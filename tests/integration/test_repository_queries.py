"""Phase 08：三個公開查詢、GSI 候選回基表核對與六個固定讀取（moto 本機表）。

moto 的 PASS 只證明資料形狀與分頁邏輯，**不**證明真實 DynamoDB 的分頁與 GSI 最終一致行為；
跨併發寫入的完整性與 O2、O3 一起驗收（設計 §10）。
`paged_repository` 的 `page_size=1` 是測試鉤子：Limit 在過濾之前套用，所以帶
`FilterExpression` 的 Scan 會出現「這一頁零筆但游標還在」，提前停止就會漏資料。
"""

from datetime import UTC, datetime

from training_kb.keys import feedback_pk, step_pk, ticket_pk, version_pk
from training_kb.models import Feedback, Ticket

VERSION = "prepare-meeting@v1"


def feedback(feedback_id: str, version_id: str = VERSION) -> Feedback:
    return Feedback(id=feedback_id, tutorial_version=version_id, rating=2,
                    category="找不到按鈕", comment=None, user="u_01",
                    ts=datetime(2026, 8, 2, tzinfo=UTC))


def ticket(ticket_id: str, project_id: str = "demo") -> Ticket:
    return Ticket(id=ticket_id, source="email", text="找不到按鈕", author="u_01",
                  ts=datetime(2026, 8, 3, 10, tzinfo=UTC), project_id=project_id)


def test_scan_entity_reads_every_page_even_when_pages_come_back_empty(
        repository, paged_repository) -> None:
    """五筆 TICKET 與五筆 FEEDBACK 交錯，`page_size=1` 讓一半的頁被 filter 濾成空。"""
    for number in range(1, 6):
        repository.put_meta(ticket(f"t_{number}"))
        repository.put_meta(feedback(f"f_{number}"))
    tickets = paged_repository.scan_entity("TICKET")
    assert [str(item["PK"]) for item in tickets] == [f"TICKET#t_{n}" for n in range(1, 6)]
    assert tickets == repository.scan_entity("TICKET")


def test_query_pk_returns_every_edge_of_the_same_start_point(repository, paged_repository) -> None:
    """GPH Rule 1：查某起點的關係就用該起點的 PK，而且要讀齊所有分頁。"""
    pk = feedback_pk("f_12")
    repository.put_meta(feedback("f_12"))
    for number in range(1, 4):
        repository.put_edge(pk, "REFERS_TO", version_pk(f"prepare-meeting@v{number}"))
    rows = paged_repository.query_pk(pk)
    assert [str(item["SK"]) for item in rows] == [
        "META",
        "REFERS_TO#VERSION#prepare-meeting@v1",
        "REFERS_TO#VERSION#prepare-meeting@v2",
        "REFERS_TO#VERSION#prepare-meeting@v3",
    ]
    assert [str(item["SK"]) for item in paged_repository.query_pk(pk, sk_prefix="REFERS_TO#")] == [
        f"REFERS_TO#VERSION#prepare-meeting@v{number}" for number in range(1, 4)
    ]
    assert paged_repository.query_pk(ticket_pk("t_missing")) == []


def test_step_edges_are_scanned_with_meta_only_off(repository, paged_repository) -> None:
    """STEP 沒有 `META` item，所以預設的 `meta_only=True` 會把它整個濾掉。"""
    pk = step_pk("prepare-meeting@v2", 1)
    repository.put_edge(pk, "REFERENCES", "FEATURE#Prepare", {"type": "read", "text": "step 1"})
    assert paged_repository.scan_entity("STEP") == []
    assert [str(item["PK"]) for item in paged_repository.scan_entity("STEP", meta_only=False)] == [
        pk
    ]
