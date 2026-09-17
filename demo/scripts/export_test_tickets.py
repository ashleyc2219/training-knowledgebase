"""從 `demo/seed/tickets.json` 依 source 拆到 `demo/test-tickets/`。

種子檔本身不動。github_issue 種子沒有，寫一筆合成範例供 parser 測試。
"""

from pathlib import Path

from demo.seed_loader import load_seed
from demo.ticket_files import DEFAULT_TICKETS_DIR, dump_source
from training_kb.clock import parse_iso
from training_kb.models import Ticket, TicketSource

GITHUB_SAMPLE = Ticket(
    id="t_gh_001", source=TicketSource.GITHUB_ISSUE,
    text="會前摘要按鈕在 Issue 裡找不到", author="u_gh_01",
    ts=parse_iso("2026-09-17T10:00:00Z"), project_id="demo", cluster_id=None,
    feature_ids=[], embedding=None)


def main() -> int:
    bundle = load_seed(Path("demo/seed"))
    root = Path(DEFAULT_TICKETS_DIR)
    by_source: dict[str, list[Ticket]] = {str(TicketSource.EMAIL): [],
                                          str(TicketSource.DISCORD): []}
    for ticket in bundle.tickets:
        by_source.setdefault(str(ticket.source), []).append(ticket)
    dump_source(root, str(TicketSource.EMAIL), by_source[str(TicketSource.EMAIL)])
    dump_source(root, str(TicketSource.DISCORD), by_source[str(TicketSource.DISCORD)])
    dump_source(root, str(TicketSource.GITHUB_ISSUE), (GITHUB_SAMPLE,))
    print(f"已寫入 {root}：email={len(by_source[str(TicketSource.EMAIL)])} "
          f"discord={len(by_source[str(TicketSource.DISCORD)])} github_issue=1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
