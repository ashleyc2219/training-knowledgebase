"""Phase 33：`RawEvent` 與結構簽名的單元測試。

這裡只驗「簽名素材的邊界」：可信入口脈絡缺一不可、未核定的 `(domain, event_type)`
一律拒絕，以及簽名只看結構不看值。不連 AWS、不呼叫模型、不讀 fixture 檔。
"""

from dataclasses import replace

import pytest

from training_kb.errors import PermanentError
from training_kb.rote import RawEvent, structure_signature


def test_unknown_event_type_is_blocked() -> None:
    event = RawEvent("github.com", "github_pr", "pull_request", {}, {})
    with pytest.raises(PermanentError, match="STABLE_KEYS"):
        structure_signature(event)


def test_untrusted_context_is_rejected() -> None:
    event = RawEvent("", "", "issues", {}, {"action": "opened"})
    with pytest.raises(PermanentError, match="可信"):
        structure_signature(event)


# --- 簽名只看結構，不看任何事件值 ---------------------------------------------

ISSUE_PAYLOAD = {
    "action": "opened",
    "issue": {"number": 128, "title": "會前摘要在哪裡開啟？"},
    "repository": {"full_name": "acme/copilot"},
    "sender": {"login": "kai-w", "id": 90210},
}
ISSUE_HEADERS = {"X-GitHub-Event": "issues", "X-GitHub-Delivery": "d-1", "X-Request-Id": "r-1"}


@pytest.fixture
def issue_event() -> RawEvent:
    return RawEvent("github.com", "github_issue", "issues", ISSUE_HEADERS, ISSUE_PAYLOAD)


def test_signature_is_sixteen_lowercase_hex(issue_event: RawEvent) -> None:
    signature = structure_signature(issue_event)
    assert len(signature) == 16
    assert set(signature) <= set("0123456789abcdef")


@pytest.mark.parametrize(
    "changes",
    [
        {
            "payload": {
                **ISSUE_PAYLOAD,
                "action": "closed",
                "sender": {"login": "another-user", "id": 1},
                "issue": {"number": 999, "title": "different"},
            }
        },
        {
            "headers": {
                "x-github-delivery": "d-2",
                "X-GITHUB-EVENT": "issue_comment",
                "Content-Type": "application/json",
            }
        },
        {"payload": {**ISSUE_PAYLOAD, "installation": {"id": 7}}},
    ],
    ids=["event-values", "header-case-value", "unapproved-key"],
)
def test_signature_ignores_everything_but_structure(
    issue_event: RawEvent, changes: dict
) -> None:
    assert structure_signature(replace(issue_event, **changes)) == structure_signature(issue_event)


def test_missing_approved_key_changes_signature(issue_event: RawEvent) -> None:
    trimmed = {name: value for name, value in ISSUE_PAYLOAD.items() if name != "repository"}
    assert structure_signature(replace(issue_event, payload=trimmed)) != structure_signature(
        issue_event
    )
