"""Release Note Update pipeline：擷取變更 → 找受影響 Tutorial → UPDATE / RETIRE。

契約見 docs/spec/features/依ReleaseNote更新Tutorial.feature（七條 Rule）：
- 只處理 `processed_at` 為空的 Release；有值的不再處理。
- 擷取產品變更寫入 `ReleaseFeatureChange`；對不到既有 Feature 就不新建，只記 processed_at。
- 受影響 Tutorial **只依 `Tutorial.feature_id`** 命中（不濾 status）。
- renamed / changed → UPDATE（產新版、Feature 改名、旗標回 false、last_action=UPDATE）。
- deprecated / removed → RETIRE（retired、is_obsolete、Feature.status，不產新版、不改 current_version）。
- new → 不決定動作。

降級（黑客松當天沒有 LLM 金鑰時的預設路徑）：
- 擷取：`llm.complete_json` → `LLMUnavailable` → regex 規則式（只認劇本句型），標 `source="rule"`。
- 改寫：LLM 失敗 → 對五欄做 `str.replace(from_name, to_name)` 字面替換。
- 多跳：`hydra` 為 None 或呼叫失敗 → SQL `Tutorial.feature_id` 命中。
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.agent import llm, rules
from app.errors import OperationFailed

# --- SQL（Phase 5 專屬，依總覽 §現況更新放在本模組，不回改 app/analytics/sql.py） ---

UNPROCESSED_RELEASES = """
SELECT id, content, created_at, processed_at FROM Release
WHERE processed_at IS NULL OR processed_at = ''
ORDER BY created_at, id
"""

ALL_FEATURES = "SELECT id, name, status FROM Feature ORDER BY id"

INSERT_RELEASE_FEATURE_CHANGE = """
INSERT INTO ReleaseFeatureChange (release_id, feature_id, change_type, from_name, to_name)
VALUES (:release_id, :feature_id, :change_type, :from_name, :to_name)
"""

# Rule 5：只依 feature_id，不濾 status
TUTORIALS_BY_FEATURE = "SELECT * FROM Tutorial WHERE feature_id = :feature_id ORDER BY tutorial_id"

VERSION_ROW = """
SELECT * FROM TutorialVersion
WHERE tutorial_id = :tutorial_id AND tutorial_version = :tutorial_version
"""

INSERT_VERSION = """
INSERT INTO TutorialVersion
  (tutorial_id, tutorial_version, title, problem, prerequisites,
   steps, expected_outcome, reason, supersedes_version, created_at)
VALUES
  (:tutorial_id, :tutorial_version, :title, :problem, :prerequisites,
   :steps, :expected_outcome, :reason, :supersedes_version, :created_at)
"""

MARK_OUTDATED = "UPDATE Tutorial SET is_possibly_outdated = 1 WHERE tutorial_id = :tutorial_id"

APPLY_UPDATE = """
UPDATE Tutorial
SET current_version = :new_version, is_possibly_outdated = 0, last_action = 'UPDATE'
WHERE tutorial_id = :tutorial_id
"""

APPLY_RETIRE = """
UPDATE Tutorial
SET status = 'retired', is_obsolete = 1, is_possibly_outdated = 0, last_action = 'RETIRE'
WHERE tutorial_id = :tutorial_id
"""

FEATURE_RENAME = "UPDATE Feature SET name = :name WHERE id = :feature_id"
FEATURE_SET_STATUS = "UPDATE Feature SET status = :status WHERE id = :feature_id"
MARK_RELEASE_PROCESSED = "UPDATE Release SET processed_at = :now WHERE id = :release_id"

FIVE_FIELDS = ("title", "problem", "prerequisites", "steps", "expected_outcome")

# --- 規則式擷取（降級用，只認 demo 劇本的五種句型） ---

PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^(?P<from>.+?)\s+has been renamed to\s+(?P<to>.+?)\.?$", re.I), "renamed"),
    (re.compile(r"^(?P<name>.+?)\s+has been deprecated\.?$", re.I), "deprecated"),
    (re.compile(r"^(?P<name>.+?)\s+has been removed\.?$", re.I), "removed"),
    (re.compile(r"^(?P<name>.+?)\s+is a new feature\.?$", re.I), "new"),
    (re.compile(r"^(?P<name>.+?)\s+has(?: been)? changed\.?$", re.I), "changed"),
]

EXTRACT_SCHEMA = (
    '{"changes": [{"feature_name": "", "change_type": '
    '"new|changed|renamed|deprecated|removed", "from_name": "", "to_name": ""}]}'
)

REWRITE_SCHEMA = '{"title": "", "problem": "", "prerequisites": "", "steps": "", "expected_outcome": ""}'


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- 擷取產品變更 ---


def _extract_by_regex(content: str) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        for pattern, change_type in PATTERNS:
            m = pattern.match(line)
            if not m:
                continue
            groups = m.groupdict()
            if change_type == "renamed":
                changes.append(
                    {
                        "feature_name": groups["from"].strip(),
                        "change_type": "renamed",
                        "from_name": groups["from"].strip(),
                        "to_name": groups["to"].strip(),
                        "source": "rule",
                    }
                )
            else:
                changes.append(
                    {
                        "feature_name": groups["name"].strip(),
                        "change_type": change_type,
                        "from_name": "",
                        "to_name": "",
                        "source": "rule",
                    }
                )
            break
    return changes


def _normalise(raw: dict[str, Any], source: str) -> dict[str, Any]:
    return {
        "feature_name": (raw.get("feature_name") or "").strip(),
        "change_type": (raw.get("change_type") or "").strip().lower(),
        "from_name": (raw.get("from_name") or "").strip(),
        "to_name": (raw.get("to_name") or "").strip(),
        "source": source,
    }


def extract_changes(content: str) -> list[dict[str, Any]]:
    """從 Release Note 本文擷取產品變更清單。

    先試 LLM，`LLMUnavailable`／回覆不合用時改走 regex 規則式。
    擷取不到任何 change_type 時 `OperationFailed`（規格 `Then 操作失敗`）——降級不改變失敗語意。
    """
    changes: list[dict[str, Any]] = []
    prompt = (
        "你是產品 Release Note 擷取器。只輸出一個 JSON 物件，不要任何解釋、不要 markdown code fence。\n\n"
        f"Release Note 本文：\n{content}\n\n"
        "規則：\n"
        "- change_type 只能是 new / changed / renamed / deprecated / removed 其中之一。\n"
        "- 更名時 feature_name 填舊名稱，from_name 填舊名、to_name 填新名；其餘一律空字串。\n"
        "- 本文沒寫的變更不得臆測；判斷不出 change_type 時輸出空字串。"
    )
    try:
        data = llm.complete_json(prompt, EXTRACT_SCHEMA)
        raw = data.get("changes") if isinstance(data, dict) else data
        if isinstance(raw, dict):
            raw = [raw]
        for item in raw or []:
            change = _normalise(item, "llm")
            if change["change_type"]:
                changes.append(change)
    except Exception:  # noqa: BLE001 - LLMUnavailable 或任何回覆異常都走規則式降級
        changes = []

    if not changes:
        changes = _extract_by_regex(content)

    if not changes:
        raise OperationFailed(f"擷取不到 change_type：{content}")
    return changes


# --- 改寫五欄 ---


def _rewrite_fields(version: dict[str, Any], change: dict[str, Any]) -> dict[str, str]:
    """把舊功能名稱換成新名稱，其餘不動；LLM 失敗時做字面替換。"""
    old = {field: (version.get(field) or "") for field in FIVE_FIELDS}
    from_name, to_name = change["from_name"], change["to_name"]

    if from_name and to_name:
        prompt = (
            "你是教學文件維護器。把下面這篇教學裡的舊功能名稱換成新名稱，其餘一字不改。\n\n"
            f"舊名稱：{from_name}\n新名稱：{to_name}\n\n"
            f"目前版本內容（JSON）：\n{old}\n\n"
            "規則：不得新增或刪除任何步驟，不得改寫語氣或重排順序；"
            '只替換功能名稱字面（含被引號包住的按鈕名，例如 Click "Cancel Order"）。'
        )
        try:
            data = llm.complete_json(prompt, REWRITE_SCHEMA)
            new = {field: (data.get(field) or "").strip() for field in FIVE_FIELDS}
            if new["steps"]:
                return new
        except Exception:  # noqa: BLE001 - 降級到字面替換
            pass
        return {field: value.replace(from_name, to_name) for field, value in old.items()}

    # change_type = changed：規格沒給替換對象，內容原樣帶到新版本（只記 reason）
    return old


# --- Tutorial 檔案 ---


def render_markdown(fields: dict[str, str], version: str) -> str:
    """五欄 → `.md` 版型（與 Phase 2 的 writer 同型）。"""
    return (
        f"# {fields.get('title', '')}\n\n"
        f"## Problem\n{fields.get('problem', '')}\n\n"
        f"## Prerequisites\n{fields.get('prerequisites', '')}\n\n"
        f"## Steps\n{fields.get('steps', '')}\n\n"
        f"## Expected Outcome\n{fields.get('expected_outcome', '')}\n\n"
        f"<!-- version: {version} -->\n"
    )


def _write_markdown(path: str, fields: dict[str, str], version: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_markdown(fields, version), encoding="utf-8")


# --- 主流程 ---


def process_unprocessed_releases(
    db,
    cognee=None,
    hydra=None,
    now: Optional[str] = None,
) -> list[dict[str, Any]]:
    """處理所有 processed_at 為空的 Release，回傳決定的動作清單。

    一列失敗（擷取不到 change_type）不影響其他列：該列 `processed_at` 保持空、下輪可重跑；
    全部跑完後若有失敗的列才 `OperationFailed`。
    """
    now = now or _now()
    releases = db.run_sql(UNPROCESSED_RELEASES)  # Rule 10：有 processed_at 的撈不到
    decisions: list[dict[str, Any]] = []
    failed: list[str] = []

    for rel in releases:
        try:
            decisions += _process_one(db, rel, now, cognee, hydra)
        except OperationFailed as exc:
            failed.append(f"release_id={rel['id']}：{exc}")

    if failed:
        raise OperationFailed("操作失敗：" + "；".join(failed))
    return decisions


def _process_one(db, rel: dict, now: str, cognee, hydra) -> list[dict[str, Any]]:
    changes = extract_changes(rel["content"])  # 失敗 → processed_at 保持空
    features = db.run_sql(ALL_FEATURES)
    results: list[dict[str, Any]] = []

    for change in changes:
        action = rules.decide_release_action(change["change_type"])  # Rule 6/7/8
        feature = _match_feature(change, features)
        if feature is None:  # Rule 9：對不到既有 Feature 就不新建
            continue

        db.execute(  # Rule 4
            INSERT_RELEASE_FEATURE_CHANGE,
            {
                "release_id": rel["id"],
                "feature_id": feature["id"],
                "change_type": change["change_type"],
                "from_name": change["from_name"],
                "to_name": change["to_name"],
            },
        )
        _remember_edge(hydra, rel, feature, change)

        for tut in _affected_tutorials(db, rel["id"], feature["id"], hydra):  # Rule 5
            if action == "UPDATE":
                _apply_update(db, tut, feature, rel, change, now, cognee, hydra)
            elif action == "RETIRE":
                _apply_retire(db, tut, feature, change)
            else:  # new：不決定動作（Rule 8）
                continue
            results.append({"release_id": rel["id"], "tutorial_id": tut["tutorial_id"], "action": action})

    db.execute(MARK_RELEASE_PROCESSED, {"release_id": rel["id"], "now": now})
    return results


def _match_feature(change: dict[str, Any], features: list[dict]) -> Optional[dict]:
    """以 feature_name 或 from_name 逐字比對既有 Feature；對不到回 None（不新建）。"""
    wanted = [n for n in (change["feature_name"], change["from_name"]) if n]
    for name in wanted:
        for feature in features:
            if (feature["name"] or "").strip().lower() == name.lower():
                return feature
    return None


def _affected_tutorials(db, release_id: int, feature_id: int, hydra) -> list[dict]:
    """多跳查受影響 Tutorial；hydra 為 None 或失敗時降級成 SQL `feature_id` 命中。"""
    ids: list[int] = []
    if hydra is not None:
        try:
            ids = _tutorial_ids(hydra.affected_tutorials_by_release(release_id))
        except Exception:  # noqa: BLE001 - 圖譜降級
            ids = []

    rows = db.run_sql(TUTORIALS_BY_FEATURE, {"feature_id": feature_id})
    if ids:
        rows = [r for r in rows if r["tutorial_id"] in ids]
    return rows


def _apply_update(db, tut: dict, feature: dict, rel: dict, change: dict, now: str, cognee, hydra) -> None:
    tutorial_id = tut["tutorial_id"]
    old_version = tut["current_version"]
    db.execute(MARK_OUTDATED, {"tutorial_id": tutorial_id})  # 處理中先標

    rows = db.run_sql(VERSION_ROW, {"tutorial_id": tutorial_id, "tutorial_version": old_version})
    if not rows:
        raise OperationFailed(f"找不到 current_version：tutorial_id={tutorial_id}, {old_version}")

    fields = _rewrite_fields(rows[0], change)
    if not fields.get("steps"):
        raise OperationFailed(f"改寫後 steps 為空：tutorial_id={tutorial_id}")

    new_version = rules.next_version(old_version)
    db.execute(
        INSERT_VERSION,
        {
            "tutorial_id": tutorial_id,
            "tutorial_version": new_version,
            **fields,
            "reason": f"Release: {rel['content']}",
            "supersedes_version": old_version,
            "created_at": now,
        },
    )
    db.execute(APPLY_UPDATE, {"tutorial_id": tutorial_id, "new_version": new_version})

    if change["change_type"] == "renamed" and change["to_name"]:
        db.execute(FEATURE_RENAME, {"feature_id": feature["id"], "name": change["to_name"]})

    _write_markdown(tut["path"], fields, new_version)
    _remember_version(cognee, hydra, tutorial_id, new_version, old_version, fields)


def _apply_retire(db, tut: dict, feature: dict, change: dict) -> None:
    db.execute(APPLY_RETIRE, {"tutorial_id": tut["tutorial_id"]})
    db.execute(FEATURE_SET_STATUS, {"feature_id": feature["id"], "status": change["change_type"]})
    # `.md` 不動、`current_version` 不動、不產新版本（規格沒寫，不腦補）


# --- 記憶層（失敗都吞掉，不影響 Then 表） ---


def _tutorial_ids(raw) -> list[int]:
    """把 hydra 多跳結果轉成 tutorial_id 清單（dict 或 int 都吃）。"""
    ids: list[int] = []
    for item in raw or []:
        value = item.get("tutorial_id") if isinstance(item, dict) else item
        if value is not None:
            try:
                ids.append(int(value))
            except (TypeError, ValueError):
                continue
    return ids


def _remember_edge(hydra, rel: dict, feature: dict, change: dict) -> None:
    """(Release)-[:changes]->(Feature)。Feature 節點的 key 在各 phase 不一致
    （seed 用 {"name": …}、create_tutorial 用 id），兩種都寫一條邊讓多跳接得上。"""
    if hydra is None:
        return
    props = {
        "content": rel["content"],
        "created_at": rel["created_at"],
        "change_type": change["change_type"],
    }
    for feature_key in ({"name": feature["name"]}, feature["id"]):
        try:
            hydra.upsert_node("Release", {"id": rel["id"]}, props)
            hydra.upsert_edge("Release", {"id": rel["id"]}, "changes", "Feature", feature_key)
        except Exception:  # noqa: BLE001 - 圖譜降級
            continue


def _remember_version(cognee, hydra, tutorial_id: int, new_version: str, old_version: str, fields: dict) -> None:
    markdown = render_markdown(fields, new_version)
    if cognee is not None:
        try:
            cognee.remember(markdown, "tutorial", {"tutorial_id": tutorial_id, "version": new_version})
        except TypeError:  # 舊簽章只吃一個參數
            try:
                cognee.remember(markdown)
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001
            pass
    if hydra is not None:
        try:
            key_new = f"{tutorial_id}:{new_version}"
            key_old = f"{tutorial_id}:{old_version}"
            hydra.upsert_node("TutorialVersion", key_new, {"tutorial_id": tutorial_id, "version": new_version})
            hydra.upsert_edge("TutorialVersion", key_new, "supersedes", "TutorialVersion", key_old)
        except Exception:  # noqa: BLE001
            pass
