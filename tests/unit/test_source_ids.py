"""Phase 13：來源 ID 編碼與穩定使用者的單元測試。

Task 1 鎖定四個 `github_*` 編碼函式的確定性與拒絕規則，Task 2 鎖定穩定使用者只能來自來源。
"""

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from training_kb.errors import IngressError
from training_kb.models import Feedback, Ticket, TutorialView
from training_kb.source_ids import (
    github_release_id,
    github_source_event_id,
    github_ticket_id,
    github_user_id,
    stable_user_from_import,
    sub_release_ids,
)

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures"
CHANGE_LINE = re.compile(r"^- (?P<kind>renamed|changed|removed): (?P<detail>.+)$", re.MULTILINE)


def pull_request_payload() -> dict:
    return json.loads((FIXTURE_ROOT / "github/pull-request-merged.json").read_text("utf-8"))


def manual_payload(name: str) -> dict:
    return json.loads((FIXTURE_ROOT / "manual" / name).read_text("utf-8"))


def changed_features(payload: dict) -> list[str]:
    """從 PR body 取出這次改到的 Feature 名稱；renamed 取箭頭右邊的新名稱。"""
    body = payload["pull_request"]["body"]
    return [match["detail"].split("->")[-1].strip() for match in CHANGE_LINE.finditer(body)]


def test_github_ids_are_deterministic_and_never_bare_pr_number() -> None:
    assert github_ticket_id("Acme", "Copilot", 128) == "t_gh-acme-copilot-128"
    assert github_release_id("acme", "copilot", 42, 1) == "r_gh-acme-copilot-pr42-1"
    assert github_release_id("acme", "copilot", 42, 2) != "r_gh-acme-copilot-pr42-1"
    assert github_source_event_id("acme", "copilot", 42) == "gh-acme-copilot-pr42"
    with pytest.raises(IngressError) as error:
        github_ticket_id("acme/evil", "copilot", 1)
    assert error.value.fields == ("owner",)
    with pytest.raises(IngressError):
        github_release_id("acme", "copilot", 42, 0)


def test_same_pull_request_fixture_always_yields_the_same_sub_release_ids() -> None:
    payload = pull_request_payload()
    owner = payload["repository"]["owner"]["login"]
    repo = payload["repository"]["name"]
    pr_number = payload["pull_request"]["number"]
    features = changed_features(payload)
    assert sorted(features) == ["Legacy Export", "Prepare"]

    first = sub_release_ids(owner, repo, pr_number, features)
    second = sub_release_ids(owner, repo, pr_number, list(reversed(features)))
    assert first == second
    assert first == (
        ("Legacy Export", "r_gh-acme-copilot-pr42-1"),
        ("Prepare", "r_gh-acme-copilot-pr42-2"),
    )

    ids = [release_id for _, release_id in first]
    assert len(set(ids)) == len(ids)
    assert "42" not in ids
    event_id = github_source_event_id(owner, repo, pr_number)
    assert event_id == "gh-acme-copilot-pr42"
    assert all(release_id.startswith(f"r_{event_id}-") for release_id in ids)


def test_sub_release_ids_reject_empty_and_duplicated_features() -> None:
    for bad in ([], ["Prepare", "Prepare"], [" "]):
        with pytest.raises(IngressError) as error:
            sub_release_ids("acme", "copilot", 42, bad)
        assert error.value.fields == ("feature",)


SENDER = {"login": "kai-w", "id": 90210, "type": "User"}


@pytest.mark.parametrize("bad", ["", "  ", "Kai Wong", "u_01!"])
def test_stable_user_comes_only_from_source(bad: str) -> None:
    renamed = {**SENDER, "login": "kai-wong"}
    assert github_user_id(SENDER["id"]) == "u_gh-90210"
    assert github_user_id(renamed["id"]) == "u_gh-90210"
    with pytest.raises(IngressError) as error:
        stable_user_from_import(bad)
    assert error.value.fields == ("user",)


def test_stable_user_is_one_string_across_ticket_feedback_and_view() -> None:
    discord = manual_payload("discord-message.json")
    email = manual_payload("support-email.json")
    changelog = manual_payload("changelog-entry.json")

    authors = {
        stable_user_from_import(item["author"])
        for payload in (discord, email)
        for item in payload["items"]
    }
    assert authors == {"u_03"}
    # changelog 是 Release 匯入檔，穩定 user「不適用」：不得為了湊欄位補一個使用者。
    assert all("author" not in item and "user" not in item for item in changelog["items"])

    user = authors.pop()
    ticket = Ticket(**discord["items"][0], source=discord["source"])
    feedback = Feedback(id="f_31", tutorial_version="prepare-meeting@v2", rating=4, user=user)
    view = TutorialView(
        tutorial_version="prepare-meeting@v2",
        user=user,
        ts=datetime(2026, 9, 5, 6, 30, tzinfo=UTC),
    )
    assert ticket.author == feedback.user == view.user == user
    assert (ticket.author, feedback.user, view.user) == ("u_03", "u_03", "u_03")
