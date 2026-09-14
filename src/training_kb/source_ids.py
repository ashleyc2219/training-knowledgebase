"""Phase 13：來源 ID 的確定性編碼、穩定使用者編碼與 O6 核定紀錄讀取。

這支檔只做「來源事實 → canonical 字串」的純函式轉換：不連 GitHub、不呼叫模型、
不讀寫 AWS，也不建立 User 實體或身分對照表。顯示名稱（login、暱稱、寄件人姓名）
一律不得用來推測是不是同一人。
"""

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from training_kb.errors import IngressError

SLUG_PATTERN = re.compile(r"^[a-z0-9._-]+$")
USER_PATTERN = re.compile(r"^[a-z0-9_-]{2,64}$")


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


def github_user_id(numeric_id: int) -> str:
    """GitHub 的穩定使用者：只用數字 id，改名（login）不改人。"""
    if isinstance(numeric_id, bool) or not isinstance(numeric_id, int) or numeric_id <= 0:
        raise IngressError("GitHub 使用者識別必須是正整數", ("user",))
    return f"u_gh-{numeric_id}"


def stable_user_from_import(value: str) -> str:
    """手動匯入檔的使用者 ID：只做格式檢查，缺值直接拒絕，不補值也不從顯示名稱猜。"""
    candidate = value.strip() if isinstance(value, str) else ""
    if not USER_PATTERN.fullmatch(candidate):
        raise IngressError("匯入檔必須提供合法的穩定使用者 ID", ("user",))
    return candidate


APPROVAL_FIELDS: tuple[str, ...] = (
    "domain",
    "event_type",
    "adapter",
    "stable_keys",
    "fixture",
    "id_encoder",
    "stable_user_source",
    "approved_by",
    "approved_at",
)
_OPTIONAL_FIELDS = frozenset({"approved_by", "approved_at"})


@dataclass(frozen=True)
class SourceApproval:
    """維護者簽收過的「來源 → 清單與編碼」一列；九個欄位就是 mapping 表的九欄。"""

    domain: str
    event_type: str
    adapter: str
    stable_keys: tuple[str, ...]
    fixture: str            # 相對於 tests/fixtures/ 的路徑
    id_encoder: str         # 事件 ID 編碼函式名或「檔案提供」
    stable_user_source: str  # 穩定 user 來自哪個欄位
    approved_by: str
    approved_at: str

    @property
    def approved(self) -> bool:
        """核定者與核定日期都填了才算核定；其餘一律 blocked。"""
        return bool(self.approved_by.strip() and self.approved_at.strip())


def _text_field(row: Mapping[str, object], name: str) -> str:
    value = row[name]
    if not isinstance(value, str):
        raise IngressError(f"{name} 必須是字串", (name,))
    if name not in _OPTIONAL_FIELDS and not value.strip():
        raise IngressError(f"{name} 不得留空", (name,))
    return value


def _approval_from(row: object) -> SourceApproval:
    if not isinstance(row, Mapping):
        raise IngressError("核定紀錄的每一列都必須是物件", ("approvals",))
    missing = tuple(name for name in APPROVAL_FIELDS if name not in row)
    if missing:
        raise IngressError("核定紀錄缺少欄位", missing)
    raw_keys = row["stable_keys"]
    if not isinstance(raw_keys, list):
        raise IngressError("stable_keys 必須是字串清單", ("stable_keys",))
    stable_keys = tuple(item for item in raw_keys if isinstance(item, str) and item.strip())
    if len(stable_keys) != len(raw_keys) or not stable_keys:
        raise IngressError("stable_keys 必須是非空的字串清單", ("stable_keys",))
    return SourceApproval(
        domain=_text_field(row, "domain"),
        event_type=_text_field(row, "event_type"),
        adapter=_text_field(row, "adapter"),
        stable_keys=stable_keys,
        fixture=_text_field(row, "fixture"),
        id_encoder=_text_field(row, "id_encoder"),
        stable_user_source=_text_field(row, "stable_user_source"),
        approved_by=_text_field(row, "approved_by"),
        approved_at=_text_field(row, "approved_at"),
    )


def load_source_approvals(path: str | Path) -> tuple[SourceApproval, ...]:
    """讀 O6 核定紀錄；缺欄位或型別不對一律拒絕，不補預設值。"""
    rows = json.loads(Path(path).read_text("utf-8"))
    if not isinstance(rows, list):
        raise IngressError("核定紀錄必須是一個陣列", ("approvals",))
    return tuple(_approval_from(row) for row in rows)


def approved_stable_keys(
    rows: Sequence[SourceApproval],
) -> dict[tuple[str, str], frozenset[str]]:
    """只回已核定的 `(domain, event_type)`；未核定的來源不會出現在結果裡。"""
    approved: dict[tuple[str, str], frozenset[str]] = {}
    for row in rows:
        if not row.approved:
            continue
        approved[(row.domain, row.event_type)] = frozenset(row.stable_keys)
    return approved


MAPPING_COLUMNS: tuple[str, ...] = (
    "domain",
    "event_type",
    "adapter",
    "STABLE_KEYS",
    "fixture",
    "事件 ID 編碼",
    "穩定 user 來源",
    "核定者",
    "核定日期",
)
PENDING = "待維護者核定"


def _mapping_cells(row: SourceApproval) -> tuple[str, ...]:
    keys = ", ".join(row.stable_keys)
    return (
        f"`{row.domain}`",
        f"`{row.event_type}`",
        f"`{row.adapter}`",
        keys if row.approved else f"候選：{keys}",
        f"`{row.fixture}`",
        row.id_encoder,
        row.stable_user_source,
        row.approved_by or PENDING,
        row.approved_at or PENDING,
    )


def render_mapping_table(rows: Sequence[SourceApproval]) -> str:
    """把核定紀錄渲染成 mapping 表的九欄；未核定的列標「候選：」與「待維護者核定」。"""
    lines = [
        "| " + " | ".join(MAPPING_COLUMNS) + " |",
        "|" + "---|" * len(MAPPING_COLUMNS),
    ]
    lines.extend("| " + " | ".join(_mapping_cells(row)) + " |" for row in rows)
    return "\n".join(lines)
