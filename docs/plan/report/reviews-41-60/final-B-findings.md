# Final review B (P49–P55) — findings for the fix wave

Verdict: Mergeable after fix wave. Line numbers refer to HEAD at review time (2714dcd); re-locate by symbol.

## Must fix

1. **Release `publish-request.json`: false "same shape" claim; no reader today** — `src/training_kb/pipelines/release.py` `task_publish_batch` (~938-942) writes only `{version_ids, staged_keys}`; docstrings at ~667-668 and ~923-924 claim P48's shape and that P59's resend reads it; neither is true (P48 writes `prepared_at`; `feedback._restored` requires it; `publishing._resume_targets` never reads this key). Test `tests/unit/test_release_asl.py` ~411-427 pins the two-key shape. Fix: add `"prepared_at": to_iso(prepared.prepared_at)` (same writer shape/sort as feedback's), update the test assertion, and rewrite the three claims to "audit record only; not a resume input today". (Same as final-A item 7.)

2. **`dynamodb:PutItem` over-grant on the analytics Lambda** — `infra/training_kb_stack.py` `ANALYTICS_DDB_ACTIONS` (~121) and doc table (~129) justify PutItem by P55 `apply_rule_status`, which only uses GetItem/UpdateItem (+ S3 put). PutItem replaces whole META items on the single table. Fix: drop `PutItem` from the analytics actions, fix the doc row, extend `tests/unit/infra/test_analytics_stack.py` (~112) negative set to assert `PutItem` absent. Redeploy is covered by the closing redeploy.

3. **Cloud failures never reach `OperationCoordinator.fail`** — `src/training_kb/pipelines/common.py` `pipeline_task_handler` (~175-201). Verified: `operations._change` has no legal-transition guard, so a later retry can still `complete` after a recorded `failed`. Fix ONCE: wrap the dispatched call — on exception `deps.operations.fail(operation_id, str(e), isinstance(e, TransientError), now=deps.now())` then re-raise; obtain `operations` from the pipeline module's `_DEPS`/`build_deps` path without changing the one-task contract; unit tests for all three pipelines (fail recorded, error re-raised, retry → complete still works). (Same as final-A item 4.)

4. **`validate_rules` retirement can silently never fire** — `src/training_kb/handlers/analytics.py` `validate_rules_action` (~94-121) groups only the batches present in this invocation; `record_evaluation` evidence under `operations/analytics/rule-validation/<rule_id>/` is never read back, so per-batch invocations can never reach "two consecutive non-overlapping non-improving batches → retired" (VAL Rule 5/6) with no warning. Fix (minimum): document the caller obligation ("pass the rule's full decisive history in one call") in the docstring + a test pinning it; better: read prior `RuleEvaluation`s for the rule before `next_status`. Ruling: implement the better variant if `record_evaluation`'s stored format makes it a small read-back; otherwise document + test.

## Ledger triage → MUST-FIX

- P55 cloud invoke of `validate_rules`: deployed analytics Lambda lacks the branch → closing redeploy + one real invoke (controller/P60 step, not the fix agent).

## Minor (fix if cheap while in the file)

- Third copy of the "active + current + published" predicate: `release.py` `_current_published` (~303-324) duplicates `feedback.current_published_versions` (~159-179); `release.py` already imports from `feedback` → reuse.
- `release_update_handler` has no unit test for one-task dispatch / unknown task → add (mirror `tests/unit/pipelines/test_ticket_flow.py` ~380-460).
- Lease scope literal `f"TUTORIAL#{slug}"` at `release.py` ~644 and `feedback.py` ~738 → `keys.tutorial_pk(slug)`.
- `handlers/analytics.py` ~86-89, ~104: `SeedBatch(**raw)`, `event["now"]`, `event["batches"]` raise TypeError/KeyError/ValueError instead of the promised `PermanentError` → wrap.
- `task_retire` docstring (~772-785): say `retire.json.successor` records the requested value, not the written one.
- `Publisher._write_tutorial_index` has two external callers (`release.py` ~798, `publishing.resume_publish`) → promote to a public method (`write_tutorial_index`) and update callers.
- `_two_unimproved` (`analytics/validation.py` ~162-167) only inspects the last two decisive batches → document the edge (or scan for any non-overlapping non-improving pair).
- `update_feature_aliases` uniqueness check not concurrency-safe (~219-231) → document.
- `_wiring` caches approved categories for the container lifetime → document.
- Site index (`site.py` ~345-356) lists retired tutorials unmarked — scope observation (D-83 limited P52 to the tutorial index); document only.

## OK-TO-DEFER (record only)

`_semantic_match` no cache; repeated full scans in `analytics/version.py`; real FEATURE#Prepare field comparison; P51 aws retry test not executed; VAL Rule 4 `validated_conflict` has no production caller (O5).
