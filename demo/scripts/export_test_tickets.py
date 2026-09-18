"""從 `demo/seed/tickets.json` 依主題類別再依 source 拆到 `demo/test-tickets/`。

種子檔本身不動。github_issue 種子沒有，寫一筆合成範例供 parser 測試。
沒有工單的主題仍寫出空的來源 × 格式格子，方便接著加票。
"""

from collections import defaultdict
from pathlib import Path

from demo.seed_loader import load_seed
from demo.ticket_files import DEFAULT_TICKETS_DIR, SEED_CATEGORIES, SOURCES, dump_source
from training_kb.clock import parse_iso
from training_kb.models import Ticket, TicketSource

GITHUB_SAMPLE = Ticket(
    id="t_gh_001", source=TicketSource.GITHUB_ISSUE,
    text="會前摘要按鈕在 Issue 裡找不到", author="u_gh_01",
    ts=parse_iso("2026-09-17T10:00:00Z"), project_id="demo", cluster_id=None,
    feature_ids=[], embedding=None)


def category_for(ticket: Ticket) -> str:
    """種子工單目前只有兩類主題；對不到的歸入準備會議。"""
    if ticket.cluster_id == "c58" or ticket.id.startswith("t_30"):
        return "weekly-digest"
    return "prepare-meeting"


def main() -> int:
    bundle = load_seed(Path("demo/seed"))
    root = Path(DEFAULT_TICKETS_DIR)
    grouped: dict[tuple[str, str], list[Ticket]] = defaultdict(list)
    for ticket in bundle.tickets:
        grouped[(category_for(ticket), str(ticket.source))].append(ticket)
    github_key = ("prepare-meeting", str(TicketSource.GITHUB_ISSUE))
    grouped[github_key].append(GITHUB_SAMPLE)
    for category in SEED_CATEGORIES:
        for source in SOURCES:
            rows = grouped.get((category, source), [])
            dump_source(root, source, rows, category=category)
    counts = ", ".join(
        f"{name}={sum(len(grouped[(name, source)]) for source in SOURCES)}"
        for name in SEED_CATEGORIES)
    print(f"已寫入 {root}：{counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
