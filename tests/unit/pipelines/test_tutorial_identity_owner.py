"""Phase 40 Task 2：只有 Ticket Analysis 能建立新的 Tutorial 身分（`分析工單` Rule 10）。

設計 §7.3 明說 Release Update 與 Feedback Review 只能在**既有**教學上長版本，所以
`create_tutorial_identity` 只准存在於 `pipelines/ticket.py`。守門的方式是掃 `pipelines/`
套件的原始碼：Phase 44／46／52 的 `release.py`、`feedback.py` 還沒建立，用 glob 而不是
逐一 import，它們一落地就自動被這條測試蓋到。
"""

from pathlib import Path

from training_kb.pipelines import ticket

PIPELINE_DIR = Path(ticket.__file__).parent
ALLOWED = frozenset({"__init__.py", "ticket.py"})


def test_only_ticket_pipeline_creates_tutorial_identity() -> None:
    assert hasattr(ticket, "create_tutorial_identity")
    others = sorted(path for path in PIPELINE_DIR.glob("*.py") if path.name not in ALLOWED)
    assert others, "pipelines 套件至少還有 common.py，掃不到東西代表這條測試失效了"
    for path in others:
        source = path.read_text(encoding="utf-8")
        assert "create_tutorial_identity" not in source, path.name
        assert "Tutorial(" not in source, path.name


def test_ticket_module_owns_the_five_produced_names() -> None:
    for name in ("TicketAction", "ALL_STEP_TYPES", "TicketGap", "decide_ticket_action",
                 "record_decision", "tutorial_slug", "create_tutorial_identity",
                 "create_first_version"):
        assert hasattr(ticket, name), name
