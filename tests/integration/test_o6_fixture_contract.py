"""Phase 13：O6 fixture 與核定紀錄的一致性。

核定紀錄是文件與 fixture，不是第十一個業務實體；`approved_by` 為空的來源一律 blocked，
下游 Phase 不得替它補猜清單。本檔不呼叫 AWS、不呼叫模型、不連 GitHub。
"""

import json
from pathlib import Path

from training_kb.source_ids import (
    approved_stable_keys,
    github_ticket_id,
    github_user_id,
    load_source_approvals,
    render_mapping_table,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures"
MAPPING_REPORT = REPO_ROOT / "docs" / "plan" / "report" / "o6-mapping.md"
MAPPING_HEADER = (
    "| domain | event_type | adapter | STABLE_KEYS | fixture "
    "| 事件 ID 編碼 | 穩定 user 來源 | 核定者 | 核定日期 |"
)


def test_unapproved_source_is_blocked_and_fixture_matches_keys() -> None:
    approvals = load_source_approvals(FIXTURE_ROOT / "o6/approved-sources.json")
    keys = approved_stable_keys(approvals)
    assert keys[("github.com", "issues")] == frozenset(
        {"action", "issue", "repository", "sender"}
    )
    # 2026-09-17 交接：五列都以 Demo 用途核定，手動來源不再 blocked。
    assert ("discord.com", "manual_batch") in keys
    for row in approvals:
        payload = json.loads((FIXTURE_ROOT / row.fixture).read_text("utf-8"))
        assert set(row.stable_keys) <= set(payload)


def test_issue_canonical_id_follows_only_the_issue_number() -> None:
    payload = json.loads((FIXTURE_ROOT / "github/issue-opened.json").read_text("utf-8"))
    owner = payload["repository"]["owner"]["login"]
    repo = payload["repository"]["name"]
    baseline_id = github_ticket_id(owner, repo, payload["issue"]["number"])
    baseline_user = github_user_id(payload["sender"]["id"])
    assert (baseline_id, baseline_user) == ("t_gh-acme-copilot-128", "u_gh-90210")

    noisy = json.loads(json.dumps(payload))
    noisy["issue"]["id"] = 9999999999
    noisy["issue"]["created_at"] = "2027-01-31T23:59:59Z"
    noisy["issue"]["title"] = "換一個完全不同的標題"
    noisy["issue"]["user"]["login"] = "kai-wong"
    noisy["sender"]["login"] = "kai-wong"
    assert github_ticket_id(owner, repo, noisy["issue"]["number"]) == baseline_id
    assert github_user_id(noisy["sender"]["id"]) == baseline_user

    noisy["issue"]["number"] = 129
    assert github_ticket_id(owner, repo, noisy["issue"]["number"]) == "t_gh-acme-copilot-129"
    assert github_user_id(noisy["sender"]["id"]) == baseline_user


def test_mapping_report_is_rendered_from_the_approval_record() -> None:
    approvals = load_source_approvals(FIXTURE_ROOT / "o6/approved-sources.json")
    table = render_mapping_table(approvals)
    report = MAPPING_REPORT.read_text("utf-8")
    assert MAPPING_HEADER in table
    assert table in report

    blocked = tuple(row for row in approvals if not row.approved)
    assert blocked == ()                       # 2026-09-17：五列都已核定（Demo 用途）
    assert len(approved_stable_keys(approvals)) == len(approvals)
    assert "待維護者核定" not in table
