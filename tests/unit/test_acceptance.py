"""Phase 60 Task 3／4：Demo 預演、停用清單與 168 列證據索引。

這支檔**完全離線**：`rehearse` 的四項用假的 boto3 invoker 與假的 HTTP poster 驗行為，
證據索引只讀 repo 內的 00B 與 `.feature`，`rule_coverage` 吃呼叫端給的 nodeid 集合
（真正的 `pytest --collect-only` 在 `checks acceptance --rebuild` 才跑）。
"""

import json
import re
from collections.abc import Mapping
from pathlib import Path

from infra.scripts.checks import (
    ACCEPTANCE_ROWS,
    GATE_OVERRIDES,
    PROJECT_ROOT,
    acceptance_report,
    build_evidence,
    deploy_checklist,
    feature_rule_counts,
    load_evidence,
    parse_coverage,
    rehearse_steps,
    rule_coverage,
    run_rehearsal,
    teardown_checklist,
)

ABBREVIATIONS = ("REL", "TIC", "RUN", "APL", "REV", "VER", "ING", "PRP", "COL", "GPH",
                 "MET", "PUB", "VAL")


def test_rehearse_covers_four_required_items() -> None:
    """Given 預演清單／When rehearse_steps／Then 四項齊全且句式一致。"""
    steps = rehearse_steps()
    joined = "\n".join(steps)
    assert "三次不同事件" in joined and "success_count" in joined
    assert "正確簽名" in joined and "錯誤簽名" in joined
    assert "小量" in joined and "重送" in joined
    assert all(step.startswith(("檢查", "執行", "確認")) for step in steps)


def test_deploy_checklist_covers_the_five_pre_deploy_switches() -> None:
    """Given 部署前清單／When deploy_checklist／Then 五項守門都在（P59 §7 的三個開關）。"""
    items = deploy_checklist()
    for keyword in ("TKB_ENV=prod", "TKB_FAULT", "TKB_FAULT_TASK",
                    "build_lambda_layer", "check_asl", "site/"):
        assert any(keyword in item for item in items), keyword


def test_teardown_lists_every_resource_to_disable() -> None:
    """Given 停用清單／When teardown_checklist／Then 五類資源都在。"""
    items = teardown_checklist()
    for keyword in ("EventBridge", "Function URL", "TKB_FAULT", "site/", "webhook secret"):
        assert any(keyword in item for item in items), keyword


def test_rehearsal_is_not_run_without_aws() -> None:
    """Given 沒有 AWS 也沒有 Function URL／When run_rehearsal／Then 四項全是 not_run。"""
    results = run_rehearsal(webhook_url="", secret=b"", payload=b"{}", invoker=None)
    assert [result.status for result in results] == ["not_run"] * 4


def test_rehearsal_reads_success_count_from_the_real_table() -> None:
    """Given PROC 的 success_count 為 3／When run_rehearsal／Then 第一項 pass。"""

    def invoker(service: str, operation: str,
                kwargs: Mapping[str, object]) -> Mapping[str, object]:
        assert (service, operation) == ("dynamodb", "scan")
        return {"Items": [{"PK": {"S": "PROC#abc"}, "success_count": {"N": "3"}}]}

    results = run_rehearsal(webhook_url="", secret=b"", payload=b"{}", invoker=invoker)
    assert results[0].status == "pass"
    assert any("success_count=3" in item for item in results[0].findings)


def test_rehearsal_below_three_successes_is_not_run() -> None:
    """Given success_count 只有 2／When run_rehearsal／Then 第一項 not_run（不是 pass）。"""

    def invoker(service: str, operation: str,
                kwargs: Mapping[str, object]) -> Mapping[str, object]:
        return {"Items": [{"PK": {"S": "PROC#abc"}, "success_count": {"N": "2"}}]}

    results = run_rehearsal(webhook_url="", secret=b"", payload=b"{}", invoker=invoker)
    assert results[0].status == "not_run"


def test_rehearsal_signature_pair_and_resend(monkeypatch: object) -> None:
    """Given 正確簽名接受、錯誤簽名拒絕、重送同一 operation／Then 兩項 pass。"""
    sent: list[Mapping[str, str]] = []

    def poster(url: str, body: bytes, headers: Mapping[str, str]) -> tuple[int, str]:
        sent.append(dict(headers))
        if headers["X-Hub-Signature-256"].endswith("0" * 64):
            return 200, '{"operation_id":null,"ok":false,"message":"GitHub 簽名不符"}'
        return 200, '{"operation_id":"op-ticket-x","ok":true}'

    results = run_rehearsal(webhook_url="http://example.invalid/", secret=b"s",
                            payload=b"{}", invoker=None, poster=poster)
    assert results[1].status == "pass", results[1].findings
    assert results[3].status == "pass", results[3].findings
    assert [headers["X-GitHub-Delivery"] for headers in sent] == [
        "d-p60-001", "d-p60-bad", "d-p60-002"]


def test_rehearsal_model_call_is_blocked_by_o5() -> None:
    """Given O5 BLOCKED／When run_rehearsal／Then 小量模型呼叫那一項固定 not_run。"""
    results = run_rehearsal(webhook_url="", secret=b"", payload=b"{}", invoker=None)
    assert results[2].status == "not_run"
    assert any("o5-20260915T030245Z.md" in item for item in results[2].findings)


def test_acceptance_rows_cover_every_required_id() -> None:
    """Given 168 列索引／When 檢查 row_id／Then V、S、147 條 Rule 都齊。"""
    ids = {row.row_id for row in ACCEPTANCE_ROWS}
    assert {"V1", "V2", "V3", "V4"} <= ids
    assert {f"S{n}" for n in range(9)} <= ids
    assert sum(1 for row in ACCEPTANCE_ROWS if row.group == "rule") == 147
    assert len(ACCEPTANCE_ROWS) == 168


def test_every_rule_row_carries_owner_and_verify_phases() -> None:
    """Given Rule 列／When 檢查 primary 與縮寫／Then 一律有 primary，且沒有 `FDB#`。"""
    rules = [row for row in ACCEPTANCE_ROWS if row.group == "rule"]
    assert all(row.owner_phase.startswith("P") for row in rules)
    assert all(re.fullmatch(r"P\d\d", row.owner_phase) for row in rules)
    assert {row.row_id for row in rules if row.row_id.startswith("COL#")}
    assert not [row for row in rules if row.row_id.startswith("FDB#")]
    assert all(row.description for row in rules)


def test_rule_row_counts_match_the_feature_files() -> None:
    """Given 13 份 `.feature`／When 重數 `Rule:`／Then 每個縮寫的列數與實際條數相同。"""
    counts = feature_rule_counts()
    assert sum(counts.values()) == 147, counts
    per_abbreviation = {abbreviation: 0 for abbreviation in ABBREVIATIONS}
    for row in ACCEPTANCE_ROWS:
        if row.group == "rule":
            per_abbreviation[row.row_id.split("#")[0]] += 1
    assert sorted(per_abbreviation.values()) == sorted(counts.values())
    assert sum(per_abbreviation.values()) == 147


def test_every_rule_row_points_at_an_existing_assertion_file() -> None:
    """Given 00B 的「可觀察 assertion」欄／When 檢查檔案／Then 每一列至少一個檔存在。"""
    missing: list[str] = []
    for entry in parse_coverage():
        paths = [path for path, _ in entry.assertions]
        if not paths or not any((PROJECT_ROOT / path).is_file() for path in paths):
            missing.append(f"{entry.row_id}: {paths}")
    assert missing == [], missing


def test_rule_coverage_marks_uncollected_assertions_as_gaps() -> None:
    """Given 一個收不到那支檔的 nodeid 集合／When rule_coverage／Then 該列是空 tuple。"""
    entries = parse_coverage()
    first = entries[0]
    path, function = first.assertions[0]
    good = rule_coverage(frozenset({f"{path}::{function or 'test_x'}"}), entries=[first])
    assert good[first.row_id] != () or function != ""
    empty = rule_coverage(frozenset({"tests/unit/test_nothing.py::test_x"}), entries=[first])
    assert empty[first.row_id] == ()


def test_missing_evidence_blocks_completion() -> None:
    """Given 只給 V1 一列證據／When acceptance_report／Then 布林 False 且含免責句。"""
    text, ok = acceptance_report(
        ACCEPTANCE_ROWS, {"V1": "site/tutorials/prepare-meeting/v1.html"})
    assert ok is False
    assert "[not_run]" in text
    assert "文件 parser 成功不等於 runtime 通過" in text


def test_fail_prefix_is_reported_as_fail() -> None:
    """Given `fail:<原因>`／When acceptance_report／Then 標 fail 並印出原因。"""
    text, ok = acceptance_report(ACCEPTANCE_ROWS, {"PUB#4": "fail:O3 仍是 FAIL"})
    assert ok is False
    assert "[fail]" in text and "O3 仍是 FAIL" in text


def test_not_run_prefix_keeps_the_gate_pointer() -> None:
    """Given `not_run:<原因>`／When acceptance_report／Then 仍是 not_run 但看得到 gate 報告。"""
    text, ok = acceptance_report(
        ACCEPTANCE_ROWS, {"AWS-MODELS": "not_run:O5 BLOCKED — o5-20260915T030245Z.md"})
    assert ok is False
    assert "O5 BLOCKED" in text


def test_a_fully_evidenced_index_is_complete() -> None:
    """Given 每一列都有證據／When acceptance_report／Then 布林 True，但免責句仍在。"""
    evidence = {row.row_id: "evidence" for row in ACCEPTANCE_ROWS}
    text, ok = acceptance_report(ACCEPTANCE_ROWS, evidence)
    assert ok is True
    assert "文件 parser 成功不等於 runtime 通過" in text


def test_gate_overrides_only_push_rows_down() -> None:
    """Given gate 覆寫表／When build_evidence／Then 覆寫的列一律不是 pass。"""
    coverage = {row.row_id: ("tests/unit/x.py::test_y",)
                for row in ACCEPTANCE_ROWS if row.group == "rule"}
    evidence = build_evidence(coverage=coverage)
    for row_id, value in GATE_OVERRIDES.items():
        assert evidence[row_id] == value
        assert value.startswith(("fail:", "not_run:")), row_id
    _, ok = acceptance_report(ACCEPTANCE_ROWS, evidence)
    assert ok is False


def test_load_evidence_round_trips(tmp_path: Path) -> None:
    """Given 一份 evidence.json／When load_evidence／Then 鍵值都是字串。"""
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps({"V1": "a", "S0": "fail:x"}, ensure_ascii=False),
                    encoding="utf-8")
    assert load_evidence(path) == {"V1": "a", "S0": "fail:x"}
