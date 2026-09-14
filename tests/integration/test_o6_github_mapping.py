"""Phase 31 Task 3：用 Phase 13 核定的 O6 fixture 做可追溯的正規化整合。

期望值一律由 Phase 13 的編碼函式產生，測試裡不另外手寫一套 ID；`(domain, event_type)`
未核定時整組斷言只能是明確 XFAIL，不得用自造 fixture 改成綠燈（設計 §18 O6）。
本檔不呼叫 AWS、不呼叫模型、不連 GitHub，所以不標 `aws` marker。
"""

import json
from pathlib import Path

import pytest

from training_kb.errors import IngressError
from training_kb.ingress import validate_release, validate_ticket
from training_kb.models import ReleaseKind
from training_kb.source_ids import (
    SourceApproval,
    approved_stable_keys,
    github_release_id,
    github_source_event_id,
    github_ticket_id,
    github_user_id,
    load_source_approvals,
    sub_release_ids,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "github"
APPROVALS = load_source_approvals(REPO_ROOT / "tests" / "fixtures" / "o6" / "approved-sources.json")
APPROVED = approved_stable_keys(APPROVALS)
ISSUE_APPROVED = bool(APPROVED.get(("github.com", "issues")))
PR_APPROVED = bool(APPROVED.get(("github.com", "pull_request")))
PROJECT_ID = "demo"  # config.DEFAULT_PROJECT_ID；MVP 只有一個專案


def load_event(name: str) -> dict[str, object]:
    payload = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def approval_of(event_type: str) -> SourceApproval:
    """核定紀錄那一列；`stable_user_source` 是「穩定 user 來自哪個欄位」的唯一權威。"""
    return next(row for row in APPROVALS
                if (row.domain, row.event_type) == ("github.com", event_type))


def owner_repo(event: dict[str, object]) -> tuple[str, str]:
    repository = event["repository"]
    assert isinstance(repository, dict)
    owner, repo = str(repository["full_name"]).split("/")
    return owner, repo


def sender_id(event: dict[str, object]) -> int:
    sender = event["sender"]
    assert isinstance(sender, dict)
    return int(sender["id"])


@pytest.mark.xfail(not ISSUE_APPROVED, strict=True, reason="O6 尚未核定")
def test_issue_fixture_maps_to_traceable_ticket() -> None:
    assert ("github.com", "issues") in APPROVED, "O6 未核定前該來源維持 blocked"
    event = load_event("issue-opened.json")
    issue = event["issue"]
    assert isinstance(issue, dict)
    owner, repo = owner_repo(event)
    payload: dict[str, object] = {
        "id": github_ticket_id(owner, repo, int(issue["number"])),
        "source": "github_issue", "text": issue["body"],
        "author": github_user_id(int(dict(issue["user"])["id"])),
        "ts": issue["created_at"], "project_id": PROJECT_ID,
    }
    ticket = validate_ticket(payload)
    assert ticket.id == github_ticket_id(owner, repo, int(issue["number"]))
    assert ticket.author == github_user_id(int(dict(issue["user"])["id"]))
    assert ticket.model_dump_json() == validate_ticket(payload).model_dump_json()
    # 穩定 user 追得回核定紀錄宣告的那個欄位，而不是測試自己挑的欄位。
    assert approval_of("issues").stable_user_source == "sender.id"
    assert ticket.author == github_user_id(sender_id(event))
    # 接入當下不得有任何分析欄位。
    assert (ticket.cluster_id, ticket.feature_ids, ticket.embedding) == (None, [], None)


@pytest.mark.xfail(not ISSUE_APPROVED, strict=True, reason="O6 尚未核定")
def test_issue_without_author_is_rejected_and_creates_nothing() -> None:
    """ING Rule 22：抽不到穩定 user 就整筆拒絕，不補猜、不留下半成品。"""
    assert ("github.com", "issues") in APPROVED, "O6 未核定前該來源維持 blocked"
    event = load_event("issue-opened.json")
    issue = event["issue"]
    assert isinstance(issue, dict)
    owner, repo = owner_repo(event)
    payload: dict[str, object] = {
        "id": github_ticket_id(owner, repo, int(issue["number"])),
        "source": "github_issue", "text": issue["body"],
        "ts": issue["created_at"], "project_id": PROJECT_ID,
    }
    with pytest.raises(IngressError) as error:
        validate_ticket(payload)
    assert error.value.fields == ("author",)


def pr_changes(body: str) -> tuple[dict[str, str], ...]:
    """把 fixture `pull_request.body` 的「功能變更」條列讀成候選欄位。

    真正的抽取工具是 Phase 36 的 `parse_pr_diff`；這裡只扮演 adapter 的角色，
    讓本 Phase 驗證「抽取之後」的 canonical 結果（ING Rule 23 的 primary 在 Task 2）。
    """
    changes: list[dict[str, str]] = []
    for line in body.splitlines():
        if not line.startswith("- ") or ": " not in line:
            continue
        kind, rest = line.removeprefix("- ").split(": ", 1)
        old_name, _, new_name = rest.partition(" -> ")
        changes.append({"kind": kind, "evidence": line,
                        "feature": new_name or old_name,
                        "old_name": old_name if new_name else "",
                        "new_name": new_name})
    return tuple(changes)


@pytest.mark.xfail(not PR_APPROVED, strict=True, reason="O6 尚未核定 github.com/pull_request")
def test_pr_fixture_maps_to_sub_releases_sharing_one_source_event() -> None:
    assert ("github.com", "pull_request") in APPROVED, "O6 未核定前該來源維持 blocked"
    event = load_event("pull-request-merged.json")
    pull_request = event["pull_request"]
    assert isinstance(pull_request, dict)
    owner, repo = owner_repo(event)
    number = int(event["number"])
    changes = {change["feature"]: change for change in pr_changes(str(pull_request["body"]))}
    assert len(changes) == 2  # 一則 Release 含兩個 Feature 變更（設計 F14）

    releases = [
        validate_release({
            "id": release_id,
            "source_event_id": github_source_event_id(owner, repo, number),
            "source": "github_pr", "feature": feature,
            "kind": changes[feature]["kind"], "evidence": changes[feature]["evidence"],
            "ts": pull_request["merged_at"],
        } | {key: changes[feature][key] for key in ("old_name", "new_name")
             if changes[feature][key]})
        for feature, release_id in sub_release_ids(owner, repo, number, tuple(changes))
    ]

    expected_event_id = github_source_event_id(owner, repo, number)
    assert expected_event_id == "gh-acme-copilot-pr42"
    assert {release.source_event_id for release in releases} == {expected_event_id}
    # 子 Release 依 k 升序，ID 一律來自 Phase 13 的編碼函式。
    assert [release.id for release in releases] == [
        github_release_id(owner, repo, number, k) for k in (1, 2)
    ]
    assert str(number) not in {release.id for release in releases}  # PR 編號不單獨當 ID
    # ING Rule 23：接入當下 feature 與 kind 就已解析完成。
    assert all(release.feature and isinstance(release.kind, ReleaseKind) for release in releases)
    renamed = [release for release in releases if release.kind is ReleaseKind.RENAMED]
    assert [(release.old_name, release.new_name) for release in renamed] == [
        ("Meeting Summary", "Prepare")
    ]
    # 穩定 user 同樣只由 Phase 13 的編碼函式產生（`Release` 本身不存作者）。
    assert approval_of("pull_request").stable_user_source == "sender.id"
    assert github_user_id(sender_id(event)) == f"u_gh-{sender_id(event)}"
