"""Demo 彩排：sqlite 模式一鍵走完六步，每步印「評審看到什麼」與耗時。

用法：
    uv run python scripts/demo_rehearsal.py            # 先重置再全跑
    uv run python scripts/demo_rehearsal.py --no-reset # 接著現有資料往下跑

每一步都可能因為別的 phase 還沒完成而跳過；跳過會印「⚠️ 待 Phase N」，
不中斷後面的步驟（彩排本身就是拿來找哪一段還沒接上的）。
"""

from __future__ import annotations

import argparse
import sys
import time
import traceback
from pathlib import Path

from app.analytics import metrics
from app.analytics.local_db import LocalDB

CANCEL_ORDER_MD = Path("tutorials/cancel-order.md")
V1_SEED = Path("data/seed/feedback_seed.json")
V2_SEED = Path("data/seed/feedback_v2_seed.json")
TOPIC = "cancel_order"  # demo 貫穿的 UserProblem.topic

_results: list[tuple[str, str, float]] = []


def step(title: str, expect: str):
    """裝飾器：印步驟標題、耗時、評審看到什麼；例外只記錄不中斷。"""

    def wrap(fn):
        def run(*args, **kwargs):
            print(f"\n{'=' * 72}\n▶ {title}\n{'=' * 72}")
            started = time.time()
            try:
                fn(*args, **kwargs)
                status = "OK"
            except Exception as exc:  # noqa: BLE001 - 彩排要看完整條線，不中斷
                status = f"跳過（{type(exc).__name__}: {exc}）"
                print(f"⚠️  {status}")
                traceback.print_exc(limit=1, file=sys.stdout)
            elapsed = time.time() - started
            print(f"👀 評審看到：{expect}")
            print(f"⏱  {elapsed:.1f}s｜{status}")
            _results.append((title, status, elapsed))

        return run

    return wrap


# --- 步驟 ---


@step("0 重置", "空畫面：9 表全空、tutorials/ 沒有 .md、.state/ 清掉")
def step_reset() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import reset_demo

    reset_demo.main()


@step("1 種子建圖", "每類 2 張 resolved 票、3 個 UserProblem、3 個 Feature 進 9 表與圖譜")
def step_seed(db: LocalDB) -> None:
    from app.ingest.seed import seed

    result = seed(db)
    print(f"   seed() → {result}")
    _print_counts(db, "Ticket", "UserProblem", "Feature")


@step("2 餵 3 張 cancel_order → 轉真人 → CREATE v1", "前兩張 escalated、第 3 張湊滿門檻 → tutorials/cancel-order.md v1 published")
def step_feed_and_create(db: LocalDB) -> None:
    from app.agent import analysis, create_tutorial, realtime
    from app.ingest.poll import bitext_response, feed_next_ticket

    for n in range(3):
        fed = feed_next_ticket(db)
        if fed is None:
            print(f"   劇本已餵完（第 {n + 1} 張）")
            break
        result = realtime.handle_open_ticket(db, fed["ticket_id"])
        print(f"   票 #{fed['ticket_id']}：{result.get('status')}｜{result.get('reason', '')}")
        if result.get("status") == "escalated":
            realtime.resolve_ticket(db, fed["ticket_id"], fed.get("bitext_response") or bitext_response(fed))

    actions = analysis.analyze_tickets(db)
    print(f"   analyze_tickets → {actions}")
    for action in actions:
        if action["action"] == "CREATE":
            created = create_tutorial.create_tutorial(db, action["user_problem_id"])
            print(f"   create_tutorial → tutorial_id={created.get('tutorial_id')} {created.get('path')}")
    _print_tutorials(db)


@step("3 第 4 張 cancel_order 票 → deflected ＋ Rote 捕捉", "中欄變 deflected 回教學連結；Workflow 一列，replay_count = 0")
def step_deflect(db: LocalDB) -> None:
    from app.agent import realtime
    from app.muscle import rote_client

    fed = _feed_topic_ticket(db, TOPIC, "bob@example.com")
    result = realtime.handle_open_ticket(db, fed["ticket_id"], rote=rote_client)
    print(f"   票 #{fed['ticket_id']}：{result.get('status')}｜{result.get('reason', '')}")
    _print_counts(db, "Workflow")
    print(f"   Workflow：{db.run_sql('SELECT id, user_problem_id, replay_count FROM Workflow')}")


@step("4 第 5 張 cancel_order 票 → 重放", "一樣 deflected，但走重放；replay_count = 1")
def step_replay(db: LocalDB) -> None:
    from app.agent import realtime
    from app.muscle import rote_client

    fed = _feed_topic_ticket(db, TOPIC, "carol@example.com")
    result = realtime.handle_open_ticket(db, fed["ticket_id"], rote=rote_client)
    print(f"   票 #{fed['ticket_id']}：{result.get('status')}")
    print(f"   Workflow：{db.run_sql('SELECT id, user_problem_id, replay_count FROM Workflow')}")


@step("5 Feedback 種子 → Review → REFINE v2", "v1 均分 2.9 → REFINE → v2；下欄均分曲線上揚")
def step_review(db: LocalDB) -> None:
    from app.agent.feedback_review import review_all
    from app.ingest.feedback import seed_feedback

    count = seed_feedback(db, V1_SEED)
    print(f"   匯入 v1 Feedback {count} 筆，均分 {metrics.avg_rating(db, 1):.2f}")
    decisions = review_all(db)
    print(f"   review_all → {decisions}")
    if V2_SEED.exists() and any(d.get("action") == "REFINE" for d in decisions):
        count2 = seed_feedback(db, V2_SEED)
        print(f"   匯入 v2 Feedback {count2} 筆，均分 {metrics.avg_rating(db, 1):.2f}")
    _print_tutorials(db)


@step("6 貼 Release Note → 入庫 → 處理 → UPDATE", 'Step 3 從 Click "Cancel Order" 變成 Click "Cancel Purchase"；Feature 改名；版本 +1')
def step_release(db: LocalDB) -> None:
    from app.agent.release_update import process_unprocessed_releases
    from app.ingest.changelog import ingest_release_text

    note = "Cancel Order has been renamed to Cancel Purchase."
    release_id = ingest_release_text(db, note, "2026-09-11T15:00:00Z")
    print(f"   入庫 Release #{release_id}（processed_at 為空）" if release_id else "   相同 Release 已存在，不新增列")

    decisions = process_unprocessed_releases(db)
    print(f"   process_unprocessed_releases → {decisions}")
    print(f"   Feature：{db.run_sql('SELECT id, name, status FROM Feature')}")
    _print_tutorials(db)

    again = process_unprocessed_releases(db)
    print(f"   再處理一次（冪等驗證）→ {again}（應為 []）")


@step("7 三條指標 ＋ Step 3", "deflection rate、重放解決率、圖譜覆蓋；cancel-order.md 的 Step 3 文字已變")
def step_metrics(db: LocalDB) -> None:
    print(f"   deflection rate：{metrics.deflection_rate(db):.2f}")
    print(f"   平均 rating（current_version）：{metrics.avg_rating(db, 1):.2f}")
    print(f"   重放解決率：{metrics.replay_rate(db):.2f}")
    print(f"   圖譜覆蓋：{metrics.coverage(db):.2f}")

    if CANCEL_ORDER_MD.exists():
        lines = CANCEL_ORDER_MD.read_text(encoding="utf-8").splitlines()
        hits = [line for line in lines if "Cancel Purchase" in line or "Cancel Order" in line]
        print(f"   {CANCEL_ORDER_MD}：")
        for line in hits[:8]:
            print(f"     {line}")
    else:
        print(f"   {CANCEL_ORDER_MD} 不存在（步驟 2 或 6 沒跑成）")


# --- 小工具 ---


def _feed_topic_ticket(db: LocalDB, topic: str, customer_ref: str) -> dict:
    """餵一張指定 topic 的 open 票。

    劇本 `data/script/demo_tickets.json` 是 3+3+3 分組（第 4、5 張是 track_refund），
    所以 deflect／重放這兩步拿不到「第 4 張同類票」。下一張剛好同 topic 就走劇本按鈕路徑，
    否則直接補一張同類 open 票（等同評審在左欄再貼一張同樣問題的票）。
    """
    from app.ingest.poll import feed_next_ticket, peek_next_ticket

    nxt = peek_next_ticket()
    if nxt and nxt.get("intent") == topic:
        return feed_next_ticket(db)

    rows = db.run_sql("SELECT id, feature_id FROM UserProblem WHERE topic = :topic", {"topic": topic})
    if not rows:
        raise RuntimeError(f"找不到 UserProblem topic={topic}（步驟 1 沒跑成？）")
    sample = db.run_sql(
        "SELECT content, category FROM Ticket WHERE user_problem_id = :id ORDER BY id LIMIT 1",
        {"id": rows[0]["id"]},
    )
    ticket_id = db.execute(
        """
        INSERT INTO Ticket (content, resolution_steps, category, customer_ref, feature_id,
                            user_problem_id, status, created_at)
        VALUES (:content, '', :category, :customer_ref, :feature_id, :user_problem_id, 'open', :created_at)
        """,
        {
            "content": sample[0]["content"] if sample else f"I need help with {topic}",
            "category": sample[0]["category"] if sample else "",
            "customer_ref": customer_ref,
            "feature_id": rows[0]["feature_id"],
            "user_problem_id": rows[0]["id"],
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
    )
    print(f"   （劇本沒有第 4 張 {topic}，補一張同類 open 票 #{ticket_id}）")
    return {"ticket_id": ticket_id}


def _print_counts(db: LocalDB, *tables: str) -> None:
    for table in tables:
        rows = db.run_sql(f"SELECT COUNT(*) AS c FROM {table}")
        print(f"   {table}：{rows[0]['c']} 列")


def _print_tutorials(db: LocalDB) -> None:
    rows = db.run_sql(
        "SELECT tutorial_id, path, status, current_version, is_possibly_outdated,"
        " is_obsolete, last_action FROM Tutorial ORDER BY tutorial_id"
    )
    for row in rows:
        print(f"   Tutorial #{row['tutorial_id']} {row['path']}｜{row['status']}｜{row['current_version']}｜{row['last_action']}")
    if not rows:
        print("   Tutorial：（空）")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Demo 彩排（sqlite 模式）")
    parser.add_argument("--no-reset", action="store_true", help="不重置，接著現有資料往下跑")
    args = parser.parse_args(argv)

    total_started = time.time()
    if not args.no_reset:
        step_reset()

    db = LocalDB()
    db.init_schema()

    step_seed(db)
    step_feed_and_create(db)
    step_deflect(db)
    step_replay(db)
    step_review(db)
    step_release(db)
    step_metrics(db)

    print(f"\n{'=' * 72}\n彩排總結\n{'=' * 72}")
    for title, status, elapsed in _results:
        mark = "✅" if status == "OK" else "⚠️ "
        print(f"{mark} {title}：{elapsed:.1f}s｜{status}")
    total = time.time() - total_started
    print(f"\n總耗時 {total:.1f}s（目標 ≤ 300s）")
    skipped = [t for t, s, _ in _results if s != "OK"]
    if skipped:
        print(f"未完成的步驟：{skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
