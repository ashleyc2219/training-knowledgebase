"""Phase 59 Task 3：`infra/scripts/check_asl.py` 對三份 ASL 快照的靜態檢查。

`check_asl_document` **包裝** Phase 29 的 `assert_safe_asl`（不重寫它的結構規則），
自己多做三件事：收齊**全部** Task 的問題（`assert_safe_asl` 第一個問題就丟例外）、
逐字比對 D-53 第二條 retrier 的四個 Lambda 服務錯誤、確認 `Catch` 導向 `PipelineFailed`。
兩者互補、不矛盾：`assert_safe_asl` 要求恰好一條 Catch，本檔的獨立檢查也是。
"""

import json
from pathlib import Path
from typing import Any

import pytest

from infra.scripts.check_asl import (
    ASL_ROOT,
    LAMBDA_SERVICE_ERRORS,
    check_asl_document,
    iter_task_states,
    main,
)
from training_kb.pipelines.asl import CATCH, FAIL_STATE_NAME, RETRY

ARN = "arn:aws:lambda:us-east-1:123456789012:function:training-kb-pipeline-task"
REPO_ROOT = Path(__file__).resolve().parents[2]
PIPELINES = ("ticket-analysis", "feedback-review", "release-update")


def _task(**extra: Any) -> dict[str, Any]:
    return {"Type": "Task", "Resource": ARN, "End": True, **extra}


def _complete_task() -> dict[str, Any]:
    return _task(Retry=[dict(item) for item in RETRY], Catch=[dict(item) for item in CATCH])


def _document() -> dict[str, Any]:
    """一份**故意有問題**的定義：`Work` 只有第一條 retrier、沒有 Catch，`Fan` 裡還有巢狀 Task。"""
    inner = {"Inner": _task()}
    return {"StartAt": "Work", "States": {
        FAIL_STATE_NAME: {"Type": "Fail", "Error": FAIL_STATE_NAME},
        "Work": _task(Retry=[dict(RETRY[0])]),
        "Fan": {"Type": "Map", "Next": "Work",
                "ItemProcessor": {"StartAt": "Inner", "States": inner}}}}


# --- 1. 逐條檢查 -------------------------------------------------------------


def test_missing_catch_and_second_retrier_are_reported() -> None:
    """Given 缺 Catch 與第二條 retrier 的定義，Then 四類問題都被列出來（不是只報第一個）。"""
    problems = check_asl_document(_document())
    assert any("Work" in item and "Catch" in item for item in problems)
    assert any(item.startswith("Task Fan.ItemProcessor.Inner") for item in problems)
    assert any("Lambda.ServiceException" in item for item in problems)
    assert any(item.startswith("assert_safe_asl") for item in problems)


def test_complete_document_has_no_problems() -> None:
    """Given 兩條 Retry ＋ 一條導向 `PipelineFailed` 的 Catch，Then 沒有任何問題。"""
    doc = _document()
    del doc["States"]["Fan"]
    doc["States"]["Work"] = _complete_task()
    assert check_asl_document(doc) == []


def test_missing_fail_state_is_reported() -> None:
    """Given 沒有 `PipelineFailed` 終點，Then 明確指出缺少 `Type=Fail` 的終點。"""
    doc = _document()
    del doc["States"]["Fan"]
    doc["States"]["Work"] = _complete_task()
    del doc["States"][FAIL_STATE_NAME]
    problems = check_asl_document(doc)
    assert any(FAIL_STATE_NAME in item and "Fail" in item for item in problems)


def test_second_retrier_is_compared_word_for_word() -> None:
    """Given 第二條 retrier 少了一個錯誤名，Then 報「缺少涵蓋 Lambda.ServiceException」。

    D-53 的第二條 retrier 是逐字契約（`LAMBDA_SERVICE_ERRORS`），少一個名稱就代表
    Lambda 服務層的暫時錯誤有一類不會被重試。
    """
    doc = _document()
    del doc["States"]["Fan"]
    doc["States"]["Work"] = _complete_task()
    doc["States"]["Work"]["Retry"][1] = {**dict(RETRY[1]),
                                         "ErrorEquals": LAMBDA_SERVICE_ERRORS[:3]}
    problems = check_asl_document(doc)
    assert any("Lambda.ServiceException" in item for item in problems)


def test_catch_pointing_somewhere_else_is_reported() -> None:
    """Given Catch 導向別的 state，Then 報它沒有把 `States.ALL` 導向 `PipelineFailed`。"""
    doc = _document()
    del doc["States"]["Fan"]
    doc["States"]["Work"] = _complete_task()
    doc["States"]["Elsewhere"] = {"Type": "Fail", "Error": "Elsewhere"}
    doc["States"]["Work"]["Catch"] = [{**dict(CATCH[0]), "Next": "Elsewhere"}]
    problems = check_asl_document(doc)
    assert any(FAIL_STATE_NAME in item and "Catch" in item for item in problems)


def test_lambda_service_errors_match_the_shared_retry_constant() -> None:
    """`LAMBDA_SERVICE_ERRORS` 與 Phase 29 `RETRY[1]` 的 `ErrorEquals` 必須是同一份清單。"""
    assert LAMBDA_SERVICE_ERRORS == RETRY[1]["ErrorEquals"]


# --- 2. 走訪 -----------------------------------------------------------------


def test_iter_task_states_walks_map_and_parallel() -> None:
    """Given `Map` 與 `Parallel` 的巢狀 Task，Then 走訪路徑帶得出完整位置。"""
    doc = {"StartAt": "Fan", "States": {
        "Fan": {"Type": "Map", "ItemProcessor": {"StartAt": "Inner",
                                                 "States": {"Inner": _task()}}},
        "Split": {"Type": "Parallel", "Branches": [
            {"StartAt": "Left", "States": {"Left": _task()}}]}}}
    found = [where for where, _ in iter_task_states(doc["States"])]
    assert found == ["Fan.ItemProcessor.Inner", "Split.Branches[0].Left"]


# --- 3. CLI ------------------------------------------------------------------


def test_main_reports_when_nothing_is_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                            capsys: pytest.CaptureFixture[str]) -> None:
    """Given 掃不到任何 ASL 定義，Then 印「找不到 ASL 定義」並回非 0（不得靜靜回 0）。"""
    monkeypatch.chdir(tmp_path)
    assert main([]) != 0
    assert "找不到 ASL 定義" in capsys.readouterr().out


def test_main_passes_on_the_three_real_definitions(
        capsys: pytest.CaptureFixture[str]) -> None:
    """Given repo 裡的三份 `infra/stepfunctions/<pipeline>/v1.json`，Then 全部 `[通過]`。"""
    paths = [str(REPO_ROOT / ASL_ROOT / pipeline / "v1.json") for pipeline in PIPELINES]
    assert main(paths) == 0
    printed = capsys.readouterr().out
    for pipeline in PIPELINES:
        assert "[通過] " in printed and pipeline in printed


def test_main_fails_when_a_catch_is_removed(tmp_path: Path,
                                            capsys: pytest.CaptureFixture[str]) -> None:
    """Given 刻意刪掉一個 Catch 的定義，Then `main` 回非 0 並印 `[不通過]`。"""
    source = REPO_ROOT / ASL_ROOT / "ticket-analysis" / "v1.json"
    doc = json.loads(source.read_text(encoding="utf-8"))
    for state in doc["States"].values():
        if state.get("Type") == "Task":
            del state["Catch"]
            break
    broken = tmp_path / "v1.json"
    broken.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    assert main([str(broken)]) == 1
    assert "[不通過]" in capsys.readouterr().out


def test_main_fails_when_the_second_retrier_is_removed(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Given 刻意刪掉第二條 retrier 的定義，Then `main` 回非 0。"""
    source = REPO_ROOT / ASL_ROOT / "release-update" / "v1.json"
    doc = json.loads(source.read_text(encoding="utf-8"))
    for state in doc["States"].values():
        if state.get("Type") == "Task":
            state["Retry"] = state["Retry"][:1]
            break
    broken = tmp_path / "v1.json"
    broken.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    assert main([str(broken)]) == 1
    assert "Lambda.ServiceException" in capsys.readouterr().out
