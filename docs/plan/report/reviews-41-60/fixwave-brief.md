# Fix wave brief — Phase 41–60 final review (one agent, one pass)

You are the single fix-wave implementer. Three area reviews (A: P42–P48, B: P49–P55, C: P41/P56–P60) produced the findings below. Fix **all MUST-FIX items** in one pass, commit per logical group (own paths only; never amend/reset/rebase), then redeploy and regenerate the evidence. A single scoped re-review follows; residuals go to the controller.

Read first: `.superpowers/sdd/phase0914-2/COMMON.md` (R3 shared-file rules are moot now — you are the only writer — but R8 commit trailers, R9 no subagents, R11 security still apply) and `IMPLEMENTER.md` §做法 (TDD: add a failing test for each behavioural fix before changing code).

## Inputs (read all three in full)
- `.superpowers/sdd/phase0914-2/reviews/final-A-findings.md`
- `.superpowers/sdd/phase0914-2/reviews/final-B-findings.md`
- `.superpowers/sdd/phase0914-2/reviews/final-C-findings.md`

## Controller rulings that bind the fixes
1. `pipeline_task_handler` (pipelines/common.py) records `operations.fail(operation_id, str(e), isinstance(e, TransientError), now=...)` then re-raises — ONE place for all three pipelines; `operations._change` has no transition guard so a later retry can still `complete`. Add unit tests per pipeline (fail recorded + re-raised; retry-then-complete works). Keep the one-task dispatch contract and the "handlers never catch" semantics (record + re-raise is not catching). Honour the soundness caveats in `final-C-findings.md` (public `deps_for(pipeline)` accessor owning the cache; skip recording when `operation_id` is missing; never mask a `build_deps` failure; move `maybe_fail_task` inside the wrapped region; unify `load_settings` usage).
16. Area C must-fix items (`final-C-findings.md` #1–#7): sts grant removal; `demo/` write paths gated (`--write` / `--apply`, refuse under `TKB_ENV=prod`, print resolved table+bucket); `faults.is_production` shared by `maybe_fail_task` and `active_fault` + `PermanentError` on unparsable `TKB_FAULT_TASK`; `check_secrets` high-precision patterns over `docs/`; MET#10/11/12 overrides; pytest advisory; `resume_publish` guard/docstring.
2. `task_commit_batch` skip branch (feedback.py): only treat as already-published when every `publishing.public_site_keys(prepared.version_ids)` object exists AND `operations/<op>/pending-promote.json` (this operation) exists; otherwise `PermanentError` naming `publishing.resume_publish`. Tests for all three cases.
3. `_guard` (feedback.py): a recorded version that is complete but `published_at is None` is added to `prepared` (republish), not "no new evidence". Test.
4. `prepare_refine` path: check the sub-operation record BEFORE `diagnose_weak`; persist the diagnosis under the operation (same mechanism as the refine reply) and reuse it on resend; if a stored refine reply's step set no longer matches, discard it (call again) rather than failing forever. Tests.
5. Prompts: escape feedback ids with `_as_data` and escape the evidence-ids payload. Test with a crafted `</source_data>` id.
6. `handlers/import_.py`: per-item catch widened to `PermanentError` and `CoordinationError` (row → rejected with message); `TransientError` still propagates; docstrings aligned; tests.
7. Release `publish-request.json`: add `prepared_at` (same shape/sort as feedback's writer); fix the three false claims ("audit record only; not a resume input today"); update the pinned test.
8. Analytics Lambda IAM: drop `dynamodb:PutItem`; fix doc row; negative assertion in `tests/unit/infra/test_analytics_stack.py`.
9. App stack: remove the `sts:GetCallerIdentity` (`Resource: *`) grant from `_grant_execution_lookup` (AWS: no permission required); update tests; `check_iam` must then pass without relaxing its allow-list.
10. `validate_rules_action`: read back prior `RuleEvaluation`s for the rule (from `record_evaluation`'s stored evidence) before `next_status` so per-batch invocations can reach retirement; if the stored format makes that non-trivial, document the caller obligation + test instead. Say which you did.
11. P48 (C): `_restored`/`_review_result` malformed/legacy records → `PermanentError` (not KeyError/JSONDecodeError). Test.
12. `checks.py`/acceptance: MET#10/11/12 rows → `not_run` under O7 (three-line override, documented).
13. pytest PYSEC-2026-1845: `uv lock --upgrade-package pytest` within `>=8,<9`; if the lock changes, run the full suite and commit `uv.lock`; if no fixed release exists, record in the report.
14. Doc/report sweeps listed as MUST-FIX in the findings files (P48 `_prepared` remnants in REP §1.1/§7.2 and Phase doc §7 Task 2 + test docstring; P52 claims; P59 §7 Step 4A item 2 / appendix A.1 wording / resume_publish cut-point-1 mechanism; P42 stale rationale + REP §1.2 `_item`). Keep edits minimal and factual.
15. Minor items marked "fix if cheap while in the file" in the findings: do them when you are already editing that file; otherwise leave and list them in the report.

## Closing steps (you do these at the end)
- `uv run pytest tests -q -W error` → all green (report the numbers); `uv run ruff check src tests infra demo`; `uv run mypy`.
- Redeploy so the cloud matches HEAD: `uv run python -m infra.scripts.build_lambda_layer && AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 TKB_CONTENT_BUCKET=training-kb-content-example command npx aws-cdk@2 deploy TrainingKbApp --exclusively --require-approval never --outputs-file /private/tmp/claude-501/-Users-example-user-AWS-Hackathon/50631fdd-e096-4d3a-95e3-283b07af8087/scratchpad/cdk-outputs-fixwave.json`. Record the deployed HEAD SHA.
- One real `aws lambda invoke` of `training-kb-analytics` with `{"action":"validate_rules", ...}` (a minimal, honest payload — use the seed batches from `demo/seed` if the handler accepts them, else an empty/undecidable batch) and record the response (closes P55's "cloud invoke left to P59/P60").
- Re-run P60's evidence: `uv run python -m infra.scripts.checks run_all` (or whatever `checks.py` exposes — see `docs/plan/report/phases/2026-09-14-Phase60-REP.md`), so `evidence.json` and a new `acceptance-<ts>.md`/`security-<ts>.md`/`snyk-<ts>.md` reflect the fixed code; `check_iam` should now pass; O3/O5/O6/O7 rows stay honest.
- Optionally re-run the P41/P48/P52 `aws`-marked state-machine tests (`TKB_RUN_AWS_INTEGRATION=1 TKB_CONTENT_BUCKET=<bucket> uv run pytest tests/integration/test_ticket_state_machine.py tests/integration/test_feedback_review_state_machine.py tests/integration/test_release_update_state_machine.py -q`) to prove the redeployed functions still behave; record results.

## Report
`docs/plan/report/phases/2026-09-14-FixWave-41-60-REP.md`: per finding → what changed (file:function), covering tests, command + output; closing gate numbers; deploy SHA; evidence files regenerated; items left (with reason). Commit the report last. Reply to the controller in ≤15 lines: status, commits, gate numbers, deploy SHA, anything left open.
