"""建立 Tutorial v1：LLM（或模板降級）產五欄 → Tutorial / TutorialVersion → tutorials/<slug>.md。

對齊 `docs/spec/features/建立Tutorial.feature`（五條 Rule）：
  Rule 1 有 Knowledge Gap 才建立；建立成功即 published / v1 / last_action = CREATE
  Rule 2 v1 五欄必填、reason 與 supersedes_version 為空
  Rule 3 五欄缺任一 → 操作失敗（不寫半篇）
  Rule 4 未識別出 Knowledge Gap → 操作失敗
  Rule 5 沒有對應 Feature → 操作失敗

成功邊界（showme §9）：兩表 ＋ .md 同進同退；寫檔失敗要把剛寫的列刪掉。
記憶層（Cognee / HydraDB）是 best-effort，不通只寫 hotdata（showme §17）。
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.agent import analysis, llm, rules
from app.errors import OperationFailed

FIVE_FIELDS = ("title", "problem", "prerequisites", "steps", "expected_outcome")

SCHEMA_HINT = (
    '{"title": string, "problem": string, "prerequisites": string, '
    '"steps": string, "expected_outcome": string}'
)

SYSTEM_RULES = """You are a technical writer for a customer-support self-service knowledge base.
You turn already-resolved support tickets into ONE short tutorial.

Return ONLY a JSON object, nothing else. No markdown fence, no commentary.
Schema:
{"title": string, "problem": string, "prerequisites": string, "steps": string, "expected_outcome": string}

Hard rules:
- All five fields are REQUIRED and must be non-empty strings.
- "steps" MUST be one single string of numbered steps separated by spaces, e.g.
  "1. Open Orders. 2. Select the order. 3. Click \\"Cancel Order\\"."
- Quote UI labels EXACTLY as they appear in the tickets, in double quotes.
  Do not paraphrase a button name.
- Do not invent product features, screens, or policies that are not in the tickets.
- Write in English. Keep the whole tutorial under 150 words."""

SELECT_USER_PROBLEM = "SELECT id, topic, feature_id FROM UserProblem WHERE id = :id"
SELECT_FEATURE = "SELECT id, name, status FROM Feature WHERE id = :id"

SELECT_MAJORITY_FEATURE = """
SELECT feature_id, COUNT(*) AS n
FROM Ticket
WHERE user_problem_id = :user_problem_id AND feature_id IS NOT NULL
GROUP BY feature_id
ORDER BY n DESC
LIMIT 1
"""

SELECT_RESOLUTION_MATERIAL = """
SELECT id, content, resolution_steps
FROM Ticket
WHERE user_problem_id = :user_problem_id
  AND status IN ('escalated', 'resolved')
  AND resolution_steps IS NOT NULL
  AND resolution_steps <> ''
ORDER BY id
"""

INSERT_TUTORIAL = """
INSERT INTO Tutorial (feature_id, user_problem_id, path, status, current_version,
                      is_possibly_outdated, is_obsolete, last_action)
VALUES (:feature_id, :user_problem_id, :path, 'published', 'v1', 0, 0, 'CREATE')
"""

INSERT_TUTORIAL_VERSION_V1 = """
INSERT INTO TutorialVersion (tutorial_id, tutorial_version, title, problem, prerequisites,
                             steps, expected_outcome, reason, supersedes_version, created_at)
VALUES (:tutorial_id, 'v1', :title, :problem, :prerequisites,
        :steps, :expected_outcome, '', '', :created_at)
"""


def _now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def create_tutorial(db, user_problem_id: int, cognee: Any = None, hydra: Any = None) -> dict:
    """為一個 Knowledge Gap 建立 Tutorial v1，回傳結果 dict。"""
    gaps = {g["user_problem_id"]: g for g in analysis.knowledge_gaps(db)}
    if user_problem_id not in gaps:
        raise OperationFailed(
            f"UserProblem {user_problem_id} 不是 Knowledge Gap，不建立 Tutorial"
        )
    topic = gaps[user_problem_id]["topic"]

    feature = _resolve_feature(db, user_problem_id)
    if feature is None:
        raise OperationFailed(
            f"UserProblem {user_problem_id} 沒有對應的 Feature，不建立 Tutorial"
        )

    try:
        tickets = db.run_sql(
            SELECT_RESOLUTION_MATERIAL, {"user_problem_id": user_problem_id}
        )
    except Exception as exc:  # noqa: BLE001
        raise OperationFailed(f"讀取 resolution_steps 失敗：{exc}") from exc
    if not tickets:
        raise OperationFailed("沒有可用的 resolution_steps，不建立 Tutorial")

    fields, source = _shape_five_fields(feature["name"], topic, tickets)

    missing = [f for f in FIVE_FIELDS if not str(fields.get(f) or "").strip()]
    if missing:
        raise OperationFailed(f"缺少內容欄位：{missing}，不寫半篇 Tutorial")
    fields = {f: str(fields[f]).strip() for f in FIVE_FIELDS}

    path = f"tutorials/{rules.tutorial_slug(topic)}.md"
    markdown = render_markdown(fields, "v1")
    md_file = Path(path)
    tutorial_id: Optional[int] = None
    try:
        tutorial_id = db.execute(
            INSERT_TUTORIAL,
            {
                "feature_id": feature["id"],
                "user_problem_id": user_problem_id,
                "path": path,
            },
        )
        if not tutorial_id:  # hotdata backend 不回 lastrowid
            tutorial_id = db.run_sql(
                "SELECT MAX(tutorial_id) AS id FROM Tutorial"
            )[0]["id"]
        db.execute(
            INSERT_TUTORIAL_VERSION_V1,
            {"tutorial_id": tutorial_id, "created_at": _now(), **fields},
        )
        md_file.parent.mkdir(parents=True, exist_ok=True)
        md_file.write_text(markdown, encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 — 兩表與 .md 同一成功邊界
        _rollback(db, tutorial_id, md_file)
        raise OperationFailed(f"建立 Tutorial 失敗，已回滾：{exc}") from exc

    remembered = _remember_best_effort(
        cognee, hydra, tutorial_id, feature, topic, fields, markdown
    )

    return {
        "tutorial_id": tutorial_id,
        "user_problem_id": user_problem_id,
        "topic": topic,
        "feature_id": feature["id"],
        "path": path,
        "version": "v1",
        "status": "published",
        "last_action": "CREATE",
        "source": source,
        "fields": fields,
        "memory": remembered,
    }


def _rollback(db, tutorial_id: Optional[int], md_file: Path) -> None:
    """把已寫的列與半檔清掉（沒有交易可用時的最小補償）。"""
    if tutorial_id:
        for sql in (
            "DELETE FROM TutorialVersion WHERE tutorial_id = :id",
            "DELETE FROM Tutorial WHERE tutorial_id = :id",
        ):
            try:
                db.execute(sql, {"id": tutorial_id})
            except Exception:  # noqa: BLE001
                pass
    try:
        md_file.unlink(missing_ok=True)
    except OSError:
        pass


def _resolve_feature(db, user_problem_id: int) -> Optional[dict]:
    """UserProblem.feature_id → 否則票的多數 feature_id；Feature 表查無此列則回 None。"""
    try:
        rows = db.run_sql(SELECT_USER_PROBLEM, {"id": user_problem_id})
        feature_id = rows[0]["feature_id"] if rows else None
        if not feature_id:
            majority = db.run_sql(
                SELECT_MAJORITY_FEATURE, {"user_problem_id": user_problem_id}
            )
            feature_id = majority[0]["feature_id"] if majority else None
        if not feature_id:
            return None
        found = db.run_sql(SELECT_FEATURE, {"id": feature_id})
    except Exception as exc:  # noqa: BLE001
        raise OperationFailed(f"讀取 Feature 失敗：{exc}") from exc
    return found[0] if found else None


def _shape_five_fields(feature_name: str, topic: str, tickets: list[dict]) -> tuple[dict, str]:
    """LLM 成型五欄；LLM 不可用時走模板降級（結果標 source="template"）。"""
    try:
        fields = llm.complete_json(build_prompt(feature_name, topic, tickets), SCHEMA_HINT)
    except llm.LLMUnavailable:
        return template_fields(feature_name, topic, tickets), "template"
    except Exception:  # noqa: BLE001 — LLM 回傳壞掉也走模板降級（demo 韌性）
        return template_fields(feature_name, topic, tickets), "template"
    if not isinstance(fields, dict):
        raise OperationFailed(f"LLM 回傳形狀不對：{type(fields).__name__}")
    if fields.get("error"):
        raise OperationFailed(f"LLM 無法產生五欄：{fields['error']}")
    return fields, "llm"


def build_prompt(feature_name: str, topic: str, tickets: list[dict]) -> str:
    """寫死的 prompt 範本（system 規則 ＋ 已解決票素材）。"""
    parts = [SYSTEM_RULES, "", f"Feature: {feature_name}", f"User problem topic: {topic}", "",
             f"Resolved tickets ({len(tickets)}):"]
    for t in tickets:
        parts += [
            f"--- ticket {t['id']} ---",
            f"customer said: {t.get('content', '')}",
            f"support resolved with: {t.get('resolution_steps', '')}",
        ]
    parts += ["", "Produce the tutorial JSON now."]
    return "\n".join(parts)


# Bitext response 開頭常是客服寒暄（"I've understood…"、"Thank you…"），拿來當步驟會很怪
_CHITCHAT = ("i ", "i'm", "i've", "i'd", "thank", "sure", "of course", "no problem", "we ", "your satisfaction")


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", (text or "").strip()) if s.strip()]


def _instruction_sentences(text: str) -> list[str]:
    """只留像「操作指示」的句子：不是寒暄、長度適中。"""
    out = [
        s
        for s in _sentences(text)
        if len(s) <= 160 and not s.lower().startswith(_CHITCHAT)
    ]
    return out or _sentences(text)


def template_fields(feature_name: str, topic: str, tickets: list[dict]) -> dict:
    """模板降級：把 resolution_steps 切句成 steps，Step 3 固定為 Click "<按鈕>"。

    cancel_order 的 Step 3 必須是 `Click "Cancel Order"`（demo 貫穿）；其他 topic 用 Feature.name。
    """
    material = _instruction_sentences(tickets[0].get("resolution_steps", "")) if tickets else []
    button = "Cancel Order" if topic == "cancel_order" else feature_name
    body = [s for s in material if button.lower() not in s.lower()]

    steps = [
        f"Open the {feature_name} page.",
        body[0] if body else f"Find the item you want to handle with {feature_name}.",
        f'Click "{button}".',
    ]
    if len(body) > 1:
        steps.append(body[1])

    numbered = " ".join(
        f"{i}. {s if s.endswith(('.', '!', '?')) else s + '.'}"
        for i, s in enumerate(steps, start=1)
    )
    problem = (
        f'Customer needs help with {topic.replace("_", " ")}: "{tickets[0].get("content", "")}"'
        if tickets
        else f"Customer needs help with {topic.replace('_', ' ')}."
    )
    return {
        "title": feature_name,
        "problem": problem,
        "prerequisites": "Customer is signed in and can open the order or request in question.",
        "steps": numbered,
        "expected_outcome": f"The {feature_name} request is completed and confirmed to the customer.",
    }


def render_markdown(fields: dict, version: str) -> str:
    """tutorials/<slug>.md 版型（頁尾標版本，Phase 5 的 Step diff 拿它當基準）。"""
    steps_lines = [s for s in re.split(r"\s+(?=\d+\.\s)", fields["steps"].strip()) if s]
    return (
        f"# {fields['title']}\n\n"
        f"## Problem\n{fields['problem']}\n\n"
        f"## Prerequisites\n{fields['prerequisites']}\n\n"
        f"## Steps\n" + "\n".join(steps_lines) + "\n\n"
        f"## Expected Outcome\n{fields['expected_outcome']}\n\n"
        f"<!-- version: {version} -->\n"
    )


def _remember_best_effort(
    cognee: Any, hydra: Any, tutorial_id: int, feature: dict, topic: str,
    fields: dict, markdown: str,
) -> dict:
    """Cognee remember ＋ HydraDB 節點與 explains 邊；失敗只記 warning，不回滾。"""
    out: dict[str, Any] = {"cognee": "skipped", "hydra": "skipped"}
    if cognee is not None:
        try:
            cognee.remember(markdown)
            out["cognee"] = "ok"
        except Exception as exc:  # noqa: BLE001
            out["cognee"] = f"failed: {exc}"
    if hydra is not None:
        try:
            hydra.upsert_node(
                "Tutorial",
                tutorial_id,
                {
                    "tutorial_id": tutorial_id,
                    "user_problem_id": user_problem_id,
                    "topic": topic,
                    "version": "v1",
                    "title": fields["title"],
                    "status": "published",
                },
            )
            out["hydra"] = "ok"
        except Exception as exc:  # noqa: BLE001
            out["hydra"] = f"failed: {exc}"
        try:
            hydra.upsert_edge("Tutorial", tutorial_id, "explains", "Feature", feature["id"])
        except Exception as exc:  # noqa: BLE001
            out["hydra_edge"] = f"failed: {exc}"
    return out
