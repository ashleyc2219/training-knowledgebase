"""Periodic Feedback Review pipeline：REFINE 或 KEEP（Phase 4）。

對齊 `docs/spec/features/定期優化Tutorial.feature` 的 10 條 Rule 與 `docs/design/showme.md` §7.4。
門檻只在 `app/agent/rules.py`；本檔負責查數字、叫 LLM（不通就走模板）、寫版本鏈與 `.md`。

寫入順序不可換：驗五欄 → 寫 TutorialVersion → 改 Tutorial → 寫 `.md` → 記憶層。
任一步在「改 Tutorial」之前失敗，`current_version` 仍指向舊版，不會出現半篇教學。

CLI（🖐️ 手動觸發一輪 Review）：
    uv run python -m app.agent.feedback_review
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.agent import llm
from app.agent.rules import decide_review_action, next_version
from app.analytics.sql import AVG_RATING_CURRENT_VERSION, SAME_CATEGORY_MAX
from app.errors import OperationFailed

FIVE_FIELDS = ("title", "problem", "prerequisites", "steps", "expected_outcome")

TEMPLATE_REASON = "Repeated feedback indicates Step 3 lacks context."
"""模板降級用的固定 reason（規格 Example 的 v2 reason）。"""

PUBLISHED_TUTORIALS = """
SELECT tutorial_id, path, status, current_version, is_possibly_outdated, is_obsolete, last_action
FROM Tutorial
WHERE status = 'published'
ORDER BY tutorial_id
"""

CURRENT_VERSION_ROW = """
SELECT * FROM TutorialVersion
WHERE tutorial_id = :tutorial_id AND tutorial_version = :tutorial_version
"""

CURRENT_VERSION_FEEDBACK = """
SELECT f.rating AS rating, f.feedback_category AS feedback_category, f.comment AS comment
FROM Feedback f
JOIN Tutorial t
  ON t.tutorial_id = f.tutorial_id
 AND t.current_version = f.tutorial_version
WHERE f.tutorial_id = :tutorial_id
ORDER BY f.id
"""

INSERT_VERSION = """
INSERT INTO TutorialVersion
    (tutorial_id, tutorial_version, title, problem, prerequisites, steps, expected_outcome,
     reason, supersedes_version, created_at)
VALUES
    (:tutorial_id, :tutorial_version, :title, :problem, :prerequisites, :steps, :expected_outcome,
     :reason, :supersedes_version, :created_at)
"""

UPDATE_TUTORIAL = """
UPDATE Tutorial SET current_version = :tutorial_version, last_action = :last_action
WHERE tutorial_id = :tutorial_id
"""

UPDATE_LAST_ACTION = "UPDATE Tutorial SET last_action = :last_action WHERE tutorial_id = :tutorial_id"


# --- 對外入口 ---


def review_all(db, cognee=None, hydra=None) -> list[dict]:
    """掃每一篇 published Tutorial，回傳每篇的決策。retired 不進 Review。"""
    return [_review_one(db, row, cognee, hydra) for row in db.run_sql(PUBLISHED_TUTORIALS)]


def _review_one(db, tut: dict, cognee=None, hydra=None) -> dict:
    tutorial_id = tut["tutorial_id"]
    current = tut["current_version"]
    outdated = bool(tut.get("is_possibly_outdated"))

    avg, count = _avg_and_count(db, tutorial_id)
    max_same = _max_same_category(db, tutorial_id)
    action = decide_review_action(avg, count, max_same, outdated)

    if action == "KEEP":
        db.execute(UPDATE_LAST_ACTION, {"last_action": "KEEP", "tutorial_id": tutorial_id})
        why = "is_possibly_outdated" if outdated else f"avg={avg} count={count} same_cat={max_same}"
        return {
            "tutorial_id": tutorial_id,
            "action": "KEEP",
            "from_version": current,
            "to_version": current,
            "reason": why,
            "source": "rules",
        }

    return _refine(db, tut, avg, count, max_same, cognee, hydra)


# --- 查數字（只算 current_version） ---


def _avg_and_count(db, tutorial_id: int) -> tuple[float, int]:
    rows = db.run_sql(AVG_RATING_CURRENT_VERSION, {"tutorial_id": tutorial_id})
    if not rows:
        return 0.0, 0
    return float(rows[0].get("avg_rating") or 0.0), int(rows[0].get("feedback_count") or 0)


def _max_same_category(db, tutorial_id: int) -> int:
    """同一 feedback_category 的最大筆數；空字串不算 recurring complaint。"""
    rows = db.run_sql(SAME_CATEGORY_MAX, {"tutorial_id": tutorial_id})
    return int(rows[0]["category_count"]) if rows else 0


# --- REFINE ---


def _refine(db, tut: dict, avg: float, count: int, max_same: int, cognee, hydra) -> dict:
    tutorial_id = tut["tutorial_id"]
    current = tut["current_version"]

    old_rows = db.run_sql(
        CURRENT_VERSION_ROW, {"tutorial_id": tutorial_id, "tutorial_version": current}
    )
    if not old_rows:
        raise OperationFailed(f"找不到 TutorialVersion({tutorial_id}, {current})")
    old = old_rows[0]
    feedback = db.run_sql(CURRENT_VERSION_FEEDBACK, {"tutorial_id": tutorial_id})

    try:
        new = llm.complete_json(
            _prompt(old, current, feedback, avg, count, max_same),
            '{"title": "...", "problem": "...", "prerequisites": "...", "steps": "...",'
            ' "expected_outcome": "...", "reason": "..."}',
        )
        source = "llm"
    except llm.LLMUnavailable:
        new = _template_refine(old)
        source = "template"

    missing = [f for f in FIVE_FIELDS if not str(new.get(f) or "").strip()]
    if missing:
        raise OperationFailed(f"REFINE 產出缺欄位 {missing}，不寫半篇 Tutorial")

    nxt = next_version(current)
    row = {
        "tutorial_id": tutorial_id,
        "tutorial_version": nxt,
        **{f: str(new[f]).strip() for f in FIVE_FIELDS},
        "reason": str(new.get("reason") or TEMPLATE_REASON).strip(),
        "supersedes_version": current,
        "created_at": _now(),
    }
    db.execute(INSERT_VERSION, row)
    db.execute(
        UPDATE_TUTORIAL,
        {"tutorial_version": nxt, "last_action": "REFINE", "tutorial_id": tutorial_id},
    )
    _write_markdown(tut.get("path"), row)

    warning = _remember(cognee, hydra, tutorial_id, current, nxt, row)

    return {
        "tutorial_id": tutorial_id,
        "action": "REFINE",
        "from_version": current,
        "to_version": nxt,
        "reason": row["reason"],
        "source": source,
        "path": tut.get("path"),
        "old_steps": old["steps"],
        "new_steps": row["steps"],
        "warning": warning,
    }


def _prompt(old: dict, current: str, feedback: list[dict], avg: float, count: int,
            max_same: int) -> str:
    lines = "\n".join(
        f"- rating={f['rating']} category={f['feedback_category']} comment={f['comment']}"
        for f in feedback
    )
    return f"""你是技術文件編輯。以下是一篇客服自助教學的目前版本，以及顧客對這一版的回饋。
請只針對回饋指出的問題改寫，不要重寫整篇、不要新增回饋沒有提到的步驟、不要改變步驟數量。

[current version {current}]
title: {old['title']}
problem: {old['problem']}
prerequisites: {old['prerequisites']}
steps: {old['steps']}
expected_outcome: {old['expected_outcome']}

[feedback on {current}]（avg={avg}，共 {count} 筆；同一 category 最多 {max_same} 筆）
{lines}

只輸出一個 JSON 物件，不要 markdown 圍欄、不要任何其他文字：
{{"title": "...", "problem": "...", "prerequisites": "...", "steps": "...",
 "expected_outcome": "...", "reason": "一句英文，說明為什麼產生這一版"}}"""


def _template_refine(old: dict) -> dict:
    """LLM 不可用時的本機模板改寫（showme §17 降級；流程與門檻不變）。

    規則固定：在含有 `Click "X"` 的那一步後面補一句定位說明，Prerequisites 補 Screenshots 一句。
    """
    steps = str(old["steps"])
    match = re.search(r'[Cc]lick "([^"]+)"', steps)
    if match:
        label = match.group(1)
        end = match.end()
        if steps[end : end + 1] == ".":
            end += 1
        addition = (
            f" On the order details page, locate the {label} button beside the order status"
            " before clicking it."
        )
        steps = steps[:end] + addition + steps[end:]
    else:
        steps = steps.rstrip() + " Follow the labels exactly as they appear on screen."

    prerequisites = str(old["prerequisites"])
    if "Screenshots" not in prerequisites:
        prerequisites = prerequisites.rstrip() + " Screenshots: see the product UI for each step."

    return {
        "title": old["title"],
        "problem": old["problem"],
        "prerequisites": prerequisites,
        "steps": steps,
        "expected_outcome": old["expected_outcome"],
        "reason": TEMPLATE_REASON,
    }


# --- 寫檔與記憶層 ---


def render_markdown(version_row: dict) -> str:
    """五欄 → `.md`。`Steps` 只是渲染，DB 的 steps 字串一個字都不改。"""
    steps = [s.strip() for s in re.split(r"(?=\b\d+\.\s)", str(version_row["steps"])) if s.strip()]
    body = "\n".join(steps)
    return (
        f"# {version_row['title']}\n\n"
        f"## Problem\n\n{version_row['problem']}\n\n"
        f"## Prerequisites\n\n{version_row['prerequisites']}\n\n"
        f"## Steps\n\n{body}\n\n"
        f"## Expected Outcome\n\n{version_row['expected_outcome']}\n\n"
        f"<!-- version: {version_row['tutorial_version']} -->\n"
    )


def _write_markdown(path: Optional[str], version_row: dict) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_markdown(version_row), encoding="utf-8")


def _remember(cognee, hydra, tutorial_id: int, old_version: str, new_version: str,
              row: dict) -> str:
    """記憶層失敗只回 warning，不回滾已寫的列（showme §17）。"""
    try:
        if cognee is not None:
            cognee.remember(render_markdown(row))
        if hydra is not None:
            hydra.upsert_edge(
                "TutorialVersion", f"{tutorial_id}:{new_version}",
                "supersedes",
                "TutorialVersion", f"{tutorial_id}:{old_version}",
            )
    except Exception as exc:  # noqa: BLE001 - demo 降級：圖譜未同步不擋主流程
        return f"圖譜未同步：{exc}"
    return ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def main() -> None:  # pragma: no cover - CLI
    """`python -m app.agent.feedback_review`：跑一輪 Review 並存一個指標點。"""
    from app.analytics import metrics
    from app.analytics.db import get_db

    db = get_db()
    results = review_all(db)
    refined = 0
    for r in results:
        if r["action"] == "REFINE":
            refined += 1
            print(f"[REFINE] tutorial {r['tutorial_id']}: {r['from_version']} -> "
                  f"{r['to_version']}  reason={r['reason']}（{r['source']}）")
            if r.get("path"):
                print(f"         {r['path']} 已重寫")
            if r.get("warning"):
                print(f"         ! {r['warning']}")
        else:
            print(f"[KEEP]   tutorial {r['tutorial_id']}: {r['reason']}")
    print(f"Review 完成：{refined} 篇 REFINE、{len(results) - refined} 篇 KEEP")
    metrics.append_history(metrics.snapshot(db))


if __name__ == "__main__":  # pragma: no cover - CLI
    main()
