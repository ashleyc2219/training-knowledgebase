"""固定格式全文、可反解的轉義與 unified diff（Phase 22）。

整個檔案是純字串運算：不碰 AWS、不呼叫模型。條件寫入的語意在
`tests/integration/test_private_artifacts.py`，那裡才需要真的 bucket。

`four_step_content(**overrides)` 與 `tests/unit/test_validate_content.py` 同名同語意，
但本 Phase 的 override 全是合法值，所以不需要 `model_construct`——這裡要證明的是
「合法內容 render 出來的形狀」，不是 schema 之後還有第二道驗證。
"""

from collections.abc import Sequence

import pytest

from training_kb.content import (
    escape_markdown,
    parse_markdown,
    render_markdown,
    unescape_markdown,
)
from training_kb.errors import ContentError
from training_kb.models import StepDraft, StepType, TutorialContent

_TEXTS = ("開啟行事曆。", "選擇今天的會議。", "開啟摘要。", "確認摘要內容。")
_TYPES = ("read", "click_ui", "click_ui", "read")


def four_step_content(
    *,
    title: str = "準備會議",
    problem: str = "會議前的準備步驟散在多個頁面，新人找不到。",
    prerequisites: Sequence[str] | None = None,
    expected_outcome: str = "會議開始前已備妥議程與摘要。",
    step3_feature: str = "Prepare",
    step3_text: str = _TEXTS[2],
) -> TutorialContent:
    """預設是合格的四步草稿；四步都引用 `Prepare`，只有第 3 步會被 override。"""
    features = ("Prepare", "Prepare", step3_feature, "Prepare")
    texts = (_TEXTS[0], _TEXTS[1], step3_text, _TEXTS[3])
    steps = [
        StepDraft(number=index + 1, type=StepType(_TYPES[index]), text=texts[index],
                  feature_id=features[index])
        for index in range(4)
    ]
    needs = list(prerequisites) if prerequisites is not None else ["已登入工作區"]
    return TutorialContent(title=title, problem=problem, prerequisites=needs,
                           steps=steps, expected_outcome=expected_outcome)


# --- 固定格式與轉義 ---------------------------------------------------------


def test_render_uses_fixed_headings_and_step_prefix() -> None:
    markdown = render_markdown(four_step_content())
    assert markdown.splitlines()[0] == "# 準備會議"
    assert "## Expected Outcome" in markdown
    assert "3. (type=click_ui, feature=Prepare) " in markdown


def test_render_keeps_five_sections_in_order() -> None:
    """順序固定才有意義的 diff：格式一變，每一版都會顯示「整篇都改了」。"""
    markdown = render_markdown(four_step_content())
    headings = [line for line in markdown.splitlines() if line.startswith("#")]
    assert headings == ["# 準備會議", "## Problem", "## Prerequisites", "## Steps",
                        "## Expected Outcome"]
    assert markdown.endswith("\n") and not markdown.endswith("\n\n")


def test_user_text_cannot_inject_markdown() -> None:
    markdown = render_markdown(four_step_content(title="# 假標題 <script>",
                                                 step3_text="- 假清單"))
    assert markdown.count("\n# ") == 0
    assert "\\<script\\>" in markdown


@pytest.mark.parametrize("title", ["準備會議", "# 假標題", "1. 假步驟", "反斜線\\結尾字"])
def test_round_trip_restores_content(title: str) -> None:
    content = four_step_content(title=title)
    assert parse_markdown(render_markdown(content)) == content


@pytest.mark.parametrize(
    "text",
    ["", "準備會議", "# 假標題", "- 假清單", "+ 也是清單", "1. 假步驟", "a\\b",
     "反斜線\\", "(type=read, feature=X)", "**粗體** _斜體_ [連結](url)", "管線 | 符號"],
)
def test_escape_and_unescape_are_inverses(text: str) -> None:
    assert unescape_markdown(escape_markdown(text)) == text


def test_dangling_backslash_is_rejected() -> None:
    """落單的反斜線不可能由 `escape_markdown` 產生，代表全文被外部改過。"""
    with pytest.raises(ContentError, match="反斜線"):
        unescape_markdown("結尾\\")


def test_multiline_field_is_rejected() -> None:
    """每個欄位只有一行，否則 `parse_markdown` 不再是精確反函式。"""
    with pytest.raises(ContentError, match="Title"):
        render_markdown(four_step_content(title="第一行\n第二行"))


def test_feature_id_with_parenthesis_is_rejected() -> None:
    """步驟行用 `)` 收尾，`feature_id` 帶括號會讓解析出現歧義。"""
    with pytest.raises(ContentError, match="feature_id"):
        render_markdown(four_step_content(step3_feature="Prep(are)"))


def test_broken_markdown_is_rejected() -> None:
    markdown = render_markdown(four_step_content()).replace("## Expected Outcome", "## Outcome")
    with pytest.raises(ContentError, match="缺少區塊"):
        parse_markdown(markdown)


def test_model_limit_becomes_content_error() -> None:
    """編號不連續是 Phase 03 擋下的，但呼叫端只認得 Phase 02 的錯誤契約。"""
    markdown = render_markdown(four_step_content()).replace("\n1. (type=", "\n2. (type=")
    with pytest.raises(ContentError, match="TutorialContent"):
        parse_markdown(markdown)


def test_bad_step_line_is_rejected() -> None:
    markdown = render_markdown(four_step_content()).replace("2. (type=click_ui,", "2) type是")
    with pytest.raises(ContentError, match="步驟格式不符"):
        parse_markdown(markdown)


def test_illegal_step_type_in_markdown_is_rejected() -> None:
    """`StepType("scroll")` 丟的是裸 `ValueError`，不能讓它外洩到呼叫端。"""
    markdown = render_markdown(four_step_content()).replace("type=read,", "type=scroll,")
    with pytest.raises(ContentError, match="type 不合法"):
        parse_markdown(markdown)
