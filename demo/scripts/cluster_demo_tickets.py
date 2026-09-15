"""用**真實** Titan embedding 對二十筆 Demo 工單分群（Phase 56 Task 3）。

    uv run python -m demo.scripts.cluster_demo_tickets [種子目錄]

流程完全走既有函式，本檔沒有第二份分群邏輯：

    每筆 text -> Writer.embed -> amazon.titan-embed-text-v2:0
      request {"inputText": ..., "dimensions": 1024, "normalize": true}
    -> Ticket.embedding（1024 維）-> Phase 38 的 assign_cluster
      （cosine >= 0.85 取最高、同分 cluster_id 升序、無命中開新群）

**本檔沒有「模型不可用就預填 cluster_id」的分支。** Bedrock 回錯時
`Writer.embed` 丟的 `PermanentError`／`TransientError` 會被接住、把**錯誤原文逐字**
寫進 `clustering_report.json` 的 `reason`，`status` 記 `BLOCKED`、`observed` 是 `null`，
而且**不產生** `tickets_clustered.json`——沒有觀察值就不該有一份看起來跑過的檔案。

二十筆的分群結果是**觀察值**：可能不是單一群。報告照實列出實際群數與每群成員，
不為了畫面好看回頭改工單文字（Phase 文件 §6.7、§9）。

2026-09-14 的實際執行結果是 **BLOCKED**（O5：Titan 回
`ValidationException: Operation not allowed`），證據在 `demo/seed/clustering_report.json`
與 Phase 56 報告。
"""

import json
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import boto3

from demo.seed_loader import (
    CREATION_TICKET_PREFIX,
    SYNTHETIC_NOTICE,
    cluster_demo_tickets,
    creation_tickets,
    load_seed,
)
from training_kb.clock import now_utc, to_iso
from training_kb.config import load_settings
from training_kb.errors import PermanentError, TransientError
from training_kb.keys import ticket_pk
from training_kb.models import Ticket
from training_kb.repository import Repository
from training_kb.vectors import centroid, cosine
from training_kb.writing.client import BedrockWriter, CallTrace, build_bedrock_client

SEED_DIR = Path(__file__).resolve().parents[1] / "seed"
REPORT_NAME = "clustering_report.json"
CLUSTERED_NAME = "tickets_clustered.json"
OPERATION_ID = "demo-cluster-01"
EMBED_NODE = "ticket-embedding"
BLOCKED = "BLOCKED"
OBSERVED = "OBSERVED"


def clustering_report(*, status: str, reason: str | None, probed_at: datetime,
                      assigned: Sequence[Mapping[str, Any]] | None,
                      upstream: str | None = None) -> dict[str, Any]:
    """組出 `clustering_report.json` 的內容。

    `assigned is None` 代表**沒有觀察值**：`observed` 是 `null`（不是 `{}`，空物件會被
    誤讀成「跑過了、結果是空的」），`tickets` 是空陣列。

    `upstream` 是 **AWS 回的錯誤原文逐字**（`botocore` 的 `ClientError` 訊息）。
    產品程式（`BedrockWriter`）刻意只留錯誤碼，因為那條路徑的 message 可能回聲使用者輸入；
    本檔是**本機的 O5 證據腳本**，輸入是版控在 repo 裡的合成工單文字，沒有使用者資料，
    而 Phase 文件 §6.7 要求 BLOCKED 報告帶錯誤原文，所以這裡從例外鏈補記一次。
    """
    observed: dict[str, Any] | None = None
    if assigned is not None:
        clusters: dict[str, list[str]] = {}
        for row in assigned:
            clusters.setdefault(str(row["cluster_id"]), []).append(str(row["ticket_id"]))
        observed = {"cluster_count": len(clusters),
                    "clusters": {key: sorted(value) for key, value in sorted(clusters.items())}}
    return {"_notice": SYNTHETIC_NOTICE, "synthetic": True, "status": status, "reason": reason,
            "upstream": upstream, "probed_at": to_iso(probed_at), "operation_id": OPERATION_ID,
            "model_id": load_settings().embedding_model_id, "observed": observed,
            "tickets": [] if assigned is None else [dict(row) for row in assigned]}


def _rows(tickets: Sequence[Ticket], assigned: Mapping[str, str], *,
          repository: Repository, trace: CallTrace) -> list[dict[str, Any]]:
    """每筆工單一列：`ticket_id`、`cluster_id`、對同群其他成員群中心的 cosine、attempt 序號。

    `top_cosine` 是**觀察值**，用 `vectors.cosine`／`centroid` 事後量出來的；它不參與判定
    （判定在 `assign_cluster`），自己開新群的那一筆沒有可比對象，記 `null`。
    """
    stored = {row.id: row for row in repository.list_tickets(load_settings().project_id)}
    embed_records = [record for record in json.loads(trace.to_json())
                     if record["node"] == EMBED_NODE]
    rows: list[dict[str, Any]] = []
    for index, ticket in enumerate(tickets):
        cluster_id = assigned[ticket.id]
        mine = stored.get(ticket.id)
        peers = [row.embedding for row in stored.values()
                 if row.cluster_id == cluster_id and row.id != ticket.id and row.embedding]
        score = (cosine(mine.embedding, centroid(peers))
                 if peers and mine is not None and mine.embedding else None)
        attempt = embed_records[index]["attempt"] if index < len(embed_records) else None
        rows.append({"ticket_id": ticket.id, "cluster_id": cluster_id,
                     "top_cosine": score, "attempt": attempt})
    return rows


def _write(directory: Path, name: str, payload: Any) -> Path:
    path = directory / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _wiring() -> tuple[Repository, BedrockWriter, CallTrace]:
    """真實 DynamoDB／S3／Bedrock 的接線；client 一律在這裡才建立（同 handlers 的既有範式）。"""
    settings = load_settings()
    dynamodb = boto3.resource("dynamodb", region_name=settings.aws_region)
    s3 = boto3.resource("s3", region_name=settings.aws_region)
    repository = Repository(dynamodb.Table(settings.table_name),
                            s3.Bucket(settings.content_bucket))
    trace = CallTrace()
    writer = BedrockWriter(build_bedrock_client(settings.bedrock_region or "us-east-1"), trace,
                           generation_model_id=None,
                           embedding_model_id=settings.embedding_model_id)
    return repository, writer, trace


def main(argv: Sequence[str]) -> int:
    """跑一次真實分群；成功寫兩份檔案回 `0`，Bedrock 擋住寫 BLOCKED 報告回 `1`。

    退出碼 `1` 是**誠實的失敗**，不是可以忽略的警告：O7 的分群條件沒有取得證據。
    """
    directory = Path(argv[0]) if argv else SEED_DIR
    bundle = load_seed(directory)
    tickets = creation_tickets(bundle)
    repository, writer, trace = _wiring()
    try:
        assigned = cluster_demo_tickets(bundle, writer=writer, repository=repository,
                                        operation_id=OPERATION_ID)
    except (PermanentError, TransientError) as error:
        path = _write(directory, REPORT_NAME,
                      clustering_report(status=BLOCKED, reason=f"{type(error).__name__}: {error}",
                                        probed_at=now_utc(), assigned=None,
                                        upstream=None if error.__cause__ is None
                                        else str(error.__cause__)))
        print(f"BLOCKED：{type(error).__name__}: {error}", file=sys.stderr)
        print(f"報告：{path}（observed 為 null，未產生 {CLUSTERED_NAME}）", file=sys.stderr)
        return 1
    rows = _rows(tickets, assigned, repository=repository, trace=trace)
    _write(directory, CLUSTERED_NAME,
           {"_notice": SYNTHETIC_NOTICE, "synthetic": True, "batch_label": bundle.batch_label,
            "items": [{"ticket_pk": ticket_pk(row["ticket_id"]), **row} for row in rows]})
    _write(directory, REPORT_NAME, clustering_report(status=OBSERVED, reason=None,
                                                     probed_at=now_utc(), assigned=rows))
    print(f"已分群 {len(assigned)} 筆（前綴 {CREATION_TICKET_PREFIX}）："
          f"{len(set(assigned.values()))} 個群")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
