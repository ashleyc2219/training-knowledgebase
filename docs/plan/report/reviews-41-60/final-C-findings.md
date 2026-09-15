# Final review C (P41, P56–P60 + shared core) — findings for the fix wave

Verdict: Mergeable after fix wave. Line numbers refer to HEAD at review time (fc1fa25); re-locate by symbol.

## Must fix

1. **[Critical] App-stack `sts:GetCallerIdentity` on `Resource: "*"`** — `infra/training_kb_stack.py` `_grant_execution_lookup` (~546-547), on the webhook role. Ruling: delete the grant (AWS documents no permission is required); `_import_execution_arns` (~512-516) already carries the correct reasoning. Update tests; `check_iam:TrainingKbApp` must then pass without relaxing its allow-list; requires the closing redeploy + `checks` rerun.

2. **[Important] Two un-gated production-write paths in `demo/`** —
   - `demo/seed_loader.py` `cluster_demo_tickets` (~586-587) does `put_meta(..., create_only=False)` for 20 tickets and `demo/scripts/cluster_demo_tickets.py` (~117-121, ~137-140) wires it to the LIVE table/bucket via `load_settings()`; its docstring only promises local JSON output. Fix: document the DynamoDB writes and put them behind an explicit `--write` flag; refuse when `TKB_ENV=prod`.
   - `demo/cli.py` `_seed` (~195-200) → `apply_seed` (`seed_loader.py` ~517-560) overwrites canonical demo PKs (`TUTORIAL#prepare-meeting`, `RULE#R-007`, `RULE#R-012`, `FEATURE#Prepare`…) with `create_only=False` on whatever `load_settings()` resolves; only O7 being unsigned prevents it. Fix: explicit opt-in (`--apply`/`--yes`), print resolved table + bucket before writing, refuse when `TKB_ENV=prod`. Tests for the refusals.

3. **[Important] `maybe_fail_task` prod guard diverges from `faults.active_fault`** — `src/training_kb/pipelines/common.py` ~148 uses exact equality with `faults.PRODUCTION`; `faults.py` ~63 normalises `.strip().lower()`. Also `maybe_fail_task` silently ignores an unparsable `TKB_FAULT_TASK` where `active_fault` raises `PermanentError`. Fix: extract `faults.is_production(env)` used by both; `PermanentError` on a `TKB_FAULT_TASK` value that does not parse to a known `<pipeline>:<task>`. Tests.

4. **[Important] `check_secrets` excludes `docs/`** — `infra/scripts/checks.py` ~101 `SCAN_EXCLUDED_PREFIXES = ("docs/", ".superpowers/")`; `docs/plan/report/**` is where every machine-generated artifact lands. No live leak today (reviewer grepped). Fix: apply the high-precision `SECRET_PATTERNS` (AKIA / `gh?_` / PRIVATE KEY) to `docs/` too; keep only the `SECRET_ASSIGNMENT` rule excluded there; update `SECRETS_SCOPE` text; test.

5. **[Important] MET#10/11/12 green against the O7 ruling** — `checks.py` `GATE_OVERRIDES` (~1008-1054) + `evidence.json`. Fix: three override lines pointing at the Phase 56 report, then rebuild acceptance (tally 132/4/32 → 129/4/35).

6. **[Important] pytest PYSEC-2026-1845 still open** — run `uv lock --upgrade-package pytest` within `>=8,<9`; if the lock changes, rerun the full suite and commit `uv.lock`; if no fixed release exists in range, record as `not_run` with the advisory link (not a bare FAIL).

7. **[Important] `resume_publish` consistency guard is tautological; docstring overclaims** — `src/training_kb/publishing.py` ~798-800 compares `written != expected`, but `promote_site_objects` (~395) returns the computed `public_site_keys(...)`, never an observed result, so the guard can only catch a hand-corrupted pending file. Fix: either make `_promote_version`/`promote_site_objects` return the keys actually written/verified, or reword the docstring (~778-779) to "pending-promote.json 自身一致性檢查" and drop the "實際補出" claim. Bundle with the P59 doc nit (cut-point-1 mechanism row) in the same docstring.

Confirmed (already in A/B): analytics `dynamodb:PutItem` over-grant; cross-cutting `operations.fail` gap.

## `operations.fail` fix — soundness caveats (must be honoured)

- `pipeline_task_handler` holds no `Deps`; each pipeline module caches a private `_DEPS`. Cleaner: add a public `deps_for(pipeline) -> Deps` in `common.py` that owns the cache; the three `*_handler`s call it (keep their one-task contract).
- `operation_id` is available: `event["state"]["operation_id"]` survives all tasks (ASL passes `state.$: $`, tasks return `{**state, ...}`). Missing/non-str → skip recording, re-raise unchanged.
- Don't mask build failures: if `build_deps` itself raises, there is no coordinator — re-raise the original.
- Move `maybe_fail_task` inside the wrapped region so injected faults are recorded like `run_sequence` would.
- Unify `load_settings` usage (`feedback.py` uses `load_settings(os.environ)`, ticket/release `load_settings()`).
- Expect one `fail` record per ASL Retry attempt; `operations._change` has no transition guard so a later `complete` still works. Tests for all three pipelines.

## Ledger triage

- MUST-FIX: sts grant (#1); pytest upgrade (#6); MET#10/11/12 (#5); closing redeploy + checks rerun (process; the stack, `handlers/import_.py`, `publishing.py` changed after the last deploy).
- CLOSED: spike leftover deleted (404 verified); `_cleanup` empty-prefix guard.
- OK-TO-DEFER (doc sync / later): `_grant_data` widest defaults (dead); MARKERS platform check; `_gap_of` test; P41 docstring drift + REP §8 commits table; non-dict state coercion; P59 doc nits (bundle the resume_publish docstring with #7); private-method index rebuild (do `write_tutorial_index` promotion if `publishing.py` is opened anyway); comprehension side effects; lease test narrowness; Lambda LoggingConfig.

## Minor (fix if cheap while in the file)

- `check_iam`: partial wildcards (`s3:*Object`, `dynamodb:Delete*`) not caught (~253); `ManagedPolicyArns` (AWSLambdaBasicExecutionRole) invisible (~205-223) → disclose in `IAM_SCOPE` (or extend).
- `check_public`: `_is_public_principal({"AWS": ["*", "arn:…"]})` returns False due to `_flatten` join (~303-308) → handle lists element-wise; never reads Block Public Access config (~1136-1145) → add `get_public_access_block`.
- `_row_status` treats any non-empty string as pass (~975-982); Rule rows are green on collectible nodeids → wording "collected + suite green at <commit>".
- `infra/app.py` ~46-49 silent skip of TrainingKbApp → keep, but make the stderr line unmistakable.
- `base_env["TKB_ENV"]` from the deployer's shell (~234) → refuse to synth with a non-prod `TKB_ENV` unless an explicit `TKB_ALLOW_NONPROD_DEPLOY=1` (or similar) is set; document in P60 checklist.
- `render_site_index` lists retired tutorials unmarked (`site.py` ~352-356) — document only (D-83 scope).
