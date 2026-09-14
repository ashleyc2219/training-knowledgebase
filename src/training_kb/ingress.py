"""接入層：驗簽、正規化、接受去重與流程啟動。

owner 是 Phase 30；P31（正規化）、P32（接受／啟動）、P37（Rote 三層）、P42、P43、P59
之後會在同一支檔案往下追加。目前的區塊順序固定為：

1. 驗簽（P30）—— 解析 JSON 之前先用原始 request bytes 比對 HMAC-SHA256。
2. 整體期限（P30）—— webhook 的八秒 deadline，下游每一步開始前呼叫 `assert_time_left`。
3. 接線點（P30 stub → P32 接受端 → P37 完整三層）。
4. 正規化（P31 之後追加於「接線點」之上）。

log 不得出現原始 body、簽名或 secret（00A §3.8）。
"""

import hashlib
import hmac
import string
from collections.abc import Mapping
from time import monotonic

from training_kb.errors import IngressError, PermanentError
from training_kb.operations import Acceptance
from training_kb.pipelines.common import JSONValue

# --- 1. 驗簽（Phase 30）-------------------------------------------------------

SIGNATURE_HEADER = "X-Hub-Signature-256"
SIGNATURE_PREFIX = "sha256="
HEX_DIGEST_LENGTH = 64


def verify_github_signature(raw_body: bytes, signature_header: str | None, secret: bytes) -> None:
    """用原始 bytes 驗 GitHub 簽名；合法回 None，不合法丟 `IngressError`。

    `raw_body` 一定要是 Lambda 收到的原始 bytes。重新 `json.dumps()` 會改掉空白與鍵順序，
    算出來的 HMAC 一定對不上。secret 沒設定屬於環境設定錯誤（`PermanentError`），
    不能報成使用者輸入錯誤。
    """
    if not secret:
        raise PermanentError("webhook secret 未設定")  # 設定錯誤，不是使用者輸入錯誤
    if not signature_header or not signature_header.startswith(SIGNATURE_PREFIX):
        raise IngressError("GitHub 簽名缺少或格式錯誤", (SIGNATURE_HEADER,))
    supplied = signature_header.removeprefix(SIGNATURE_PREFIX).lower()
    # 先擋掉長度與字元明顯不對的值，避免把任意長度字串丟進比較。
    if len(supplied) != HEX_DIGEST_LENGTH or any(c not in string.hexdigits for c in supplied):
        raise IngressError("GitHub 簽名格式錯誤", (SIGNATURE_HEADER,))
    expected = hmac.new(secret, raw_body, hashlib.sha256).hexdigest()
    # 一律固定時間比較，不可寫成 `expected == supplied`。訊息只說不符，不回報期望值。
    if not hmac.compare_digest(expected, supplied):
        raise IngressError("GitHub 簽名不符", (SIGNATURE_HEADER,))


# --- 2. 整體期限（Phase 30）---------------------------------------------------


def time_left(deadline: float) -> float:
    """還剩幾秒；小於等於 0 代表整體期限已到。

    `deadline` 一律是 `time.monotonic()` 的**絕對時刻**（單調時鐘，不受系統調時影響），
    由 handler 進入時算好 `monotonic() + WEBHOOK_DEADLINE_SECONDS` 一路往下傳。
    """
    return deadline - monotonic()


def assert_time_left(deadline: float, *, step: str) -> None:
    """下游每一步開始前呼叫；**不重新計一次八秒、也不自己呼叫 `monotonic()`**。

    逾時丟 Python 內建的 `TimeoutError`（不是 `TransientError`：這不是服務故障，
    而是來不及）。`step` 只用來讓訊息看得出卡在哪一步。
    """
    if time_left(deadline) <= 0:
        raise TimeoutError(f"{step} 時已超過 webhook 的八秒整體期限")


# --- 3. 接線點（Phase 30 stub → Phase 32 接受端 → Phase 37 完整三層）----------


def normalize_then_accept(*, domain: str, adapter: str, event_type: str,
                          headers: Mapping[str, str], payload: Mapping[str, JSONValue],
                          deadline: float) -> Acceptance:
    """Phase 31 正規化 + Phase 32 接受的接線點。

    本 Phase 只固定呼叫位置與六個 keyword 參數（00A D-60）：`domain`／`adapter` 由可信
    入口設定提供，**不得從 payload 反推**；`headers` 一律小寫鍵；`deadline` 是 handler
    進入時算好的絕對時刻，往下傳而不重新計時。

    這裡刻意丟 `PermanentError` 而不是回一個假的成功：設計 §14.1 要求驗簽以外的任何一步
    失敗都回操作失敗，不能「先回成功、之後再背景處理」。
    """
    raise PermanentError("Phase 31／32 尚未接線；本 Phase 不得先回成功再背景處理")
