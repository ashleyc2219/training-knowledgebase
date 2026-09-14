"""Phase 30 Task 2／3：驗簽先於 JSON parse，以及八秒整體期限。

這支測試不碰真實 AWS（純函式＋monkeypatch spy），所以不標 `aws` marker。
"""

import base64
import hashlib
import hmac
from collections.abc import Callable
from pathlib import Path
from time import monotonic
from types import SimpleNamespace
from typing import Any

import pytest

from training_kb.errors import PermanentError
from training_kb.handlers import github_webhook
from training_kb.ingress import assert_time_left, normalize_then_accept, time_left

SECRET = b"test-secret"
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "github" / "issue-opened.json"
ACCEPTED: dict[str, Any] = {"ok": True, "operation_id": "op-ticket-t_881",
                            "operation_ids": ["op-ticket-t_881"]}
"""成功回應的形狀（裁決 D-73）：`operation_id` 是第一筆，`operation_ids` 列出全部。"""


def sign(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET, body, hashlib.sha256).hexdigest()


def make_event(
    body: bytes,
    *,
    header: str | None,
    base64_encoded: bool = False,
    event_type: str = "issues",
    signature_key: str = "x-hub-signature-256",
) -> dict[str, Any]:
    payload = base64.b64encode(body).decode("ascii") if base64_encoded else body.decode("utf-8")
    headers = {"x-github-event": event_type, "x-github-delivery": "d-001"}
    if header:
        headers[signature_key] = header
    return {"headers": headers, "body": payload, "isBase64Encoded": base64_encoded}


Spies = tuple[list[bytes], list[dict[str, Any]]]


@pytest.fixture
def spies(monkeypatch: pytest.MonkeyPatch) -> Spies:
    parsed: list[bytes] = []
    accepted: list[dict[str, Any]] = []

    def fake_parse_json(raw: bytes) -> dict[str, Any]:
        parsed.append(raw)
        return {"action": "opened"}

    def fake_accept(**passed: Any) -> list[SimpleNamespace]:  # 六個參數都是 keyword
        accepted.append(passed)
        return [SimpleNamespace(operation_id="op-ticket-t_881")]   # D-73：回 list

    monkeypatch.setattr(github_webhook, "load_secret", lambda: SECRET)
    monkeypatch.setattr(github_webhook, "parse_json", fake_parse_json)
    monkeypatch.setattr(github_webhook, "normalize_then_accept", fake_accept)
    return parsed, accepted


def test_bad_signature_never_reaches_parser(spies: Spies) -> None:
    parsed, accepted = spies
    body = FIXTURE.read_bytes()
    result = github_webhook.handler(make_event(body, header="sha256=" + "0" * 64), None)
    assert result["ok"] is False
    assert result["fields"] == ["X-Hub-Signature-256"]
    assert parsed == [] and accepted == []  # parser 與接受路徑都 0 次


def test_valid_signature_passes_exact_bytes_to_parser(spies: Spies) -> None:
    parsed, accepted = spies
    body = FIXTURE.read_bytes()
    result = github_webhook.handler(make_event(body, header=sign(body)), None)
    assert result == ACCEPTED
    assert parsed == [body] and len(accepted) == 1  # 交給 parser 的是原封不動的 bytes
    assert accepted[0]["domain"] == "github.com" and accepted[0]["adapter"] == "github_issue"
    assert accepted[0]["event_type"] == "issues"  # 來自 X-GitHub-Event，不從 payload 猜
    assert accepted[0]["headers"]["x-github-delivery"] == "d-001"  # header 一律小寫鍵
    assert accepted[0]["payload"] == {"action": "opened"}


def test_missing_signature_header_is_rejected(spies: Spies) -> None:
    """Rule 2：沒有簽名的請求直接拒絕，parser 與接受路徑都 0 次。"""
    parsed, accepted = spies
    result = github_webhook.handler(make_event(FIXTURE.read_bytes(), header=None), None)
    assert result["ok"] is False
    assert result["fields"] == ["X-Hub-Signature-256"]
    assert result["operation_id"] is None
    assert parsed == [] and accepted == []


def test_base64_body_is_decoded_to_the_original_bytes(spies: Spies) -> None:
    parsed, accepted = spies
    body = FIXTURE.read_bytes()
    event = make_event(body, header=sign(body), base64_encoded=True)
    result = github_webhook.handler(event, None)
    assert result == ACCEPTED
    assert parsed == [body]  # decode 後與原檔 bytes 完全相同
    assert len(accepted) == 1


def test_invalid_base64_body_never_reaches_parser(spies: Spies) -> None:
    parsed, accepted = spies
    event = {"headers": {"x-github-event": "issues", "x-hub-signature-256": "sha256=" + "0" * 64},
             "body": "!!!not-base64!!!", "isBase64Encoded": True}
    result = github_webhook.handler(event, None)
    assert result["ok"] is False
    assert result["fields"] == ["body"]
    assert parsed == [] and accepted == []


@pytest.mark.parametrize("signature_key", ["X-Hub-Signature-256", "x-hub-signature-256"])
def test_signature_header_lookup_is_case_insensitive(spies: Spies, signature_key: str) -> None:
    parsed, accepted = spies
    body = FIXTURE.read_bytes()
    event = make_event(body, header=sign(body), signature_key=signature_key)
    assert github_webhook.handler(event, None) == ACCEPTED
    assert parsed == [body] and len(accepted) == 1


def test_duplicate_signature_headers_count_as_no_signature(spies: Spies) -> None:
    parsed, accepted = spies
    body = FIXTURE.read_bytes()
    event = make_event(body, header=sign(body))
    event["headers"]["X-Hub-Signature-256"] = sign(body)  # 同名 header 出現兩次
    result = github_webhook.handler(event, None)
    assert result["ok"] is False
    assert result["fields"] == ["X-Hub-Signature-256"]
    assert parsed == [] and accepted == []


def test_valid_signature_but_broken_json_fails_after_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """驗簽通過後才輪到 parser；壞掉的 JSON 由真正的 `parse_json` 回 `IngressError`。"""
    accepted: list[dict[str, Any]] = []
    monkeypatch.setattr(github_webhook, "load_secret", lambda: SECRET)
    monkeypatch.setattr(github_webhook, "normalize_then_accept",
                        lambda **passed: accepted.append(passed))
    body = b'{"action": "opened"'  # 少一個右大括號
    result = github_webhook.handler(make_event(body, header=sign(body)), None)
    assert result["ok"] is False
    assert result["fields"] == ["body"]
    assert accepted == []


def test_event_type_without_adapter_is_rejected(spies: Spies) -> None:
    parsed, accepted = spies
    body = FIXTURE.read_bytes()
    event = make_event(body, header=sign(body), event_type="star")
    result = github_webhook.handler(event, None)
    assert result["ok"] is False
    assert result["fields"] == ["X-GitHub-Event"]
    assert accepted == []  # 接受路徑 0 次
    assert parsed == [body]  # 驗簽已過、JSON 已解析，卡在沒有對應 adapter


def test_pull_request_event_maps_to_the_github_pr_adapter(spies: Spies) -> None:
    _, accepted = spies
    body = (FIXTURE.parent / "pull-request-merged.json").read_bytes()
    event = make_event(body, header=sign(body), event_type="pull_request")
    assert github_webhook.handler(event, None)["ok"] is True
    assert accepted[0]["adapter"] == "github_pr" and accepted[0]["event_type"] == "pull_request"


def test_missing_secret_is_a_configuration_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """secret 未設定是環境設定錯誤，不得報成使用者輸入錯誤，也不得放行。"""
    monkeypatch.delenv(github_webhook.SECRET_ENV, raising=False)
    body = FIXTURE.read_bytes()
    with pytest.raises(PermanentError):
        github_webhook.handler(make_event(body, header=sign(body)), None)


def test_wiring_point_refuses_to_pretend_success(rote_deps: Any) -> None:
    """接線點已由 Phase 37 接上 Rote 三層；正規化不出合法物件時仍明確失敗。

    `fail_at="validate"` 讓每一次 `validate` 都不過，Agent 用完額度後整次接入回失敗——
    不得「先回成功、之後再背景處理」（設計 §14.1）。
    """
    deps = rote_deps(fail_at="validate")
    with pytest.raises(PermanentError):
        normalize_then_accept(domain="github.com", adapter="github_issue", event_type="issues",
                              headers={}, payload={"action": "opened"}, deadline=monotonic() + 8.0)
    assert deps.started == [] and deps.commit_calls == 0


def test_wiring_point_returns_one_acceptance_per_canonical_object(rote_deps: Any,
                                                                  raw_issue: Any) -> None:
    """D-73：`normalize_then_accept` 回 `list[Acceptance]`，單一 Ticket 就是長度 1。"""
    deps = rote_deps()
    event = raw_issue()
    accepted = normalize_then_accept(domain=event.domain, adapter=event.adapter,
                                     event_type=event.event_type, headers=event.headers,
                                     payload=event.payload, deadline=deps.deadline)
    assert [acceptance.operation_id for acceptance in accepted] == [
        "op-ticket-t_gh-acme-copilot-128"]


# --- Task 3：八秒整體期限 -----------------------------------------------------


def fake_clock(*ticks: float) -> Callable[[], float]:
    values = iter(ticks)
    return lambda: next(values)


def test_deadline_boundary_is_exclusive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("training_kb.ingress.monotonic", fake_clock(7.999))
    assert_time_left(8.0, step="accept")  # 7.999 秒還在期限內
    monkeypatch.setattr("training_kb.ingress.monotonic", fake_clock(8.0))
    with pytest.raises(TimeoutError):
        assert_time_left(8.0, step="accept")  # 8.000 秒到期


def test_timeout_never_returns_success(spies: Spies, monkeypatch: pytest.MonkeyPatch) -> None:
    parsed, accepted = spies
    monkeypatch.setattr(github_webhook, "monotonic", fake_clock(0.0))
    monkeypatch.setattr("training_kb.ingress.monotonic", fake_clock(8.5))

    def slow_accept(*, deadline: float, **passed: Any) -> None:
        assert_time_left(deadline, step="accept")
        raise AssertionError("超過期限後不應該繼續")

    monkeypatch.setattr(github_webhook, "normalize_then_accept", slow_accept)
    body = FIXTURE.read_bytes()
    result = github_webhook.handler(make_event(body, header=sign(body)), None)
    assert result["ok"] is False and result["operation_id"] is None
    assert "success" not in str(result)


def test_time_left_counts_down_from_the_same_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    """同一個 deadline 一路傳下去，剩餘時間隨時鐘遞減，不會被任何一步重置。"""
    monkeypatch.setattr("training_kb.ingress.monotonic", fake_clock(1.0, 5.0, 8.0))
    deadline = 8.0
    assert time_left(deadline) == pytest.approx(7.0)
    assert time_left(deadline) == pytest.approx(3.0)
    assert time_left(deadline) == pytest.approx(0.0)


def test_log_records_delivery_and_operation_but_never_body_or_signature(
    spies: Spies, caplog: pytest.LogCaptureFixture
) -> None:
    body = FIXTURE.read_bytes()
    signature = sign(body)
    with caplog.at_level("INFO", logger=github_webhook.__name__):
        github_webhook.handler(make_event(body, header=signature), None)
        github_webhook.handler(make_event(body, header="sha256=" + "0" * 64), None)
    text = caplog.text
    assert "d-001" in text and "op-ticket-t_881" in text  # delivery ID 與 operation ID
    assert "accepted" in text and "rejected" in text  # 結果類型
    assert signature not in text and signature.removeprefix("sha256=") not in text
    assert SECRET.decode("ascii") not in text
    assert "會前摘要在哪裡開啟？" not in text  # fixture 裡的使用者全文
