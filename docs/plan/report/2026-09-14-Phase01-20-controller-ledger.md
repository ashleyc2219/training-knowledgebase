# SDD ledger — plan: docs/plan/dev-prompts/phase0914-0.md

Scope: implement docs/plan/unfinish Phase 01–20 (plus keep 00/00A/00B/phase docs in sync). Spec authority: docs/design/training-kb.md; name authority: 00A.
Branch: backend (not main). Working in-place (no worktree) — repo has 217 pending old-app deletions + untracked plan docs that a worktree would not carry.

## Rulings (preflight)
- Ruling: work in-place on branch `backend`, no git worktree — untracked plan docs + pending deletions make a worktree unusable — cost if wrong: none (branch is not main).
- Ruling: `git reset -q` once before first commit to unstage the user's pending old-app deletions; each task commits only its own explicitly added paths (`git add <files>; git commit -m .. -- <files>`), never `git add -A/.` — avoids sweeping 217 deletions into a feature commit — cost if wrong: user re-stages deletions with one command.
- Ruling: P01 pre-adds every dependency P01–P20 need (boto3, moto[dynamodb,s3], boto3-stubs, aws-cdk-lib, constructs) so parallel phases never race on pyproject.toml/uv.lock — deviates from plan text "依賴延後到使用它們的 Phase 增加" — cost if wrong: slightly larger initial install; no functional risk.
- Ruling: user directive overrides SDD default of strictly sequential single-implementer: phases that own disjoint files run in parallel waves (see below); task reviews only for high-risk phases (P05 keys, P06 repository, P10/P11 operations, P20 versioning) + final whole-branch review — cost if wrong: an unreviewed low-risk phase carries a defect to final review.
- Ruling: P01 implemented by controller (tiny, foundational, complete code in plan) — cost if wrong: none.
- Ruling: tests live in `tests/unit` and `tests/integration` (00A §3.2, AGENTS.md); the dev prompt's `test/unit` is a typo.

## Preflight conflict scan (file-sharing pairs from 00A §3.2)
| pair | shared file / interface | finding | resolution |
|---|---|---|---|
| P02→P07 | errors.py (P07 appends ObjectAlreadyExists) | append-only | sequential (P07 after P02) |
| P03→P04 | models.py | P04 extends P03 | sequential |
| P05→P10 | keys.py (+ops_pk, operation_ref) | append-only | sequential (P10 after P08) |
| P06→P07→P08→P10 | repository.py | each extends Repository | strict chain |
| P06→P07 | tests/integration/conftest.py (bucket added) | extend | sequential |
| P10→P11 | operations.py | P11 adds methods | sequential |
| P15→P16→P17→P18 | writing/client.py | each extends | strict chain |
| P01,P06,P07,P09 | pyproject.toml / uv.lock | would race | deps pre-added in P01 |
| P14→P15 | gate O5 PASS required by P15 | evidence dependency | P15 after P14 report |
| P10→P20 | OperationCoordinator used by allocate_version | interface | P20 after P10 |
| P19→P20 | rules_applied list | interface | P20 after P19 |
| P06/P08→P19 | repository list_rules / queries | interface | P19 after P08 |

## Wave plan
W0 P01 | W1 P02 ∥ P03 | W2 P04 ∥ P14 | W3 P05 ∥ P13 ∥ P15 | W4 P06 ∥ P09 ∥ P16 | W5 P07 ∥ P17 | W6 P08 ∥ P18 | W7 P10 ∥ P12 ∥ P19 | W8 P11 ∥ P20

## Progress
- Task P01: complete (commits 5b14447..581c5ac; gates: pytest 1 passed, ruff All checks passed, mypy 0 issues; marker probe 1 skipped / 1 passed; versions uv 0.11.32, py 3.12.7, pytest 8.4.2, ruff 0.16.7, mypy 1.20.2). Note: shell blocks `rm`/`node` via functions → use `command rm`/`command node`.
- W1 dispatched: P02 (opus), P03 (opus) — in progress.
- Task P02: complete (commits 4cb92c1..6b30405; 8 unit tests, ruff/mypy green; no separate review per ruling). Concern noted: `IngressError.fields` sorted+dedup (Phase-doc choice). P14 dispatched (opus) right after.
- Task P03: complete (commits 214f25b..e002f8a; 7 unit tests; ruff/mypy green). Ruling: StrictModel = ConfigDict(extra="forbid", frozen=True), NOT strict=True — 00A §6.2 said strict=True but D-12/D-66 and every Phase doc assume frozen, and strict rejects StepDraft(type="click_ui") — recorded as D-69 in 00A — cost if wrong: type coercion leaks into models (mitigated by P04 validators).
- W2 dispatched: P04 (opus). P14 already running.
- Task P04: complete (commits cb49ae5..5521f5c; 25 unit tests; mypy green). Carry-forward: P19 fixture `evidence=["f_12"]` must become 5 distinct feedback IDs (AuthoringRule validator). ERM note vs 00A on ProvenWorkflow.domain/adapter: 00A wins, ERM untouched.
- W3 dispatched: P05 (opus, review planned), P13 (opus). P15 pending P14.
- Task P14: complete DONE_WITH_CONCERNS (commits 8a48cf7..212ff6a; 49 passed/2 skipped; O5 report docs/plan/report/o5-20260914T170050Z.md). **O5 BLOCKED**: account 123456789012 never submitted Bedrock use-case form (GetUseCaseForModelAccess → "You have not filled out the request form"); Titan authorizationStatus NOT_AUTHORIZED (agreement AVAILABLE); Anthropic agreement NOT_AVAILABLE (needs form).
- Ruling: controller accepts Titan's first-party model agreement via create-foundation-model-agreement (reversible, no third-party terms, zero cost until used) to unblock the embedding half of O5; Anthropic use-case form requires real company details → left to user, flagged via push notification and final report — cost if wrong: user deletes the agreement with one CLI call.
- Ruling: P15–P18 proceed with fake Writer + unit tests (and real Titan integration where possible); Claude real-AWS integration tests stay BLOCKED/skipped until the form is submitted; O5 stays BLOCKED in docs — the plan's hard stop is overridden by the user's "keep working autonomously" directive — cost if wrong: Claude adapter code lacks live verification until form is filled.
- O5 follow-up: create-foundation-model-agreement not applicable ("Agreement not supported for this model" for Titan); Titan stays NOT_AUTHORIZED, InvokeModel "Operation not allowed" → account-level Bedrock enablement requires console (use-case form + model access). O5 fully BLOCKED pending user. Push notification sent 2026-09-14.
- W3 dispatched: P15 (opus) under the O5-BLOCKED ruling.
- Task P05: implemented (commits 879e285..9880f21; 102 passed/2 skipped overall; O1 accepted for key naming only, approver auto-filled as repo maintainer — needs maintainer confirmation). Review dispatched (opus) in parallel with W4.
- Ruling: data stack region = us-east-1 (same region as Bedrock; single region) — cost if wrong: redeploy to another region (RemovalPolicy RETAIN keeps data).
- W4 dispatched: P06 (opus, review planned), P09 (opus; bootstrap + deploy us-east-1). P16 waits for P15.
- Task P13: complete DONE_WITH_CONCERNS (commits 034bc57..8972d03; 11 tests; O6 mapping report docs/plan/report/o6-mapping.md — issues source approved per design §7.2, pull_request + manual sources await maintainer approval). Carry-forward: `sub_release_ids`/`render_mapping_table` added to source_ids.py (not in 00A §6.8) — add to 00A at final doc sync; P36 must read PR sub-changes from `pull_request.body` fixture format.
- Task P05 review: Needs fixes — Important: (1) parse_step_pk accepts "STEP##3"/"03"/fullwidth digits (plan-mandated code) → fix with isdecimal + non-empty version; (2) O1 approver auto-filled. Minor (bundled into same round because trivial): _bare should reject surrounding whitespace; view_pk naive/microsecond rejection untested; RELATIONS size not asserted.
- Ruling: O1 provisionally accepted by controller under the user's autonomy grant ("所有的決策都不必徵求我的同意"); decision record must say approver = controller on behalf of maintainer, pending Timmy Lin's confirmation; P06 not blocked — cost if wrong: rename META constant + tests before any real data exists (cheap).
- Ruling: P05 fix round verified by controller (focused tests + hunk read) instead of a dispatched re-review — user asked to minimize reviews — cost if wrong: a regression in a 1-line parser change slips to final review.
- Task P15: complete DONE_WITH_CONCERNS (commits a420753..7874ed0; 138 passed/4 skipped overall; live Bedrock test FAIL/skip due to O5 BLOCKED, recorded as evidence). Carry-forward: P16 must add `BedrockWriter.embed` and the `writer: Writer = BedrockWriter(...)` protocol assertion; P18's inference_config must keep Task-2 assertion `{"maxTokens":512,"temperature":0.1}` consistent.
- W4 dispatched: P16 (opus).
- Task P05: fix round 1/5 (5 addressed, 0 open; commits b8f0fbe..91f7eb0); controller verified parse_step_pk rejections + round-trip + whitespace rejection; 46 key tests green.
- Task P05: complete (commits 879e285..91f7eb0, review clean after round 1; O1 provisionally accepted pending maintainer confirmation).
- Task P09: complete (commits 4b3a433..571c852; 12 stack tests; 161 passed/5 skipped overall). Deployed: us-east-1 CDKToolkit bootstrapped; TrainingKbData CREATE_COMPLETE; table training_kb (PAY_PER_REQUEST, GSI by_target KEYS_ONLY); bucket training-kb-content-example (public access blocked, ssl-only policy); role TrainingKbData-TrainingKbDataRoleB75DED38-4EUcpdGUDCov. Carry-forward: add `infra/__init__.py` to 00A §3.2 at doc sync; infra tests need sys.path bootstrap; IAM second-person review not done.
- Task P06: implemented (commits a5c6b9f..83c2b83; 12 moto tests + real-table smoke PASS on us-east-1 training_kb; 161 passed/5 skipped overall). Also implemented item_to_model/put_meta_item/get_meta_item (00A owners P08/P10) — carry-forward: P08/P10 consume, do not re-declare. Review dispatched (opus); findings (if any) will be routed to whoever holds repository.py at the time (P07).
- W5 dispatched: P07 (opus). P17 waits for P16.
- Task P16: complete DONE_WITH_CONCERNS (commits f3690e6..57997c7; 20 passed/1 skipped own; live Titan call → PermanentError ValidationException, O5 still BLOCKED). Note: mypy gate covers src only (tests not in [tool.mypy] files) — Protocol assertion in tests needs explicit `uv run mypy src tests/...` run.
- W5 dispatched: P17 (opus).
- Task P06 review: Approved with 1 Important — put_meta_item(create_only=False) returns True on overwrite (contract says "created by me") → routed to P07 agent (holds repository.py) with tuple-codec minor + parse_pk ValueError wrap. Minors deferred to final review: update_meta not-found message conflates with stale revision; get_meta_item returns int for integral floats (raw path); _revision KeyError if item written outside Repository; 3× duplicated get_item(Key=..) call; update_meta cannot detect third-class attrs (00A design, D-40 — known risk for P20–P23 writers).
- Task P06: complete (commits a5c6b9f..83c2b83, review approved; fix carried by P07).
- Task P17: complete DONE_WITH_CONCERNS (commits 888308d..34c2424; 252 passed/5 skipped overall; added jsonschema + types-jsonschema deps — allowed exception; generate_json node name uses schema.get("$id","model"); ConflictJudgement.evidence / StepRewrite.steps shapes ruled from P55/P51 — carry to 00A doc sync).
- W6 dispatched: P18 (opus). P08 waits for P07.
- Task P07: complete (commits b1ccb3c..a74c1c9 incl. 10fa581 fix for P06 review Important + 2 minors; moto 5.2.3 IfNoneMatch probe PASS; 252 passed/5 skipped). Deferred: `get_object -> None` under the P09 data role (needs s3:ListBucket) not yet proven live; put_edge does not check relation endpoint kinds (00A generic signature; semantics owned by P23/P40/P42).
- W6 dispatched: P08 (opus). P18 running.
- Task P18: complete DONE_WITH_CONCERNS (commits 4fb1f18..f3799d3; 115 own tests; live Claude call → PermanentError ValidationException (O5 BLOCKED)). Deferred: storage-retry test uses local stand-ins (FakeObjectStore/FakeCoordinator) because P10's OperationCoordinator did not exist yet — P40/P41 (out of scope) may swap to real fixtures; inference_config uses schema.get("$id","").
- Task P08: complete (commits 918e8ab..6be0c58; 18 own tests; 287 passed/8 skipped overall). Name per 00A: `query_by_target` (not query_target). Carry-forward to 00A doc sync: add P08 as modifier of tests/integration/conftest.py (by_target GSI + paged_repository fixture). GSI eventual consistency/real paging unverified (moto only) — expected, waits O2/O3.
- W7 dispatched: P10 (opus, review planned), P12 (opus, real-AWS O3 spike on isolated table/bucket), P19 (opus).
- Task P19: complete (commits 770b8cd..fa14b3d; 14 own tests; 322 passed/8 skipped overall). Carry-forward to doc sync: 00A D-66 影響欄 add P19; 00B Rule-1 evidence lives in integration test (Phase doc §9 notes it). render_rules_block does not escape; prompt_write_tutorial wraps via _as_data (tested).
- Task P10: implemented DONE_WITH_CONCERNS (commits 6e685a9..255f12a; 16 own tests; 317 passed/8 skipped). Rulings by implementer (accepted): record_* do not change status (normalized/started reserved for P32); operation_id_for/execution_name stay with P32 ingress.py per 00A §6.8; repository.py untouched. O2 = not passed (moto only). Review dispatched (opus); findings routed to P11 (holds operations.py).
- W8 dispatched: P11 (opus; real DynamoDB O2 cases us-east-1), P20 (opus, review planned).
- Task P10 review: Approved with 3 Important — (1) record_version no write-once (plan-mandated) → routed to P11 (fix: same value no-op, different → CoordinationError), P20 informed; (2) OperationStatus normalized/started have no writer — Ruling: keep as reserved values, P32 decides; note in 00A §6.4 at doc sync — cost if wrong: P32 adds two small methods; (3) phase10-report handoff claims _existing/_write reusable for SEQ/LEASE — false (ops_pk rejects '#'), P11 warned. Minors deferred: ops_pk vs operation_ref accept sets differ; no-progress-payload test lacks attribute-set assertion; resend-with-different-now not directly asserted; record_proc_sample concurrent → CoordinationError vs False (P35 note); small redundancies (_ref_part return unused, list() vs tuple codec, double get_meta_item in load/_existing).
- Task P10: complete (commits 6e685a9..255f12a, review approved; fix carried by P11).
- Task P12: complete DONE_WITH_CONCERNS (commits 2c91299..deafd1c; 8 unit + 8 aws integration green on real AWS; isolated table/bucket deleted & confirmed 404). **O3 = FAIL** (report docs/plan/report/o3-20260914t181109z.md): cut-points a2/a3/b1/c1 show partial visibility; a1 ok; transact limit 100/2=50 items consistent with P25. Blocks P24/P25/P41/P48/P52/P57 (next batch) until a mechanism is decided; three un-approved decision exits listed in the report for the maintainer. No F49 relaxation, no CloudFront.
- Task P20: complete DONE_WITH_CONCERNS (commits 54e4d1a..611655d; 16 own tests; 351 passed/16 skipped overall excluding P11 in-progress). Ruling: P20 task review folded into the final whole-branch review (user asked to minimize reviews; final review is imminent) — cost if wrong: a versioning defect surfaces one review later.
- Task P11: complete (commits c347f7f..0b068b6 incl. 4897a6c record_version write-once fix; 356 passed/23 skipped; **O2 = PASS** on real DynamoDB isolated table training_kb_o2_20260914t182824z (deleted); report docs/plan/report/o2-20260914t182824z.md; evidence s3 operations/o2/20260914t182824z.json (+ an earlier run 20260914t182535z.json left in bucket — maintainer may delete)).
- ALL 20 PHASES IMPLEMENTED. Controller verification: `uv run pytest tests -q -W error` → 356 passed, 23 skipped; ruff src/tests/infra clean; mypy src clean (17 files).
- Final phase: whole-branch review (opus) + doc sync agent (00/00A/00B carry-forwards, Phase 01 doc ticks, REP compile) dispatched in parallel.
- Doc sync: complete (commits 309f5dc, c3b3fb5) — 00/00A/00B carry-forwards applied (D-70/71/72, gate status tables), Phase 01 doc ticked, REP drafted at docs/plan/report/2026-09-14-Phase01-20實作-REP.md (§6 final numbers pending), phase reports copied to docs/plan/report/phases/.
- Final review (opus): Mergeable after fix wave. Must-fix: (1) py.typed + mypy files include infra (+ o2_report no-any-return); (2) models.aware() must normalize to UTC and reject microseconds (two time-serialization paths; view_pk vs ts attr divergence); (3) accept() takes sequence before conditional write — CoordinationError from next_sequence must fall back to load()→duplicate; (4) acquire_lease must reject blank owner; (5) _generate_with_correction has no public entry. Deferred minors triaged: all keep deferred except mypy scope (→#1); IAM second-person review done by reviewer (pass); P20 reviewed in final pass (pass).
- Ruling: #5 resolved by code — rename to public `generate_validated_json` re-exported from `training_kb.writing`, 00A §6.5 wording updated — cost if wrong: downstream phases import a different name (trivial rename).
- Ruling: fix wave verified by controller (full gates + focused checks) instead of a dispatched scoped re-review — user asked to minimize reviews — cost if wrong: a regression in the five small fixes slips through (all have new tests).
- Fix wave dispatched (opus, single agent).
