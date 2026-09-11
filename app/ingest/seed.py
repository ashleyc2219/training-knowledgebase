"""種子匯入：`data/seed/bitext_seed.json` → 9 表 ＋ Cognee ＋ HydraDB。

契約見 `docs/spec/features/建構知識圖譜.feature`（5 條 Rule）：
匯入後 Ticket `status = resolved` 且 `resolution_steps` / `created_at` 有值；
`UserProblem.topic` 等於 `intent` 且同 topic 重用同一列；
`Feature.name` 等於 `feature_name` 且同名重用同一列；不同 intent 各建一列。

寫入順序固定：先寫資料層（hotdata / SQLite），成功後才寫圖譜層。
圖譜層失敗只印警告不擋 demo（`docs/design/showme.md` §17 的降級表）。

執行：`uv run python -m app.ingest.seed`
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from app.errors import OperationFailed
from app.ingest.bitext import SEED_PATH

REQUIRED_FIELDS = ("content", "category", "intent", "customer_ref", "feature_name", "created_at")


def load_seed(path: Path | str = SEED_PATH) -> list[dict]:
    """讀種子 JSON；缺欄位就 `操作失敗`。"""
    p = Path(path)
    if not p.exists():
        raise OperationFailed(f"找不到種子檔 {p}；請先跑 `uv run python -m app.ingest.bitext`")
    rows = json.loads(p.read_text(encoding="utf-8"))
    for row in rows:
        missing = [f for f in REQUIRED_FIELDS if not row.get(f)]
        if missing or not _steps(row):
            raise OperationFailed(f"種子列缺欄位：{missing or ['response']}")
    return rows


def _steps(row: dict) -> str:
    """解法步驟：規格欄名是 `response`，Phase 0 產出的 JSON 用 `resolution_steps`。"""
    return row.get("response") or row.get("resolution_steps") or ""


def _write_rows(db: Any, table: str, rows: list[dict], key: list[str]) -> None:
    """統一寫入：hotdata 走 `load_rows`（upsert），SQLite 走 `INSERT`。"""
    if not rows:
        return
    if hasattr(db, "load_rows"):
        db.load_rows(table, rows, key=key)
        return
    cols = list(rows[0].keys())
    sql = (
        f"INSERT INTO {table} ({', '.join(cols)}) "
        f"VALUES ({', '.join(':' + c for c in cols)})"
    )
    for row in rows:
        db.execute(sql, row)


def _next_id(db: Any, table: str, id_col: str = "id") -> int:
    rows = db.run_sql(f"SELECT MAX({id_col}) AS m FROM {table}")
    current = rows[0]["m"] if rows and rows[0].get("m") is not None else 0
    return int(current) + 1


def seed(
    db: Any,
    cognee: Any = None,
    hydra: Any = None,
    rows: Optional[list[dict]] = None,
) -> dict:
    """匯入種子票單。回傳各表列數與圖譜層狀態。重跑冪等（同 content + created_at 不重複）。"""
    rows = rows if rows is not None else load_seed()
    rows = sorted(rows, key=lambda r: r["created_at"])

    features = {r["name"]: r["id"] for r in db.run_sql("SELECT id, name FROM Feature")}
    problems = {r["topic"]: r["id"] for r in db.run_sql("SELECT id, topic FROM UserProblem")}
    seen_tickets = {
        (r["content"], r["created_at"])
        for r in db.run_sql("SELECT content, created_at FROM Ticket")
    }

    next_feature = _next_id(db, "Feature")
    next_problem = _next_id(db, "UserProblem")
    next_ticket = _next_id(db, "Ticket")

    new_features: list[dict] = []
    new_problems: list[dict] = []
    new_tickets: list[dict] = []
    graph_items: list[tuple[dict, dict]] = []  # (ticket, 原始匯入列)

    for row in rows:
        name = row["feature_name"]
        if name not in features:
            features[name] = next_feature
            new_features.append({"id": next_feature, "name": name, "status": "active"})
            next_feature += 1
        feature_id = features[name]

        topic = row["intent"]
        if topic not in problems:
            problems[topic] = next_problem
            new_problems.append({"id": next_problem, "topic": topic, "feature_id": feature_id})
            next_problem += 1
        user_problem_id = problems[topic]

        identity = (row["content"], row["created_at"])
        if identity in seen_tickets:
            continue
        seen_tickets.add(identity)

        ticket = {
            "id": next_ticket,
            "content": row["content"],
            "resolution_steps": _steps(row),
            "category": row["category"],
            "customer_ref": row["customer_ref"],
            "feature_id": feature_id,
            "user_problem_id": user_problem_id,
            "status": "resolved",
            "deflected_tutorial_id": None,
            "deflected_tutorial_version": None,
            "reopened_from_ticket_id": None,
            "created_at": row["created_at"],
        }
        next_ticket += 1
        new_tickets.append(ticket)
        graph_items.append((ticket, row))

    # 1) 資料層先寫；失敗直接往上拋（不寫半套）
    _write_rows(db, "Feature", new_features, key=["id"])
    _write_rows(db, "UserProblem", new_problems, key=["id"])
    _write_rows(db, "Ticket", new_tickets, key=["id"])

    # 2) 圖譜層：失敗只降級
    cognee_ok = _remember_all(cognee, graph_items)
    hydra_ok = _push_graph(hydra, graph_items)

    return {
        "tickets": len(db.run_sql("SELECT id FROM Ticket")),
        "user_problems": len(db.run_sql("SELECT id FROM UserProblem")),
        "features": len(db.run_sql("SELECT id FROM Feature")),
        "inserted_tickets": len(new_tickets),
        "cognee_ok": cognee_ok,
        "hydra_ok": hydra_ok,
    }


def _remember_all(cognee: Any, items: list[tuple[dict, dict]]) -> bool:
    """每張票 remember 一次（`docs/design/showme.md` §5.5）。"""
    if cognee is None:
        return False
    try:
        for ticket, row in items:
            text = f"{row['content']}\n\n{_steps(row)}\n\nintent: {row['intent']}"
            cognee.remember(
                text,
                kind="ticket",
                meta={
                    "ticket_id": ticket["id"],
                    "intent": row["intent"],
                    "feature": row["feature_name"],
                    "customer_ref": row["customer_ref"],
                },
            )
        return True
    except Exception as exc:  # 降級，不擋資料層
        print(f"WARN: cognee degraded（{type(exc).__name__}: {exc}）；可事後補跑 seed")
        return False


def _push_graph(hydra: Any, items: list[tuple[dict, dict]]) -> bool:
    """Ticket / UserProblem / Feature 節點 ＋ `asks_about` 邊（本 phase 只寫這一種邊）。"""
    if hydra is None:
        return False
    try:
        for ticket, row in items:
            hydra.upsert_node(
                "Ticket",
                {"id": ticket["id"]},
                {
                    "status": ticket["status"],
                    "customer_ref": ticket["customer_ref"],
                    "created_at": ticket["created_at"],
                },
            )
            hydra.upsert_node(
                "UserProblem",
                {"topic": row["intent"]},
                {"id": ticket["user_problem_id"], "feature_id": ticket["feature_id"]},
            )
            hydra.upsert_node(
                "Feature",
                {"name": row["feature_name"]},
                {"id": ticket["feature_id"], "status": "active"},
            )
            hydra.upsert_edge(
                "Ticket",
                {"id": ticket["id"]},
                "asks_about",
                "Feature",
                {"name": row["feature_name"]},
            )
        return True
    except Exception as exc:  # 降級，不擋資料層
        print(f"WARN: hydradb degraded（{type(exc).__name__}: {exc}）；可事後補跑 seed")
        return False


def main() -> dict:
    """`uv run python -m app.ingest.seed`：圖譜層連不上就印警告繼續。"""
    from app.analytics.db import get_db

    db = get_db()
    cognee = hydra = None
    try:
        from app.memory.cognee_client import CogneeClient

        cognee = CogneeClient()
    except Exception as exc:
        print(f"WARN: cognee client 建立失敗（{exc}）")
    try:
        from app.memory.hydradb_client import HydraDBClient

        hydra = HydraDBClient()
    except Exception as exc:
        print(f"WARN: hydradb client 建立失敗（{exc}）")

    summary = seed(db, cognee=cognee, hydra=hydra)
    print(
        f"seed: {summary['tickets']} tickets, {summary['user_problems']} user problems, "
        f"{summary['features']} features（本次新增 {summary['inserted_tickets']} 張票）"
    )
    print(f"  db:      {type(db).__name__}")
    print(f"  cognee:  {'ok' if summary['cognee_ok'] else 'degraded'}")
    print(f"  hydradb: {'ok' if summary['hydra_ok'] else 'degraded'}")
    return summary


if __name__ == "__main__":
    main()
