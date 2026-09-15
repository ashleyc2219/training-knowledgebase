# Final review A (P42–P48) — findings for the fix wave

Verdict: Mergeable after fix wave. Line numbers refer to HEAD at review time (2714dcd); re-locate by symbol.

## Must fix

1. **[Critical] `task_commit_batch` skip branch claims a batch published without checking public objects** — `src/training_kb/pipelines/feedback.py` `task_commit_batch` (~1039-1049) with `_publish_split` (~964-977). When every version already has `published_at`, the Task skips the transaction, sets `published = prepared.version_ids`, writes `review-result.json`, completes the operation → Succeeded. But `Publisher._after_transaction` sets `published_at` BEFORE writing `site/` (publishing.py ~564-572), so "all published, site half-written" (cut point 4 / a3) is exactly this state; a redrive or same-day manual rerun then reports full success with public pages missing. Fix: in the skip branch require (a) every key of `publishing.public_site_keys(prepared.version_ids)` to exist and (b) evidence the batch was published under THIS operation (`operations/<op>/pending-promote.json` written first by `_publish_site`); otherwise raise `PermanentError` naming `publishing.resume_publish` as the recovery path. Add tests (site missing → PermanentError; other-operation → PermanentError; genuine → success).

2. **[Important] Versions created but unpublished are orphaned; the next run reports success with nothing published** — `feedback.py` `_guard` (~688-689) returns `None` (no_new_evidence) when `record.version_id` exists and `verify_version_complete` is true, ignoring `published_at`. After a failure at Prepare/Inspect/Commit, later runs short-circuit → `prepared_version_ids` empty → Succeeded with empty result; the version never becomes current. Fix: when the recorded version is complete but `published_at is None`, add it to `prepared` so the batch republishes it instead of reporting no new evidence. Test.

3. **[Important] `diagnose_weak` runs before the F23 short-circuit; diagnosis not persisted** — `feedback.py` ~894 `prepare_refine(diagnose_weak(...))` and `_reuse_or_call` (~655-667). A resend pays a fresh model call per target even when `_guard` returns None; and a retried diagnosis may yield different `step_indexes` while the stored refine reply is replayed → `_apply_rewrite` raises ContentError forever. Fix: check the sub-operation record and skip the target BEFORE calling `diagnose_weak`; persist/reuse the diagnosis under the same operation (same mechanism as the refine reply) or discard the stored reply when its step set no longer matches. Tests for both.

4. **[Important] Cloud path never marks the ledger failed** — `pipelines/common.py` `pipeline_task_handler` (~175-201) / `feedback_review_handler`: `run_sequence` records `operations.fail(...)` but the per-task cloud handlers don't. Fix ONCE in `pipeline_task_handler`: on exception, `operations.fail(operation_id, str(e), isinstance(e, TransientError), now=...)` then re-raise (mirror `run_sequence`); check `operations.py` transitions so a retry that later succeeds can still `complete` (adjust `_change` guards if needed). Applies to all three pipelines. Tests.

5. **[Important] Feedback IDs reach prompts unescaped** — `src/training_kb/writing/prompts.py` ~118 (`f"{row.id}: {_as_data(row.comment)}"`) and ~154 (`json.dumps(list(feedback_ids))`). `bare_id` only rejects `#`/control chars, so an id like `f_x</source_data>…` closes the data section. Fix: `_as_data(row.id)` and escape the evidence-ids payload. Test with a crafted id.

6. **[Important] `handlers/import_.py` batch contract mismatch** — docstrings promise "整批 PermanentError 零寫入 / 資料錯只拒那一筆", but `_import_one` catches only `IngressError`; `normalize_then_accept` can raise `PermanentError` (nothing canonical), `import_feedback` can raise `CoordinationError` (put_meta create_only race) or `TransientError`, aborting mid-loop with earlier items written/started. Fix: either widen the per-item catch to `PermanentError`/`CoordinationError` (row carries the failure; `TransientError` still propagates so the invocation is retried) or narrow both docstrings to "only shape errors guarantee zero writes". Ruling: widen the per-item catch for `PermanentError` and `CoordinationError`, keep `TransientError` propagating; update docstrings + tests.

7. **[Important] release `publish-request.json` lacks `prepared_at`** — `src/training_kb/pipelines/release.py` ~939-941 vs docstring ~924 claiming P48's shape; `feedback._restored` requires it. Fix: add `"prepared_at": to_iso(prepared.prepared_at)`; align key order/sort with feedback's writer; docstring.

## Ledger-triage promoted to MUST-FIX (in addition to the above)

- P48 (C): `_restored`/`_review_result` bare `json.loads`/`KeyError` → `PermanentError` (feedback.py ~956-961, ~1069, ~1082).
- P48 (A): doc/report sweep — `docs/plan/report/phases/2026-09-14-Phase48-REP.md` §1.1 (~26), §7.2 (~415, ~427-428) and Phase doc `docs/plan/unfinish/48-*.md` §7 Task 2 sketch (~445-480) + `tests/unit/test_feedback_review_flow.py` ~417 docstring still describe `_prepared`/re-prepare/non-merging result.
- Closing redeploy of TrainingKbApp (P42 fix 2 / P48 fix / P59 not deployed) — done by P60/controller, not the fix agent.

## OK-TO-DEFER (record only)

Lambda LoggingConfig INFO; `_assert_open` before `_dedupe` corner; `_record` only on success; P41 sts dead grant; import ticket/release branch cloud-unexercised (O6); stale rationale in tests/unit/infra/test_import_lambda.py ~197-202 and REP §1.2 `_item` name (fix if touching the file anyway).

## Minor (fix if cheap while in the file)

- Diverged duplication: `feedback.py` `_rules_for_hits`/`_assert_unchanged`/`_apply_rewrite` (~571-633) vs `release.py` (~411-495): release rejects duplicate step numbers, feedback keeps the last; feedback rejects changed `type`, release only `feature_id`. Make the two check sets identical (shared helper preferred, e.g. in `content.py` or a small `pipelines/rewrite.py`).
- Import Lambda bedrock grant is on the embedding ARN (never used by classify) — document; extend in two places when O5 clears.
- `import_.py` deadline unused on feedback/view path (docstring ~78-81) — check `assert_time_left` per item or fix wording.
- Resumed import re-calls the classifier when `_dedupe` returns `existing is None` on the accept-duplicate/item-missing resume (`ingress.py` ~970) — reuse stored category if any.
- `propose_candidate` returns an existing RULE regardless of status (~461-463) → retired rules listed as candidates in review-result; filter to candidate/active or document.
- `EvaluateTargets` runs all model calls for all targets in one 90 s Lambda — document the ceiling.
- `tests/integration/test_feedback_review_state_machine.py` ~220-231 deletes today's real `OPS#<review op>`/`review-result.json` — guard so it only deletes the synthetic run's records (e.g. use a distinct project_id/date suffix) or document.
