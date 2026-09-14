"""Phase 37 Task 2：REL Rule 1 的 primary 斷言——從 PR diff 或 changelog 抽出四個欄位。

直接從 O6 核定紀錄指定的原始 fixture 跑 `parse_* -> normalize_release -> validate`，
對 `feature`／`kind`／`old_name`／`new_name` 四欄與 Phase 13 算出的 ID 直接斷言；
**不是**拿 Phase 31 的欄位 validator 當抽取實作。未核定的來源維持 gate failure
（`xfail(strict=True)`：補臨時 mapping 讓它變綠會 XPASS 成紅燈）。

本檔不連 AWS、不呼叫模型，所以不標 `aws` marker（00A §3.2）。
"""

import json
from pathlib import Path
from typing import Any

import pytest

from training_kb.adapters import default_registry
from training_kb.models import ReleaseKind
from training_kb.source_ids import (
    github_release_id,
    github_source_event_id,
    load_source_approvals,
    sub_release_ids,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "fixtures"
APPROVALS = {(row.domain, row.event_type): row
             for row in load_source_approvals(FIXTURES / "o6" / "approved-sources.json")}
CASES = [("github.com", "pull_request", "parse_pr_diff"),
         ("changelog.local", "manual_batch", "parse_changelog")]
KINDS = {kind.value for kind in ReleaseKind}


def gate(domain: str, event_type: str) -> tuple[pytest.MarkDecorator, ...]:
    """未核定的來源掛 `xfail(strict=True)`：斷言照跑、逐列印出 blocked 原因，
    而且一旦有人補臨時 mapping 讓它通過就會 XPASS 被判成紅燈（與 Phase 36 同一種表達）。"""
    if APPROVALS[(domain, event_type)].approved:
        return ()
    return (pytest.mark.xfail(strict=True, reason=f"O6 尚未核定 {domain}/{event_type}"),)


CASE_PARAMS = [pytest.param(domain, event_type, parser, id=f"{domain}:{event_type}",
                            marks=gate(domain, event_type))
               for domain, event_type, parser in CASES]


def payload_of(domain: str, event_type: str) -> dict[str, Any]:
    row = APPROVALS[(domain, event_type)]      # 核定紀錄缺這一列就是 KeyError，不吞錯
    loaded: dict[str, Any] = json.loads((FIXTURES / row.fixture).read_text(encoding="utf-8"))
    return loaded


@pytest.mark.parametrize(("domain", "event_type", "parser"), CASE_PARAMS)
def test_extraction_produces_the_four_change_fields(domain: str, event_type: str,
                                                    parser: str) -> None:
    row = APPROVALS[(domain, event_type)]
    assert row.approved_by, (
        f"O6 gate：({domain}, {event_type}) 尚未核定，不得以臨時 mapping 讓測試變綠")
    registry = default_registry()
    payload = payload_of(domain, event_type)
    parsed = registry.run(parser, {"payload": payload})
    changes = parsed["changes"]
    validated = [registry.run("validate", {"candidate": registry.run(
        "normalize_release", {"parsed": parsed, "index": k})})
        for k in range(1, len(changes) + 1)]
    assert validated, "抽取結果至少要有一筆功能變更"
    for release in validated:
        assert release["feature"] and release["kind"] in KINDS
        if release["kind"] == ReleaseKind.RENAMED:
            assert release["old_name"] and release["new_name"]
    renamed = [release for release in validated if release["kind"] == ReleaseKind.RENAMED]
    assert renamed, "兩份 fixture 都含一筆改名，old_name／new_name 必須被抽出來"
    assert registry.run("normalize_release", {"parsed": parsed})["id"] == validated[0]["id"]
    if domain != "github.com":
        return
    owner = payload["repository"]["owner"]["login"]
    repo, number = payload["repository"]["name"], payload["number"]
    assert validated[0]["source_event_id"] == github_source_event_id(owner, repo, number)
    assert validated[0]["id"] == github_release_id(owner, repo, number, 1)
    assert len({release["source_event_id"] for release in validated}) == 1


@pytest.mark.xfail(not APPROVALS[("github.com", "pull_request")].approved, strict=True,
                   reason="O6 尚未核定 github.com/pull_request")
def test_pr_sub_release_order_matches_phase13() -> None:
    """`parse_pr_diff` 的 `changes` 順序必須與 Phase 13 的 `sub_release_ids` 一致。

    兩邊都依 Feature 名稱升序配 `k`；任一邊改掉排序，同一個 PR 就會長出兩組不同的
    `r_` ID（Phase 36 報告 §9 第 4 點指名要補的交叉比對）。
    """
    row = APPROVALS[("github.com", "pull_request")]
    assert row.approved_by, (
        "O6 gate：(github.com, pull_request) 尚未核定，不得以臨時 mapping 讓測試變綠")
    registry = default_registry()
    payload = payload_of("github.com", "pull_request")
    parsed = registry.run("parse_pr_diff", {"payload": payload})
    owner = payload["repository"]["owner"]["login"]
    repo, number = payload["repository"]["name"], payload["number"]
    expected = sub_release_ids(owner, repo, number,
                               [change["feature"] for change in parsed["changes"]])
    actual = [(change["feature"],
               registry.run("normalize_release", {"parsed": parsed, "index": k})["id"])
              for k, change in enumerate(parsed["changes"], start=1)]
    assert actual == list(expected)
