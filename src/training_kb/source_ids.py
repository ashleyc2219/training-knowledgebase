"""Phase 13：來源 ID 的確定性編碼、穩定使用者編碼與 O6 核定紀錄讀取。

這支檔只做「來源事實 → canonical 字串」的純函式轉換：不連 GitHub、不呼叫模型、
不讀寫 AWS，也不建立 User 實體或身分對照表。顯示名稱（login、暱稱、寄件人姓名）
一律不得用來推測是不是同一人。
"""

import re
from collections.abc import Sequence

from training_kb.errors import IngressError

SLUG_PATTERN = re.compile(r"^[a-z0-9._-]+$")


def _part(value: str, field: str) -> str:
    """把 owner／repo 轉成小寫 slug；含其他字元一律拒絕而不是取代。"""
    lowered = value.strip().lower() if isinstance(value, str) else ""
    if not SLUG_PATTERN.fullmatch(lowered):
        raise IngressError(f"{field} 含不允許的字元", (field,))
    return lowered


def _positive(value: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise IngressError(f"{field} 必須是大於 0 的整數", (field,))
    return value


def _repo_part(owner: str, repo: str) -> str:
    return f"{_part(owner, 'owner')}-{_part(repo, 'repo')}"


def github_ticket_id(owner: str, repo: str, number: int) -> str:
    return f"t_gh-{_repo_part(owner, repo)}-{_positive(number, 'number')}"


def github_release_id(owner: str, repo: str, pr_number: int, k: int) -> str:
    pr, index = _positive(pr_number, "pr_number"), _positive(k, "k")
    return f"r_gh-{_repo_part(owner, repo)}-pr{pr}-{index}"


def github_source_event_id(owner: str, repo: str, pr_number: int) -> str:
    return f"gh-{_repo_part(owner, repo)}-pr{_positive(pr_number, 'pr_number')}"


def sub_release_ids(
    owner: str, repo: str, pr_number: int, features: Sequence[str]
) -> tuple[tuple[str, str], ...]:
    """同一個 PR 的多個子變更依 Feature 名稱升序配 `k`（從 1 起算）。

    回 `(feature, release_id)` 序對；同一份 PR 重送（子變更順序不同也一樣）會得到
    完全相同的一組 `r_` ID。空清單與重複 Feature 名稱一律拒絕，不自行補號。
    """
    names = tuple(
        name.strip() for name in features if isinstance(name, str) and name.strip()
    )
    if not names or len(names) != len(features) or len(set(names)) != len(names):
        raise IngressError("PR 子變更必須各有一個不重複的 Feature 名稱", ("feature",))
    return tuple(
        (name, github_release_id(owner, repo, pr_number, index))
        for index, name in enumerate(sorted(names), start=1)
    )
