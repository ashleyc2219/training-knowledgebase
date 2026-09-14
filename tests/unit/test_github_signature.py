"""Phase 30 Task 1：以原始 request bytes 驗 GitHub 的 X-Hub-Signature-256。"""

import hashlib
import hmac
from pathlib import Path

import pytest

from training_kb.errors import IngressError, PermanentError
from training_kb.ingress import verify_github_signature

SECRET = b"test-secret"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "github"


def sign(body: bytes, secret: bytes = SECRET) -> str:
    return "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()


def test_rejects_changed_raw_bytes() -> None:
    body = b'{"action":"opened"}'
    header = sign(body)
    assert verify_github_signature(body, header, SECRET) is None  # 合法時回 None
    with pytest.raises(IngressError) as error:
        verify_github_signature(body + b" ", header, SECRET)  # 只多一個空白
    assert error.value.fields == ("X-Hub-Signature-256",)


def test_missing_secret_is_a_configuration_error() -> None:
    with pytest.raises(PermanentError):
        verify_github_signature(b"{}", sign(b"{}"), b"")


@pytest.mark.parametrize(
    ("header", "reason"),
    [
        (None, "缺 header"),
        ("", "空字串"),
        ("sha1=" + "a" * 40, "prefix 寫成 sha1="),
        ("sha256=" + "z" * 64, "非 hex 字元"),
        ("sha256=" + "a" * 63, "長度 63"),
        ("sha256=" + "a" * 65, "長度 65"),
    ],
)
def test_malformed_signature_headers_report_the_signature_field(
    header: str | None, reason: str
) -> None:
    with pytest.raises(IngressError) as error:
        verify_github_signature(b'{"action":"opened"}', header, SECRET)
    assert error.value.fields == ("X-Hub-Signature-256",), reason


def test_uppercase_hex_signature_is_accepted() -> None:
    """大寫十六進位的合法簽名應通過；prefix 仍是 GitHub 實際送的小寫 `sha256=`。"""
    body = b'{"action":"opened"}'
    upper_hex = "sha256=" + sign(body).removeprefix("sha256=").upper()
    assert verify_github_signature(body, upper_hex, SECRET) is None


def test_same_body_and_secret_produce_the_same_digest_twice() -> None:
    body = b'{"action":"opened"}'
    assert sign(body) == sign(body)
    assert verify_github_signature(body, sign(body), SECRET) is None
    assert verify_github_signature(body, sign(body), SECRET) is None


def test_wrong_secret_is_rejected() -> None:
    body = b'{"action":"opened"}'
    with pytest.raises(IngressError) as error:
        verify_github_signature(body, sign(body, b"another-secret"), SECRET)
    assert error.value.fields == ("X-Hub-Signature-256",)


@pytest.mark.parametrize("name", ["issue-opened.json", "pull-request-merged.json"])
def test_phase13_fixtures_must_pass_hmac_before_anything_else(name: str) -> None:
    """Rule 1：合法 fixture 的原始 bytes 必須先通過 HMAC 驗簽（簽名用測試自己的假 secret 現算）。"""
    body = (FIXTURES / name).read_bytes()
    assert verify_github_signature(body, sign(body), SECRET) is None
    with pytest.raises(IngressError) as error:
        verify_github_signature(body + b"\n", sign(body), SECRET)  # 只多一個換行
    assert error.value.fields == ("X-Hub-Signature-256",)
