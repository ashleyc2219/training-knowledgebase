"""維護者本機的 Demo 控制台（Phase 58）：六個子命令，只有一條受控寫入路徑。

```text
uv run python -m demo.cli seed            # 唯一直接寫入；O7 未核定時直接拒絕
uv run python -m demo.cli trigger-ticket  --ticket-id t_3001
uv run python -m demo.cli upload-tickets  --source email --format json
uv run python -m demo.cli trigger-release --release-id r_42
uv run python -m demo.cli trigger-review  --mode demo
uv run python -m demo.cli import --file <widget 匯出檔> --kind feedback|view
uv run python -m demo.cli metrics --version prepare-meeting@v1
```

**寫入界線（設計 §13、Phase 58 §1）**：除了 `seed` 之外，本檔**不建立任何 DynamoDB client**，
所有寫入都走 `lambda:invoke`（受控匯入 Lambda `training-kb-import`、指標 Lambda
`training-kb-analytics`）或 `states:StartExecution`（`training-kb-feedback-review`）。
全檔唯一的 boto3 出口是 `_boto_client`，測試把它換掉就能證明「這次執行要過哪些 client」。

**身分與區域**：client 一律 `boto3.client(service, region_name=load_settings().aws_region)`，
本檔沒有任何金鑰字面值，也不接受金鑰參數；身分走維護者本機的 AWS 登入（R11）。

**本計畫選擇（2026-09-14，測試工單目錄後續補上）——`trigger-ticket`／`trigger-release` 送什麼：**
CLI 不讀 DynamoDB。工單原文從 **`demo/test-tickets/`**（`--tickets-dir`）依來源
email／discord／github_issue 與 json／csv／xlsx 讀出來；Release 仍從種子檔 `--dir`
（預設 `demo/seed`）。組成 00A D-60 的「可信入口設定 ＋ 原始事件」交給受控匯入
Lambda。可信入口設定是**維護者宣告**的（`TICKET_ENTRIES`／`RELEASE_ENTRY`，值取自
`tests/fixtures/o6/approved-sources.json` 已登記的手動匯入來源），不從 payload 反推。
`github_issue` 只接受 parser、不 invoke（正式入口是 webhook）。

**O5 BLOCKED**：`trigger-ticket` 觸發的正式 Ticket Analysis 會在 Titan／Claude 節點
`ValidationException: Operation not allowed` → `PermanentError` → Catch → PipelineFailed。
那是 gate 證據，不是這支 CLI 的錯誤。

**O7 未核定**：`demo/seed/approvals/` 的三份核定紀錄是空的，所以 `seed` 會印出
`missing_approvals` 並回非 0、**一個 item 都不寫**。這是正確行為，不是壞掉；要重新核定是
維護者的事（`demo/seed_loader.py` 沒有、也不得有任何自動填值路徑）。**沒有 `--force`。**

**`seed` 的寫入要明示 `--apply`**（修正波：final review C#2）：`apply_seed` 以
`create_only=False` 覆寫 `TUTORIAL#prepare-meeting`、`RULE#R-007`、`FEATURE#Prepare`
這些正式資料的主鍵，目標由 `load_settings()` 的環境變數決定。沒有 `--apply` 時只印報告與
**解析出來的 table／bucket**；`TKB_ENV=prod` 時連 `--apply` 都拒絕。
"""

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import boto3

from demo.seed_loader import BANNER, apply_seed, load_seed, render_report, verify_recipe
from demo.ticket_files import DEFAULT_TICKETS_DIR as DEFAULT_TICKETS_DIR
from demo.ticket_files import (
    FORMATS,
    GITHUB_ISSUE_HINT,
    SOURCES,
    find_ticket,
    load_file,
    load_slot,
)
from training_kb.clock import now_utc, to_iso
from training_kb.config import load_settings
from training_kb.errors import ContentError, PermanentError
from training_kb.faults import is_production
from training_kb.ingress import execution_name, operation_id_for
from training_kb.models import Release, Ticket, TicketSource
from training_kb.pipeline_starter import state_machine_arns
from training_kb.pipelines.common import PipelineName
from training_kb.repository import Repository

SUBCOMMANDS: tuple[str, ...] = (
    "seed", "trigger-ticket", "upload-tickets", "trigger-release", "trigger-review",
    "import", "metrics")
"""子命令順序就是 `--help` 的顯示順序；`upload-tickets` 讀測試工單目錄。"""

DEFAULT_SEED_DIR = "demo/seed"
"""Phase 56 的種子目錄；`seed`／`trigger-release` 的 `--dir` 預設值。"""

IMPORT_FUNCTION = "training-kb-import"
ANALYTICS_FUNCTION = "training-kb-analytics"
"""兩支具名 Lambda（00A §3.5）。這裡不 import `infra/`（會拉進整包 CDK），改由
`tests/unit/test_demo_cli.py::test_cli_function_names_match_the_deployed_stack` 逐字比對。"""

REVIEW_PIPELINE: PipelineName = "feedback-review"
REVIEW_MODES: tuple[str, ...] = ("formal", "demo")
"""Phase 44 的 `ReviewMode`；`argparse` 的 `choices`，未知的值在解析階段就 `SystemExit`。"""

IMPORT_KINDS: tuple[str, ...] = ("feedback", "view")
"""`import` 只收 Phase 42 的固定匯入兩種；`ticket`／`release` 走 `trigger-*`。"""

DEMO_SOURCE = "demo-cli"
"""送進匯入 Lambda 的來源標籤；只進 log 的計數，不影響去重鍵。"""

TICKET_ENTRIES: Mapping[str, tuple[str, str, str]] = {
    "email": ("mail.local", "email_manual", "manual_batch"),
    "discord": ("discord.com", "discord_manual", "manual_batch"),
}
"""`Ticket.source` -> (domain, adapter, event_type)。值與 O6 登記的手動匯入來源逐字相同。"""

RELEASE_ENTRY: tuple[str, str, str] = ("changelog.local", "changelog_manual", "manual_batch")
"""Release 一律以 changelog 手動匯入重放：種子的 Release 已經有 changelog 條目的六個欄位。"""

PROXY_NOTE = ("rate 是 proxy：窗口內先瀏覽後同群開票的不同使用者數／窗口內不同瀏覽者數，"
              "不是直接量測的教學成效；窗口端點待維護者核定（O4）")
NO_RATING = "尚無評分"
NO_SAMPLE = "N/A：樣本不足"
PENDING_APPROVAL = "待維護者核定"
APPLY_FLAG = "--apply"
"""`seed` 真的寫入的明示開關（修正波：final review C#2）。沒有它就只報告不寫。"""


def _boto_client(service: str) -> Any:
    """全檔唯一的 boto3 出口；區域來自 `load_settings()`，**不寫死也不接受金鑰參數**。

    測試把這個名字換掉，就能直接觀察「這次執行要過哪些 client」——
    「沒有呼叫 dynamodb」因此是被證明的，不是推論出來的。
    """
    # boto3 的 client 依 service 名字有上百個 overload，傳 `str` 型別上對不起來；
    # 本專案不用 `# type: ignore`，所以把工廠函式本身收成 `Any`（與 `Repository`
    # 的 `client: object` 同一條慣例，00A §6.3）。
    factory: Any = boto3.client
    return factory(service, region_name=_region())


def _region() -> str:
    region = load_settings().aws_region
    if not region:
        raise PermanentError("Demo 控制台需要 TKB_AWS_REGION；區域由環境決定，程式不寫死")
    return region


# --- 1. parser ---------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """子命令的參數定義；未知的 `--mode`／`--kind`／`--source` 在這一層就 `SystemExit`。"""
    parser = argparse.ArgumentParser(
        prog="python -m demo.cli",
        description=f"{BANNER}：維護者本機的 Demo 控制台（唯讀為主，寫入只走受控路徑）")
    sub = parser.add_subparsers(dest="command", required=True)

    seed = sub.add_parser(
        "seed", help=f"載入 Demo 種子；O7 未核定或沒有 {APPLY_FLAG} 時只報告不寫入")
    seed.add_argument("--dir", default=DEFAULT_SEED_DIR, help="種子目錄")
    seed.add_argument(APPLY_FLAG, action="store_true",
                      help="真的寫入 DynamoDB 與私有 S3 前綴（覆寫既有的 Demo 主鍵）")

    ticket = sub.add_parser(
        "trigger-ticket", help="以測試工單目錄裡的一張工單觸發正式 Ticket Analysis")
    ticket.add_argument("--ticket-id", required=True, help="測試工單的 ID")
    ticket.add_argument("--tickets-dir", default=DEFAULT_TICKETS_DIR, help="測試工單目錄")

    upload = sub.add_parser(
        "upload-tickets", help="把測試工單目錄（json／csv／xlsx）逐張送進 import Lambda")
    upload.add_argument("--tickets-dir", default=DEFAULT_TICKETS_DIR, help="測試工單目錄")
    upload.add_argument("--file", help="單一工單檔（路徑可在目錄外）")
    upload.add_argument("--source", choices=SOURCES, help="來源資料夾")
    upload.add_argument("--format", dest="ticket_format", choices=FORMATS, help="json／csv／xlsx")

    release = sub.add_parser("trigger-release", help="以種子裡的一筆 Release 觸發 Release Update")
    release.add_argument("--release-id", required=True, help="種子 releases.json 的 Release ID")
    release.add_argument("--dir", default=DEFAULT_SEED_DIR, help="種子目錄")

    review = sub.add_parser("trigger-review", help="啟動每日回饋檢視（input 逐字只有 mode）")
    review.add_argument("--mode", required=True, choices=REVIEW_MODES)

    imports = sub.add_parser("import", help="把 widget 匯出檔逐筆送進受控匯入 Lambda")
    imports.add_argument("--file", required=True, help="Phase 57 widget 的匯出檔")
    imports.add_argument("--kind", required=True, choices=IMPORT_KINDS)

    metrics = sub.add_parser("metrics", help="讀一個版本的指標（評分、負面回饋、重開票）")
    metrics.add_argument("--version", required=True, help="版本 ID，例如 prepare-meeting@v1")
    return parser


# --- 2. 共用小工具 -----------------------------------------------------------


def _invoke(function: str, event: Mapping[str, Any]) -> dict[str, Any]:
    """同步呼叫一支 Lambda 並把回應解成 dict；`FunctionError` 原樣往上丟。"""
    response = _boto_client("lambda").invoke(
        FunctionName=function, Payload=json.dumps(event, ensure_ascii=False).encode("utf-8"))
    body = response["Payload"].read()
    payload: Any = json.loads(body.decode("utf-8")) if body else {}
    if response.get("FunctionError"):
        raise PermanentError(f"{function} 失敗：{payload}")
    return payload if isinstance(payload, dict) else {"result": payload}


def _print_results(rows: Sequence[Mapping[str, Any]]) -> int:
    """逐筆印 `ImportResult`（`saved`／`duplicate`／`rejected`）；有 `rejected` 就回非 0。"""
    rejected = 0
    for row in rows:
        status = str(row.get("status"))
        rejected += status == "rejected"
        fields = row.get("fields") or ()
        print(f"  {status} object_id={row.get('object_id')} {row.get('message', '')}"
              + (f" fields={list(fields)}" if fields else ""))
    return 1 if rejected else 0


def _seed_bundle(directory: str) -> Any:
    return load_seed(Path(directory))


# --- 3. 六個 handler ---------------------------------------------------------


def _seed(args: argparse.Namespace) -> int:
    """唯一直接寫入的子命令：`load_seed` -> `verify_recipe` -> （兩道門都過才）`apply_seed`。

    **兩道門，缺一不可**：

    ```text
    1 O7 核定齊備   o7_ready；缺核定就印 missing_approvals 回非 0（沒有 --force 這個出口）
    2 明示 --apply  修正波（final review C#2）：沒有它就只印報告與**解析出來的目標**
    ```

    第 2 道是修正波加的。`apply_seed` 對 `TUTORIAL#prepare-meeting`、`RULE#R-007`、
    `RULE#R-012`、`FEATURE#Prepare` 這些**正式資料的主鍵**做 `create_only=False` 覆寫，
    目標表與 bucket 由 `load_settings()` 決定——維護者的 shell 指到哪就寫到哪。原本唯一的
    煞車是「O7 還沒核定」，核定一簽下去，`demo.cli seed` 就變成一個沒有確認步驟的覆寫指令。

    `TKB_ENV=prod` 一律拒絕（與 `faults.is_production` 同一個寬鬆比對）：合成資料明示是
    合成的（`SYNTHETIC_NOTICE`），不該進正式環境。

    印出解析後的表名與 bucket 是刻意的：寫入目標來自環境變數，看得到才確認得了。
    """
    bundle = _seed_bundle(args.dir)
    report = verify_recipe(bundle)
    print(render_report(bundle, report), end="")
    if not report.o7_ready:
        print(f"缺少核定紀錄（{PENDING_APPROVAL}）：{', '.join(report.missing_approvals)}")
        print("→ 未寫入任何資料。請維護者在 demo/seed/approvals/ 逐份簽名後再跑一次。")
        return 1
    settings = load_settings()
    print(f"寫入目標：table={settings.table_name} bucket={settings.content_bucket} "
          f"region={_region()}")
    if not args.apply:
        print(f"→ 未寫入任何資料。確認上面的目標無誤後，加上 {APPLY_FLAG} 再跑一次。")
        return 0
    if is_production():
        print(f"{BANNER}：TKB_ENV 是正式環境，拒絕寫入合成種子資料。", file=sys.stderr)
        return 2
    region = _region()
    repository = Repository(
        boto3.resource("dynamodb", region_name=region).Table(settings.table_name),
        boto3.resource("s3", region_name=region).Bucket(settings.content_bucket))
    written = apply_seed(bundle, repository=repository, now=now_utc())
    print(f"已寫入 {len(written)} 筆（批次 {bundle.batch_label}）")
    return 0


def _ticket_event(ticket: Ticket) -> dict[str, Any]:
    """一張測試工單 -> 受控匯入的一個 item（可信入口設定由本檔宣告，不從 payload 反推）。"""
    if ticket.source is TicketSource.GITHUB_ISSUE:
        raise PermanentError(GITHUB_ISSUE_HINT)
    entry = TICKET_ENTRIES.get(str(ticket.source))
    if entry is None:
        raise PermanentError(
            f"工單 {ticket.id} 的來源 {ticket.source} 沒有對應的手動匯入入口；"
            f"可用的是 {sorted(TICKET_ENTRIES)}")
    domain, adapter, event_type = entry
    item = {"id": ticket.id, "text": ticket.text, "author": ticket.author,
            "ts": to_iso(ticket.ts), "project_id": ticket.project_id}
    return {"domain": domain, "adapter": adapter, "event_type": event_type,
            "payload": {"source": str(ticket.source), "domain": domain, "adapter": adapter,
                        "batch_id": f"{DEMO_SOURCE}-{ticket.id}", "items": [item]}}


def _release_event(release: Release) -> dict[str, Any]:
    """一筆種子 Release -> changelog 手動匯入的一個 item（六個欄位種子已經有）。"""
    domain, adapter, event_type = RELEASE_ENTRY
    item = {"id": release.id, "feature": release.feature, "kind": str(release.kind),
            "old_name": release.old_name, "new_name": release.new_name,
            "evidence": release.evidence, "ts": to_iso(release.ts)}
    return {"domain": domain, "adapter": adapter, "event_type": event_type,
            "payload": {"source": "changelog", "domain": domain, "adapter": adapter,
                        "batch_id": f"{DEMO_SOURCE}-{release.id}", "items": [item]}}


def _invoke_ticket(ticket: Ticket) -> int:
    """一張工單一次 invoke；github_issue 在組事件時就拒絕，不會打 Lambda。"""
    try:
        event = {"kind": "ticket", "source": DEMO_SOURCE, "items": [_ticket_event(ticket)]}
    except PermanentError as error:
        print(str(error), file=sys.stderr)
        return 2
    print(f"[{BANNER}] invoke {IMPORT_FUNCTION} kind=ticket ticket_id={ticket.id}")
    return _print_results(_invoke(IMPORT_FUNCTION, event).get("results") or ())


def _trigger_ticket(args: argparse.Namespace) -> int:
    """送一張測試工單走正常 Ticket Analysis（D-68）；只呼叫 `lambda.invoke` 一次。"""
    try:
        found = find_ticket(Path(args.tickets_dir), args.ticket_id)
    except ContentError as error:
        print(str(error), file=sys.stderr)
        return 2
    if found is None:
        print(f"測試工單目錄沒有工單 {args.ticket_id}", file=sys.stderr)
        return 2
    return _invoke_ticket(found)


def _upload_tickets(args: argparse.Namespace) -> int:
    """`--file` 或 `--source`＋`--format` 擇一；一列一次 invoke。"""
    if args.file:
        if args.source or args.ticket_format:
            print("upload-tickets：`--file` 不能和 `--source`／`--format` 一起用",
                  file=sys.stderr)
            return 2
        try:
            tickets = load_file(Path(args.file))
        except ContentError as error:
            print(str(error), file=sys.stderr)
            return 2
    elif args.source and args.ticket_format:
        try:
            tickets = load_slot(Path(args.tickets_dir), args.source, args.ticket_format)
        except ContentError as error:
            print(str(error), file=sys.stderr)
            return 2
    else:
        print("upload-tickets：請給 `--file`，或同時給 `--source` 與 `--format`",
              file=sys.stderr)
        return 2
    if not tickets:
        print("沒有可上傳的工單", file=sys.stderr)
        return 2
    failed = 0
    for ticket in tickets:
        failed += 0 if _invoke_ticket(ticket) == 0 else 1
    return 1 if failed else 0


def _trigger_release(args: argparse.Namespace) -> int:
    """送一筆 Release 走正常 Release Update；只呼叫 `lambda.invoke` 一次。"""
    bundle = _seed_bundle(args.dir)
    found = next((row for row in bundle.releases if row.id == args.release_id), None)
    if found is None:
        print(f"種子裡沒有 Release {args.release_id}", file=sys.stderr)
        return 2
    event = {"kind": "release", "source": DEMO_SOURCE, "items": [_release_event(found)]}
    print(f"[{BANNER}] invoke {IMPORT_FUNCTION} kind=release release_id={found.id}")
    return _print_results(_invoke(IMPORT_FUNCTION, event).get("results") or ())


def _trigger_review(args: argparse.Namespace) -> int:
    """啟動當日回饋檢視（00A D-61）。

    input **逐字只有** `{"mode": <mode>}`：沒有 `project_id`、沒有任何「排程時刻」欄位，
    與 EventBridge Scheduler 送給同一條 state machine 的形狀完全相同。execution name 由
    `execution_name(operation_id_for("feedback-review", f"{project_id}-{UTC 日期}"))` 算出來，
    與 Phase 48 `review_operation_id` 的算式逐字相同（canonical id 用 `-` 不用 `#`），
    所以同一天重送會落在同一筆 operation 紀錄。
    """
    project_id = load_settings().project_id
    canonical = f"{project_id}-{datetime.now(UTC).date().isoformat()}"
    operation_id = operation_id_for("feedback-review", canonical)
    name = execution_name(operation_id)
    payload = json.dumps({"mode": args.mode}, sort_keys=True)
    account = str(_boto_client("sts").get_caller_identity()["Account"])
    arn = state_machine_arns(region=_region(), account_id=account)[REVIEW_PIPELINE]
    response = _boto_client("stepfunctions").start_execution(
        stateMachineArn=arn, name=name, input=payload)
    print(f"input={payload}")
    print(f"operation_id={operation_id}")
    print(f"execution_arn={response['executionArn']}")
    return 0


def _import(args: argparse.Namespace) -> int:
    """把 widget 匯出檔 `{kind, source, generated_at, note, items}` **逐筆**送出。

    一個 item 一次 `lambda.invoke`，對應 Phase 42 的一次 `import_feedback`／`import_view`
    與一個 `ImportResult`；一筆 `rejected` 不影響其他筆，但整體退出碼會是非 0。
    """
    envelope: Any = json.loads(Path(args.file).read_text(encoding="utf-8"))
    if not isinstance(envelope, dict) or envelope.get("kind") != args.kind:
        print(f"匯入檔的 kind 是 {envelope.get('kind') if isinstance(envelope, dict) else '?'}，"
              f"與 --kind {args.kind} 不符", file=sys.stderr)
        return 2
    items = envelope.get("items")
    if not isinstance(items, list) or not items:
        print("匯入檔的 items 必須是非空陣列", file=sys.stderr)
        return 2
    source = str(envelope.get("source") or DEMO_SOURCE)
    print(f"[{BANNER}] invoke {IMPORT_FUNCTION} kind={args.kind} items={len(items)}")
    failed = 0
    for index, item in enumerate(items):
        event = {"kind": args.kind, "source": source, "items": [item]}
        print(f"items[{index}]")
        failed += _print_results(_invoke(IMPORT_FUNCTION, event).get("results") or ())
    return 1 if failed else 0


def _metrics(args: argparse.Namespace) -> int:
    """讀一個版本的指標；公式一份都不在本檔，全部由 analytics Lambda（P53／P54）算。"""
    event = {"action": "metrics", "version_ids": [args.version]}
    results = _invoke(ANALYTICS_FUNCTION, event).get("results") or ()
    for row in results:
        reopen = row.get("reopen") or {}
        average = row.get("average")
        rate = reopen.get("rate")
        print(f"{row.get('version_id')} "
              f"avg={NO_RATING if average is None else average}"
              f"（顯示 {row.get('display_average')}） "
              f"n={row.get('sample_size')} negative={row.get('negative')} "
              f"reopen 筆數={reopen.get('count')} 分子={reopen.get('reopen_users')} "
              f"分母={reopen.get('viewers')} "
              f"rate={NO_SAMPLE if rate is None else rate}")
        print(f"  {PROXY_NOTE}")
    return 0 if results else 1


_HANDLERS: Mapping[str, Any] = {
    "seed": _seed, "trigger-ticket": _trigger_ticket, "upload-tickets": _upload_tickets,
    "trigger-release": _trigger_release, "trigger-review": _trigger_review,
    "import": _import, "metrics": _metrics,
}


def main(argv: Sequence[str] | None = None) -> int:
    """依子命令分派；每個 handler 自己回退出碼（0 成功、非 0 有問題）。"""
    args = build_parser().parse_args(None if argv is None else list(argv))
    result: int = _HANDLERS[args.command](args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
