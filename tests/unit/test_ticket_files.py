"""測試工單目錄：三種格式讀成同一個 Ticket，來源資料夾與 source 必須一致。"""

from pathlib import Path
from typing import Any

import pytest

from demo.ticket_files import (
    COLUMNS,
    DEFAULT_TICKETS_DIR,
    GITHUB_ISSUE_HINT,
    dump_csv,
    dump_json,
    dump_xlsx,
    find_ticket,
    load_all,
    load_file,
    load_slot,
    load_xlsx,
    ticket_row,
)
from training_kb.clock import parse_iso
from training_kb.errors import ContentError
from training_kb.models import Ticket, TicketSource

ROOT = Path(DEFAULT_TICKETS_DIR)


def _sample() -> Ticket:
    return Ticket(
        id="t_9001", source=TicketSource.EMAIL, text="測試工單正文",
        author="u_90", ts=parse_iso("2026-09-17T10:00:00Z"), project_id="demo",
        cluster_id=None, feature_ids=[], embedding=None)


def test_seeded_email_json_loads_t_3001() -> None:
    """Given 從種子拆出的 email json When 找 t_3001 Then 來源是 email。"""
    found = find_ticket(ROOT, "t_3001")
    assert found is not None
    assert found.source is TicketSource.EMAIL
    assert found.text


def test_three_formats_round_trip(tmp_path: Path) -> None:
    """Given 同一張工單寫成 json／csv／xlsx When 讀回 Then 三份內容相同。"""
    ticket = _sample()
    dump_json(tmp_path / "email" / "json" / "tickets.json", (ticket,))
    dump_csv(tmp_path / "email" / "csv" / "tickets.csv", (ticket,))
    dump_xlsx(tmp_path / "email" / "xlsx" / "tickets.xlsx", (ticket,))
    loaded = [load_slot(tmp_path, "email", fmt) for fmt in ("json", "csv", "xlsx")]
    assert [ticket_row(row[0]) for row in loaded] == [ticket_row(ticket)] * 3


def test_source_folder_mismatch_is_rejected(tmp_path: Path) -> None:
    """Given email 工單放在 discord/json When 讀檔 Then ContentError。"""
    dump_json(tmp_path / "discord" / "json" / "tickets.json", (_sample(),))
    with pytest.raises(ContentError, match="不一致"):
        load_file(tmp_path / "discord" / "json" / "tickets.json")


def test_load_all_rejects_conflicting_duplicates(tmp_path: Path) -> None:
    """Given 同一 id 兩份不同正文 When load_all Then ContentError。"""
    first = _sample()
    second = first.model_copy(update={"text": "另一段正文"})
    dump_json(tmp_path / "email" / "json" / "tickets.json", (first,))
    dump_csv(tmp_path / "email" / "csv" / "tickets.csv", (second,))
    with pytest.raises(ContentError, match="不一致"):
        load_all(tmp_path)


def test_xlsx_missing_openpyxl(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Given 沒有 openpyxl When 讀 xlsx Then 說明這是本機 dev 依賴。"""

    def boom() -> Any:
        raise ContentError("讀寫 xlsx 需要 openpyxl；請在本機安裝 dev 依賴（不會進 Lambda）")

    monkeypatch.setattr("demo.ticket_files._openpyxl", boom)
    path = tmp_path / "tickets.xlsx"
    path.write_bytes(b"not-a-real-workbook")
    with pytest.raises(ContentError, match="openpyxl"):
        load_xlsx(path)


def test_github_hint_mentions_webhook() -> None:
    assert "webhook" in GITHUB_ISSUE_HINT
    assert find_ticket(ROOT, "t_gh_001") is not None


def test_columns_cover_ticket_fields() -> None:
    assert COLUMNS[0] == "id" and "source" in COLUMNS and "text" in COLUMNS
