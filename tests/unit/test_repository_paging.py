"""Phase 08：分頁迴圈的結束條件與三個公開查詢送出的參數。

用腳本化的假 table 鎖住兩件 moto 很難穩定重現的事：一頁被 `FilterExpression` 濾成空卻仍帶
游標時**不得**提前停止，以及 GSI 查詢**不能**帶 `ConsistentRead`（DynamoDB 的 GSI 只有最終
一致）。`page_size` 是測試鉤子：有值時每個請求加 `Limit`，正式程式不設定它。
"""

from training_kb.repository import Repository


class ScriptedTable:
    """依序回放排好的回應；`scan` 與 `query` 共用同一個入口，每次呼叫的參數都記下來。"""

    def __init__(self, pages: list[dict[str, object]]) -> None:
        self.pages = pages
        self.requests: list[dict[str, object]] = []

    def _record(self, **kwargs: object) -> dict[str, object]:
        self.requests.append(kwargs)
        return self.pages[len(self.requests) - 1]

    scan = query = _record


def test_empty_page_with_cursor_does_not_stop_the_scan() -> None:
    ticket = {"PK": "TICKET#t_2", "SK": "META", "entity": "TICKET"}
    cursor = {"PK": "FEEDBACK#f_12", "SK": "META"}
    table = ScriptedTable([
        {"Items": [], "LastEvaluatedKey": cursor},
        {"Items": [ticket], "LastEvaluatedKey": {"PK": "TICKET#t_2", "SK": "META"}},
        {"Items": []},
    ])
    assert Repository(table).scan_entity("TICKET") == [ticket]
    assert len(table.requests) == 3
    assert table.requests[1]["ExclusiveStartKey"] == cursor
    assert table.requests[0]["ConsistentRead"] is True


def test_gsi_query_never_asks_for_consistent_read() -> None:
    table = ScriptedTable([{"Items": []}])
    assert Repository(table).query_by_target("FEATURE#Prepare") == []
    assert table.requests[0]["IndexName"] == "by_target"
    assert "ConsistentRead" not in table.requests[0]


def test_meta_only_filters_after_every_page_is_read() -> None:
    """`meta_only` 的過濾在讀完所有分頁之後才做，所以第一頁全是邊也不會早停。"""
    edge = {"PK": "RULE#R-007", "SK": "APPLIED_TO#VERSION#prepare-meeting@v2", "entity": "RULE"}
    meta = {"PK": "RULE#R-007", "SK": "META", "entity": "RULE"}
    pages: list[dict[str, object]] = [
        {"Items": [edge], "LastEvaluatedKey": {"PK": "RULE#R-007", "SK": edge["SK"]}},
        {"Items": [meta]},
    ]
    assert Repository(ScriptedTable(list(pages))).scan_entity("RULE") == [meta]
    table = ScriptedTable(list(pages))
    assert Repository(table).scan_entity("RULE", meta_only=False) == [edge, meta]
    assert "FilterExpression" in table.requests[0]


def test_page_size_adds_limit_to_every_request_and_is_off_by_default() -> None:
    """`page_size` 只是測試鉤子；不給值時請求裡不得出現 `Limit`。"""
    pages: list[dict[str, object]] = [
        {"Items": [], "LastEvaluatedKey": {"PK": "VERSION#prepare-meeting@v1"}},
        {"Items": []},
    ]
    table = ScriptedTable(list(pages))
    assert Repository(table, page_size=2).query_pk("VERSION#prepare-meeting@v1") == []
    assert [request["Limit"] for request in table.requests] == [2, 2]
    default = ScriptedTable(list(pages))
    assert Repository(default).query_pk("VERSION#prepare-meeting@v1", consistent=False) == []
    assert "Limit" not in default.requests[0]
    assert default.requests[0]["ConsistentRead"] is False
