"""Phase 33：逐列比對 O6 核定紀錄、fixture 與 `STABLE_KEYS`。

正式程式不讀 `tests/` 路徑，`STABLE_KEYS` 是逐條抄寫的 literal；抄錯或漏抄由本檔擋下來。
`approved_by` 為空的來源一律 blocked，不得 fallback 成可重放簽名。
不需要真實 AWS、不呼叫模型、不連 GitHub，所以不標 `aws`。
"""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from training_kb.errors import PermanentError
from training_kb.rote import STABLE_KEYS, RawEvent, signature_shape, structure_signature
from training_kb.source_ids import SourceApproval, approved_stable_keys, load_source_approvals

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures"
APPROVALS = load_source_approvals(FIXTURE_ROOT / "o6/approved-sources.json")
APPROVED = [row for row in APPROVALS if row.approved_by]


def mask_values(value: object) -> object:
    """把每一個葉節點的值換成 `MASKED`，保留整個巢狀結構與所有 key 名稱。"""
    if isinstance(value, dict):
        return {name: mask_values(item) for name, item in value.items()}
    if isinstance(value, list):
        return [mask_values(item) for item in value]
    return "MASKED"


def test_stable_keys_matches_the_approval_record() -> None:
    assert dict(STABLE_KEYS) == approved_stable_keys(APPROVED)


@pytest.mark.parametrize("row", APPROVED, ids=lambda row: f"{row.domain}:{row.event_type}")
def test_approved_fixture_keeps_structure_without_values(row: SourceApproval) -> None:
    payload = json.loads((FIXTURE_ROOT / row.fixture).read_text(encoding="utf-8"))
    assert set(row.stable_keys) <= set(payload)
    event = RawEvent(row.domain, row.adapter, row.event_type, {}, payload)
    masked = replace(event, payload=mask_values(payload))
    assert signature_shape(masked) == signature_shape(event)
    assert structure_signature(masked) == structure_signature(event)


def test_pending_sources_stay_blocked() -> None:
    for row in APPROVALS:
        if row.approved_by:
            continue
        with pytest.raises(PermanentError, match="STABLE_KEYS"):
            structure_signature(RawEvent(row.domain, row.adapter, row.event_type, {}, {}))


def test_every_source_row_is_approved() -> None:
    """2026-09-17 交接：五列都以 Demo 用途核定（tests/fixtures/o6/approved-sources.json）。"""
    assert [f"{row.domain}:{row.event_type}" for row in APPROVALS if not row.approved_by] == []
