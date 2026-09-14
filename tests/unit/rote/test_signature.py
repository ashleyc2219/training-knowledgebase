"""Phase 33：`RawEvent` 與結構簽名的單元測試。

這裡只驗「簽名素材的邊界」：可信入口脈絡缺一不可、未核定的 `(domain, event_type)`
一律拒絕，以及簽名只看結構不看值。不連 AWS、不呼叫模型、不讀 fixture 檔。
"""

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
