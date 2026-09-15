"""Phase 58 Task 1：Demo 控制台六個子命令與「唯一寫入路徑」的守門。

Given 維護者在本機用 `python -m demo.cli <子命令>`
When 每個子命令跑完
Then 除了受控的 `seed` 匯入之外，所有寫入都只經過 `lambda:invoke` 或 `states:StartExecution`，
     而且**沒有任何一個子命令碰 DynamoDB**。

本檔不連 AWS：`demo.cli._boto_client` 被換成 `FakeAws`，它同時扮演 lambda／stepfunctions／sts
三個 client，並把「要了哪些 service」「送出什麼 payload」全部記下來，所以
「沒有呼叫 dynamodb」這句話是由**要過哪些 client** 直接證明的，不是推論。
"""

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest

from demo.cli import (
    ANALYTICS_FUNCTION,
    DEFAULT_SEED_DIR,
    IMPORT_FUNCTION,
    SUBCOMMANDS,
    build_parser,
    main,
)

ACCOUNT = "111122223333"
REGION = "us-east-1"
SEED_DIR = "demo/seed"


class FakeAws:
    """一個物件扮演三種 boto3 client；`services` 是「這次執行要了哪些 client」的完整清單。"""

    def __init__(self, payloads: Sequence[dict[str, Any]] = ()) -> None:
        self.services: list[str] = []
        self.invocations: list[tuple[str, dict[str, Any]]] = []
        self.executions: list[tuple[str, str, str]] = []
        self._payloads = [dict(row) for row in payloads]

    def __call__(self, service: str) -> "FakeAws":
        self.services.append(service)
        return self

    # --- lambda ---
    def invoke(self, *, FunctionName: str, Payload: bytes) -> dict[str, Any]:  # noqa: N803
        self.invocations.append((FunctionName, json.loads(Payload.decode("utf-8"))))
        body = self._payloads.pop(0) if self._payloads else {}
        return {"StatusCode": 200, "Payload": BytesIO(json.dumps(body).encode("utf-8"))}

    # --- stepfunctions ---
    def start_execution(self, *, stateMachineArn: str, name: str,  # noqa: N803
                        input: str) -> dict[str, str]:
        self.executions.append((stateMachineArn, name, input))
        arn = stateMachineArn.replace(":stateMachine:", ":execution:")
        return {"executionArn": f"{arn}:{name}"}

    # --- sts ---
    def get_caller_identity(self) -> dict[str, str]:
        return {"Account": ACCOUNT}


@pytest.fixture
def aws(monkeypatch: pytest.MonkeyPatch) -> FakeAws:
    """把 `demo.cli` 的唯一 boto3 出口換成假的，並固定區域與專案。"""
    monkeypatch.setenv("TKB_AWS_REGION", REGION)
    monkeypatch.setenv("TKB_PROJECT_ID", "demo")
    fake = FakeAws()
    monkeypatch.setattr("demo.cli._boto_client", fake)
    return fake


def run(argv: Sequence[str], aws: FakeAws, payloads: Sequence[dict[str, Any]] = ()) -> int:
    aws._payloads = [dict(row) for row in payloads]
    return main(list(argv))


# --- 1. 參數 -----------------------------------------------------------------


def test_parser_has_exactly_six_subcommands() -> None:
    """Given 控制台 When 建立 parser Then 子命令恰好是 `SUBCOMMANDS` 六個。"""
    parser = build_parser()
    actions = [action for action in parser._actions if action.dest == "command"]
    assert len(actions) == 1
    assert actions[0].choices is not None
    assert set(actions[0].choices) == set(SUBCOMMANDS)
    assert len(SUBCOMMANDS) == 6


@pytest.mark.parametrize("mode", ["formal", "demo"])
def test_trigger_review_accepts_only_known_modes(mode: str) -> None:
    """Given `--mode` 是 `ReviewMode` 兩個值之一 When 解析 Then 原樣收下。"""
    assert build_parser().parse_args(["trigger-review", "--mode", mode]).mode == mode


def test_trigger_review_rejects_unknown_mode() -> None:
    """Given `--mode loose` When 解析 Then `SystemExit`，一條流程都沒啟動。"""
    with pytest.raises(SystemExit):
        build_parser().parse_args(["trigger-review", "--mode", "loose"])


def test_seed_dir_defaults_to_demo_seed() -> None:
    """Given 沒給 `--dir` When 解析 Then 預設是 `demo/seed`（Phase 56 的種子目錄）。"""
    assert build_parser().parse_args(["seed"]).dir == DEFAULT_SEED_DIR
    assert DEFAULT_SEED_DIR == SEED_DIR


# --- 2. trigger-review：input 逐字只有 mode（00A D-61）------------------------


def test_trigger_review_sends_mode_only_and_derived_execution_name(
        aws: FakeAws, capsys: pytest.CaptureFixture[str]) -> None:
    """Given `--mode demo` When 觸發 Then input 逐字 `{"mode": "demo"}`、名稱由 op-id 導出。"""
    assert run(["trigger-review", "--mode", "demo"], aws) == 0
    assert aws.invocations == []
    assert len(aws.executions) == 1
    arn, name, payload = aws.executions[0]
    assert json.loads(payload) == {"mode": "demo"}
    assert payload == '{"mode": "demo"}'
    today = datetime.now(UTC).date().isoformat()
    assert name == f"op-feedback-review-demo-{today}"
    assert arn == (f"arn:aws:states:{REGION}:{ACCOUNT}"
                   ":stateMachine:training-kb-feedback-review")
    printed = capsys.readouterr().out
    assert '{"mode": "demo"}' in printed
    assert f"op-feedback-review-demo-{today}" in printed


def test_trigger_review_only_uses_stepfunctions_and_sts(aws: FakeAws) -> None:
    """Given 觸發 review When 跑完 Then 只要過 stepfunctions 與 sts，沒有 dynamodb。"""
    assert run(["trigger-review", "--mode", "formal"], aws) == 0
    assert set(aws.services) == {"stepfunctions", "sts"}


# --- 3. trigger-ticket／trigger-release：只呼叫 lambda.invoke -------------------


def test_trigger_ticket_invokes_import_lambda_with_one_item(
        aws: FakeAws, capsys: pytest.CaptureFixture[str]) -> None:
    """Given 一張 B 類工單 When `trigger-ticket` Then 只送一次 `lambda.invoke`，形狀是受控匯入。"""
    reply = {"kind": "ticket", "source": "demo-cli",
             "results": [{"status": "saved", "object_id": "t_3001",
                          "message": "ticket 已交給 op-ticket-t_3001", "fields": []}]}
    assert run(["trigger-ticket", "--ticket-id", "t_3001"], aws, [reply]) == 0
    assert aws.executions == []
    assert len(aws.invocations) == 1
    function, event = aws.invocations[0]
    assert function == IMPORT_FUNCTION
    assert event["kind"] == "ticket"
    assert len(event["items"]) == 1
    item = event["items"][0]
    assert (item["domain"], item["adapter"], item["event_type"]) == (
        "mail.local", "email_manual", "manual_batch")
    inner = item["payload"]["items"][0]
    assert inner["id"] == "t_3001"
    assert inner["text"]            # 原文來自種子檔，不由 CLI 捏造
    assert set(aws.services) == {"lambda"}
    assert "saved" in capsys.readouterr().out


def test_trigger_ticket_rejects_unknown_ticket(aws: FakeAws) -> None:
    """Given 種子裡沒有這張工單 When `trigger-ticket` Then 回非 0 且沒有送出任何請求。"""
    assert run(["trigger-ticket", "--ticket-id", "t_0000"], aws) != 0
    assert aws.invocations == [] and aws.executions == []


def test_trigger_release_invokes_import_lambda_with_one_item(aws: FakeAws) -> None:
    """Given 一筆種子 Release When `trigger-release` Then 只送一次 `lambda.invoke`。"""
    reply = {"kind": "release", "source": "demo-cli",
             "results": [{"status": "saved", "object_id": "r_42", "message": "", "fields": []}]}
    assert run(["trigger-release", "--release-id", "r_42"], aws, [reply]) == 0
    assert aws.executions == []
    function, event = aws.invocations[0]
    assert function == IMPORT_FUNCTION and event["kind"] == "release"
    item = event["items"][0]
    assert (item["domain"], item["adapter"], item["event_type"]) == (
        "changelog.local", "changelog_manual", "manual_batch")
    assert item["payload"]["items"][0]["id"] == "r_42"
    assert set(aws.services) == {"lambda"}


# --- 4. import：每個 item 各送一次（P42 的一次 ImportResult）--------------------


def test_import_sends_one_invoke_per_item_and_prints_each_status(
        tmp_path: Path, aws: FakeAws, capsys: pytest.CaptureFixture[str]) -> None:
    """Given 兩筆的 widget 匯入檔 When `import` Then 兩次 invoke、逐筆印狀態。"""
    envelope = {"kind": "feedback", "source": "widget-download",
                "generated_at": "2026-09-14T00:00:00Z", "note": "合成資料示範",
                "items": [{"id": "f_900", "tutorial_version": "prepare-meeting@v2"},
                          {"id": "f_901", "tutorial_version": "prepare-meeting@v2"}]}
    path = tmp_path / "feedback.json"
    path.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
    replies = [{"kind": "feedback", "source": "widget-download",
                "results": [{"status": status, "object_id": f"f_{index}",
                             "message": "", "fields": []}]}
               for index, status in enumerate(("saved", "duplicate"))]
    assert run(["import", "--file", str(path), "--kind", "feedback"], aws, replies) == 0
    assert len(aws.invocations) == 2
    for _, event in aws.invocations:
        assert len(event["items"]) == 1
        assert event["kind"] == "feedback"
    printed = capsys.readouterr().out
    assert "saved" in printed and "duplicate" in printed
    assert set(aws.services) == {"lambda"}


def test_import_rejects_kind_mismatch(tmp_path: Path, aws: FakeAws) -> None:
    """Given 檔頭 `kind` 與 `--kind` 不同 When `import` Then 回非 0 且一次都不送。"""
    path = tmp_path / "view.json"
    path.write_text(json.dumps({"kind": "view", "items": [{}]}), encoding="utf-8")
    assert run(["import", "--file", str(path), "--kind", "feedback"], aws) != 0
    assert aws.invocations == []


# --- 5. metrics ---------------------------------------------------------------


def test_metrics_invokes_analytics_and_prints_numerator_and_denominator(
        aws: FakeAws, capsys: pytest.CaptureFixture[str]) -> None:
    """Given 一個版本 When `metrics` Then 只呼叫 analytics Lambda，畫面同時有分子分母與 proxy。"""
    reply = {"action": "metrics", "results": [{
        "version_id": "prepare-meeting@v1", "average": 2.875, "display_average": "2.9",
        "sample_size": 8, "negative": 8,
        "reopen": {"count": 7, "reopen_users": 7, "viewers": 10, "rate": 0.7}}]}
    assert run(["metrics", "--version", "prepare-meeting@v1"], aws, [reply]) == 0
    function, event = aws.invocations[0]
    assert function == ANALYTICS_FUNCTION
    assert event == {"action": "metrics", "version_ids": ["prepare-meeting@v1"]}
    printed = capsys.readouterr().out
    for fragment in ("2.875", "2.9", "分子=7", "分母=10", "0.7", "proxy"):
        assert fragment in printed
    assert set(aws.services) == {"lambda"}


def test_metrics_zero_sample_shows_na_not_zero(
        aws: FakeAws, capsys: pytest.CaptureFixture[str]) -> None:
    """Given 零評分零瀏覽 When `metrics` Then 印「尚無評分」與「N/A：樣本不足」，不印 0 分或 0%。"""
    reply = {"action": "metrics", "results": [{
        "version_id": "share-summary@v1", "average": None, "display_average": "尚無評分",
        "sample_size": 0, "negative": 0,
        "reopen": {"count": 0, "reopen_users": 0, "viewers": 0, "rate": None}}]}
    assert run(["metrics", "--version", "share-summary@v1"], aws, [reply]) == 0
    printed = capsys.readouterr().out
    assert "尚無評分" in printed and "樣本不足" in printed
    assert "0%" not in printed and "avg=0" not in printed


# --- 6. seed：O7 未核定就拒絕，而且一個字都不寫 --------------------------------


def test_seed_refuses_and_writes_nothing_while_approvals_missing(
        aws: FakeAws, capsys: pytest.CaptureFixture[str]) -> None:
    """Given `o7_ready is False` When `seed` Then 印 `missing_approvals`、回非 0、零寫入。"""
    assert run(["seed", "--dir", SEED_DIR], aws) != 0
    printed = capsys.readouterr().out
    assert "R007-B1" in printed and "待維護者核定" in printed
    assert "O7 已通過" not in printed
    assert aws.services == []      # 連 client 都沒有要過，遑論寫入


# --- 7. 全域守門 --------------------------------------------------------------


def test_no_subcommand_ever_asks_for_a_dynamodb_client(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Given 六個子命令都跑一次 When 收集要過的 client Then 沒有 `dynamodb`。"""
    monkeypatch.setenv("TKB_AWS_REGION", REGION)
    monkeypatch.setenv("TKB_PROJECT_ID", "demo")
    path = tmp_path / "view.json"
    path.write_text(json.dumps({"kind": "view", "items": [{"id": "v_1"}]}), encoding="utf-8")
    runs = (["seed", "--dir", SEED_DIR],
            ["trigger-ticket", "--ticket-id", "t_3001"],
            ["trigger-release", "--release-id", "r_42"],
            ["trigger-review", "--mode", "demo"],
            ["import", "--file", str(path), "--kind", "view"],
            ["metrics", "--version", "prepare-meeting@v1"])
    services: list[str] = []
    for argv in runs:
        fake = FakeAws([{"results": [{"status": "saved", "object_id": None,
                                      "message": "", "fields": []}]},
                        {"action": "metrics", "results": []}])
        monkeypatch.setattr("demo.cli._boto_client", fake)
        main(argv)
        services += fake.services
    assert "dynamodb" not in services
    assert set(services) <= {"lambda", "stepfunctions", "sts"}


def test_cli_function_names_match_the_deployed_stack() -> None:
    """Given CDK 已固定兩支 Lambda 名 When 比對 CLI 常數 Then 逐字相同（名稱只有一份）。"""
    from infra.training_kb_stack import ANALYTICS_FUNCTION as CDK_ANALYTICS
    from infra.training_kb_stack import IMPORT_FUNCTION as CDK_IMPORT

    assert (IMPORT_FUNCTION, ANALYTICS_FUNCTION) == (CDK_IMPORT, CDK_ANALYTICS)


def test_cli_source_has_no_credentials_or_region_literal() -> None:
    """Given `demo/cli.py` When 讀原始碼 Then 沒有金鑰字面值，也沒有寫死區域。"""
    source = Path("demo/cli.py").read_text(encoding="utf-8")
    for banned in ("AKIA", "aws_secret", "aws_access_key", "us-east-1", "123456789012"):
        assert banned not in source
