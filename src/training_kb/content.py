"""教學內容模組：版號分配（Phase 20）。Phase 21–23 會在同一支檔案追加內容驗證、
Markdown／diff 與建版，欄位與函式名一律以 00A §6.6 為準。

版號屬於 Tutorial，不屬於流程：三條 pipeline（CREATE／UPDATE／REFINE）都只能經
`allocate_version` 取號，任何 handler 自己拼「current + 1」都會讓同一篇教學出現兩條版本鏈
（設計 §8.1）。決定的形狀是 `VersionPlan`——**它只是「這次要寫第幾版」的凍結決定**，
版本還沒有寫進 DynamoDB，寫入是 Phase 23 `create_version` 的事。

決策順序固定（設計 §8.3、§14.2）：

```text
operations.load(operation_id)
   | 沒有紀錄 ----------> CoordinationError（尚未被 O2 接受）
   v
   record.version_id 有值？ -- 是 --> 讀既有 VERSION item
   | 否                        有 -> 沿用它的 supersedes / reason / rules_applied
   |                           無 -> supersedes 由基底重新推導，其餘用參數
   v
   tutorial.current_version -> base（None 代表還沒有任何已發布版本）
   v
   number = base 號碼 + 1；該號碼已有 VERSION item 就繼續 +1
   v
   operations.record_version(...) 先落地，再回傳 VersionPlan
```

**基底與號碼是兩件事。** `supersedes` 固定取 `current_version`——只有 publish 成功才會切換它
（F37），所以它就是「最近已發布版本」；號碼則必須跳過已被占用的號碼，否則上一次永久失敗
留下的未發布 v2 會被新操作覆寫。D26 允許缺口，不允許覆寫。

**先落地再回傳。** `record_version` 必須在回傳前完成：落地前當機時重試由 `current_version`
重新推導出同一號碼，落地後當機時重試直接讀回同一號碼。**這個保證的前提是 O2 串行（F35），
而 O2 gate 尚未通過**：兩個併發操作仍可能探到同一個空號，那是 gate 未通過的已知後果，
不是條件寫入就能宣稱解決。本模組只宣稱「給定同一份操作紀錄時版號確定」。

`record_version` 是 write-once（Phase 11 依 Phase 10 review 追加：同值 no-op、換值丟
`CoordinationError`）。這裡的順序「先 `load`、有 `version_id` 就直接重用、沒有才配號再寫」
天生相容——重送根本走不到第二次寫入；併發探到**不同**空號時，輸的那一邊會拿到
`CoordinationError` 而不是靜默覆寫別人的版號。

執行資訊（探到第幾號、基底怎麼推導）一律留在 operation 紀錄，不得寫上 VERSION item 或
`Tutorial`：十實體模型是 strict，沒有第三類屬性（00A §3.6）。
"""

import difflib
import re
from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import ValidationError

from training_kb.errors import ContentError, CoordinationError
from training_kb.models import StepDraft, StepType, TutorialContent
from training_kb.operations import OperationCoordinator
from training_kb.repository import Repository

# --- 1. 版本 ID 編碼 ---------------------------------------------------------


def make_version_id(slug: str, number: int) -> str:
    """`<slug>@v<n>`（00A §3.3）。`bool` 先擋掉，否則 `True` 會組出 `a@vTrue`。"""
    if isinstance(number, bool) or not isinstance(number, int) or number < 1:
        raise ValueError(f"invalid version parts: {slug!r}, {number}")
    if not slug or slug != slug.strip() or "@" in slug or "#" in slug:
        raise ValueError(f"invalid version parts: {slug!r}, {number}")
    return f"{slug}@v{number}"


def parse_version_id(value: str) -> tuple[str, int]:
    """`make_version_id` 的反函式；只接受它產得出來的字串。

    `isdecimal()`（不是 `isdigit()`）擋掉 `²` 這種 `int()` 會丟自己的 `ValueError` 的字元，
    與 `keys.parse_step_pk` 同一套寫法；最後的 round-trip 比較再擋掉 `a@v01` 這種前導零與
    `a@v１` 這種全形數字——它們 `int()` 得到同一個值，組回去卻不是原本那個 ID，
    放行等於讓兩個字串對應同一版。
    """
    slug, separator, suffix = value.partition("@v")
    if not separator or not suffix.isdecimal():
        raise ValueError(f"invalid version id: {value}")
    number = int(suffix)
    if number < 1 or make_version_id(slug, number) != value:
        raise ValueError(f"invalid version id: {value}")
    return slug, number


# --- 2. VersionPlan ----------------------------------------------------------


@dataclass(frozen=True)
class VersionPlan:
    """「這次要寫第幾版、以哪一版為基底、為什麼寫、套用了哪些規則」的凍結決定。

    `rules_applied` 是 `tuple`（不是 `list`），frozen dataclass 才真的凍結得住；
    寫進 `TutorialVersion.rules_applied`（`list[str]`）是 Phase 23 的轉換。
    """

    version_id: str
    slug: str
    number: int
    supersedes: str | None
    reason: str
    rules_applied: tuple[str, ...]
    operation_id: str


def _plan(version_id: str, supersedes: str | None, reason: str,
          rules_applied: Sequence[str], operation_id: str) -> VersionPlan:
    slug, number = parse_version_id(version_id)
    return VersionPlan(version_id=version_id, slug=slug, number=number, supersedes=supersedes,
                       reason=reason, rules_applied=tuple(rules_applied),
                       operation_id=operation_id)


# --- 3. 版號分配 -------------------------------------------------------------


def _base_version(repository: Repository, slug: str) -> tuple[str | None, int]:
    """基底＝最近**已發布**的版本，也就是 `current_version`；**不是**最新版本。

    回 `(supersedes, base_number)`；還沒有任何已發布版本時是 `(None, 0)`，所以第一版是 v1。
    """
    tutorial = repository.get_tutorial(slug)
    if tutorial is None:
        raise ContentError(f"找不到教學：{slug}")
    if tutorial.current_version is None:
        return None, 0
    base_slug, number = parse_version_id(tutorial.current_version)
    if base_slug != slug:
        raise ContentError(f"{slug} 的 current_version 指向別篇：{tutorial.current_version}")
    return tutorial.current_version, number


def _replay_plan(version_id: str, tutorial_id: str, operation_id: str, repository: Repository,
                 reason: str, rules_applied: Sequence[str]) -> VersionPlan:
    """同一個 operation 重送：直接沿用紀錄裡的版號，**不重新配號**。

    紀錄的版號屬於別篇教學代表呼叫端把兩次邏輯操作混成同一個 `operation_id`
    （`OperationRecord.version_id` 是單值，一個 operation 只對應一篇教學的一個版本，
    D-59），這是協調錯誤，不是內容錯誤，所以丟 `CoordinationError` 並在訊息帶兩個 slug。

    VERSION item 已經寫出來時，`supersedes`／`reason`／`rules_applied` 一律以**表裡那筆**
    為準：重試不得用新參數改寫已保存的內容（設計 §14.2）。這裡也**不**擋已發布的版本——
    「已發布不可覆寫」是 Phase 23 `create_version` 的關卡，本函式只決定版號。
    """
    slug, _ = parse_version_id(version_id)
    if slug != tutorial_id:
        raise CoordinationError(f"操作 {operation_id} 已配給 {slug}，不能改用 {tutorial_id}")
    existing = repository.get_version(version_id)
    if existing is not None:
        return _plan(version_id, existing.supersedes, existing.reason,
                     existing.rules_applied, operation_id)
    supersedes = _base_version(repository, tutorial_id)[0]
    return _plan(version_id, supersedes, reason, rules_applied, operation_id)


def _next_free_number(repository: Repository, slug: str, base_number: int) -> int:
    """從基底號碼往上找第一個還沒有 VERSION item 的號碼。

    只做 `base_number + 1` 會覆寫上一次永久失敗留下的未發布版本；D26 允許號碼缺口，
    **不允許覆寫**，所以被占用的號碼一律跳過，不回頭補洞。
    """
    number = base_number + 1
    while repository.get_version(make_version_id(slug, number)) is not None:
        number += 1
    return number


def allocate_version(
    tutorial_id: str,
    operation_id: str,
    operations: OperationCoordinator,
    *,
    repository: Repository,
    reason: str,
    rules_applied: Sequence[str],
) -> VersionPlan:
    """回這次要寫的版號；同一個 `operation_id` 重送必定拿到同一個 `version_id`（D26）。

    `tutorial_id` 就是 `Tutorial.slug`，本專案不另外發明 Tutorial 主鍵。失敗路徑一律在
    `record_version` 之前就丟出來，不留半筆版號紀錄。
    """
    if not reason.strip():
        raise ContentError("建立版本必須記錄 reason")
    record = operations.load(operation_id)
    if record is None:
        raise CoordinationError(f"操作尚未被接受：{operation_id}")
    if record.version_id is not None:
        return _replay_plan(record.version_id, tutorial_id, operation_id,
                            repository, reason, rules_applied)
    supersedes, base_number = _base_version(repository, tutorial_id)
    version_id = make_version_id(tutorial_id, _next_free_number(repository, tutorial_id,
                                                                base_number))
    operations.record_version(operation_id, version_id)
    return _plan(version_id, supersedes, reason, rules_applied, operation_id)


# --- 4. 內容驗證 -------------------------------------------------------------

LEGAL_STEP_TYPES = frozenset(StepType)


def _section_problems(content: TutorialContent) -> list[str]:
    """五段是否都有非空內容、步驟編號是否為 1..n 連續。

    `steps` 為空是唯一的提早返回：沒有步驟就沒有編號可檢查，繼續往下只會報出
    「1 到 0 的連續整數」這種看不懂的話。
    """
    problems = [
        f"缺少 {label}"
        for label, value in (("Title", content.title), ("Problem", content.problem),
                             ("Expected Outcome", content.expected_outcome))
        if not value.strip()
    ]
    if not [item for item in content.prerequisites if item.strip()]:
        problems.append("缺少 Prerequisites（沒有前置條件時請寫「無」）")
    if not content.steps:
        problems.append("缺少 Steps")
        return problems
    numbers = [step.number for step in content.steps]
    if numbers != list(range(1, len(numbers) + 1)):
        problems.append(f"步驟編號必須是 1 到 {len(numbers)} 的連續整數，實際是 {numbers}")
    return problems


_FEATURE_SPLITTERS = (",", "、", ";", "/", "+", " and ")


def _feature_problem(index: int, raw: str, known: frozenset[str]) -> str | None:
    """一步恰好引用一個既有 Feature（D05）；零個或多個一律拒絕，不自動挑第一個。

    **先比對 `known_feature_ids`，比不到才看分隔符號**：名稱真的含有 `/` 或 `+` 的既有
    Feature（例如 `Import/Export`）因此仍然通過，只有「查無此 Feature 而且長得像兩個」
    才報「引用了多個」。分隔符號清單是本 Phase 的選擇、不是規格；日後出現名稱含分隔符號
    又尚未建立成 Feature 的情況，正確做法是先建立／更名該 Feature，不是在這裡放行。
    """
    feature_id = raw.strip()
    if not feature_id:
        return f"第 {index} 步沒有引用 Feature"
    if feature_id in known:
        return None
    if any(mark in feature_id for mark in _FEATURE_SPLITTERS):
        return f"第 {index} 步引用了多個 Feature：{feature_id}"
    return f"第 {index} 步引用的 Feature 不存在：{feature_id}"


def _step_problems(content: TutorialContent, known: frozenset[str]) -> list[str]:
    """逐步檢查文字、型態與 Feature 引用；訊息只帶步驟編號與 `feature_id`。

    **不帶 `step.text` 全文**：這段訊息會被 Phase 18 原樣送回模型，也會落進操作紀錄，
    帶上全文等於把使用者原始回饋沿著錯誤路徑外流。
    """
    problems: list[str] = []
    for index, step in enumerate(content.steps, start=1):
        if not step.text.strip():
            problems.append(f"第 {index} 步沒有文字")
        if step.type not in LEGAL_STEP_TYPES:
            problems.append(f"第 {index} 步的 type 不合法：{step.type}")
        problem = _feature_problem(index, step.feature_id, known)
        if problem is not None:
            problems.append(problem)
    return problems


def validate_content(content: TutorialContent, known_feature_ids: frozenset[str]) -> None:
    """結構可不可以保存（F48）；回 `None` 代表可保存，不合格一次丟出全部問題。

    **不判斷文字好不好，也不修改任何內容**：驗證器不是修正器，缺 Feature 不會自動補、
    多引用不會自動取第一個（D05）。`known_feature_ids` 由呼叫端先查好傳進來（裡面是裸 ID，
    不是 `FEATURE#Prepare`），本函式不讀 DynamoDB、不呼叫模型、不寫任何檔案。

    **兩組問題一起收集再丟。** Phase 18 只允許一次修正（設計 §14.3）：五段有問題就先丟出，
    那唯一一次機會會被浪費在最前面的小問題上，步驟引用的問題要等下一輪才看得到，而下一輪
    不存在。唯一的提早收斂在 `_section_problems`（`steps` 為空）。

    丟出的是 `ContentError`（`PermanentError` 子類）：這是資料不合法、不是服務暫時故障，
    不進 ASL Task Retry，重試上限由 Phase 18 管。
    """
    problems = _section_problems(content)
    problems.extend(_step_problems(content, known_feature_ids))
    if problems:
        raise ContentError("教學內容驗證失敗：" + "；".join(problems))


# --- 5. Markdown 全文 --------------------------------------------------------

_MD_SPECIALS = frozenset("\\`*_[]<>#|()")
_SECTIONS = ("Title", "Problem", "Prerequisites", "Steps", "Expected Outcome")
_STEP_LINE = re.compile(r"^(\d+)\. \(type=([a-z_]+), feature=([^)]*)\) (.*)$")
_DANGLING_BACKSLASH = re.compile(r"(?<!\\)(?:\\\\)*\\$")


def escape_markdown(text: str) -> str:
    r"""在 Markdown 會吃掉的字元前插入一個反斜線；只加，不改寫、不刪字。

    兩層：行內符號 `` \ ` * _ [ ] < > # | ( ) `` 逐字加反斜線（`#` 讓使用者文字無法偽造
    `# `／`## ` 標題，`( )` 讓步驟行的 `feature=...)` 不會被提前關閉），再加上只有出現在
    **行首**才有意義的 `-`、`+` 與「數字後接句點」——每個欄位都自成一行，所以字串開頭
    就是行首。`>` 已在行內清單裡，不必再處理一次行首。

    反斜線自己也在清單裡，這是 `unescape_markdown` 能一對一還原的前提：它先被加倍，
    後面的 `\<` 才不會與原文裡真的寫著的 `\<` 混在一起。
    """
    escaped = "".join(f"\\{ch}" if ch in _MD_SPECIALS else ch for ch in text)
    if escaped[:1] in ("-", "+"):
        return "\\" + escaped
    head, dot, rest = escaped.partition(".")
    if dot and head.isdigit():
        return f"{head}\\.{rest}"
    return escaped


def unescape_markdown(text: str) -> str:
    """把反斜線後的下一個字元原樣取出；對任何字串 `unescape(escape(x)) == x`。

    **不看被轉義的是哪個字元**：只要照「反斜線吃掉下一個字元」還原，就與
    `escape_markdown` 的插入規則互為反函式，日後改動 `_MD_SPECIALS` 也不會讓舊全文解錯。
    結尾落單的反斜線不可能由 `escape_markdown` 產生，代表全文在 S3 之外被改過，
    丟 `ContentError` 而不是靜靜吃掉它。
    """
    if _DANGLING_BACKSLASH.search(text):
        raise ContentError("Markdown 以落單的反斜線結尾")
    return re.sub(r"\\(.)", r"\1", text)


def _one_line(label: str, value: str) -> str:
    """欄位只能有一行，轉義後回傳；`label` 只用來組錯誤訊息，不進輸出。

    多行欄位會讓 `parse_markdown` 分不出「同一欄的第二行」與「下一個項目」，
    精確反函式就斷了（多段落排版留給 Phase 57 的 HTML renderer）。
    """
    if "\n" in value or "\r" in value:
        raise ContentError(f"{label} 不得含換行：每個欄位在 Markdown 中只有一行")
    if label == "feature_id" and ("(" in value or ")" in value):
        raise ContentError(f"feature_id 不得含括號：{value}")
    return escape_markdown(value)


def render_markdown(content: TutorialContent) -> str:
    """把 `TutorialContent` 寫成固定樣板的全文（00A §5.2）。

    五段順序不可變、每段與標題之間恰好一個空行、檔案以一個換行結尾。**格式固定是
    diff 有意義的前提**：前綴或空行數量會變的話，每一版的 diff 都會變成「整篇都改了」。
    每個欄位都先過 `_one_line`（拒絕換行、再轉義），所以使用者或模型的文字不可能
    長出新的標題、清單或連結。
    """
    steps = [
        f"{step.number}. (type={step.type}, feature={_one_line('feature_id', step.feature_id)}) "
        f"{_one_line('step.text', step.text)}"
        for step in content.steps
    ]
    items = "\n".join(f"- {_one_line('Prerequisites', item)}" for item in content.prerequisites)
    blocks = [
        f"# {_one_line('Title', content.title)}",
        "## Problem\n\n" + _one_line("Problem", content.problem),
        "## Prerequisites\n\n" + items,
        "## Steps\n\n" + "\n".join(steps),
        "## Expected Outcome\n\n" + _one_line("Expected Outcome", content.expected_outcome),
    ]
    return "\n\n".join(blocks) + "\n"


def _split_sections(markdown: str) -> dict[str, list[str]]:
    """把全文切成五個區塊的非空行；少一個區塊就丟 `ContentError`。

    **先判斷 `## ` 再判斷 `# `**，否則 `## Problem` 會被當成標題行。空行一律丟掉，
    所以 render 的空行數量不影響解析。
    """
    sections: dict[str, list[str]] = {}
    current = ""
    for line in markdown.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
        elif line.startswith("# "):
            current = "Title"
            sections[current] = [line[2:]]
        elif line.strip():
            sections.setdefault(current, []).append(line)
    missing = [name for name in _SECTIONS if name not in sections]
    if missing:
        raise ContentError("Markdown 缺少區塊：" + "、".join(missing))
    return sections


def _step_type(value: str) -> StepType:
    """把步驟行讀到的 `type=` 字串收斂成 `StepType`；不合法丟 `ContentError`。

    Phase 文件原本寫 `type=match[2]` 直接丟給 pydantic，但 `StepDraft.type` 的宣告型別是
    `StepType`，mypy strict 不接受 `str`（而本專案不用 `# type: ignore`）。在這裡先判斷還有
    第二個好處：`StepType("scroll")` 丟的是**裸 `ValueError`**，不是 `ValidationError`，
    照文件的 `except ValidationError` 會讓它外洩到呼叫端。
    """
    if value not in LEGAL_STEP_TYPES:
        raise ContentError(f"步驟 type 不合法：{value}")
    return StepType(value)


def _only_line(sections: dict[str, list[str]], name: str) -> str:
    lines = sections[name]
    if len(lines) != 1:
        raise ContentError(f"{name} 區塊必須恰好一行，實際 {len(lines)} 行")
    return unescape_markdown(lines[0])


def parse_markdown(markdown: str) -> TutorialContent:
    """`render_markdown` 的反函式：Phase 23 用它把 S3 全文讀回來核對基表 STEP。

    `StepDraft`／`TutorialContent` 是 Phase 03 的嚴格模型，遇到不合法內容丟的是 pydantic
    的 `ValidationError`；**呼叫端只認得 Phase 02 的錯誤契約**，所以一律轉成 `ContentError`
    （`PermanentError` 子類），不讓第三方例外型別外洩。訊息只帶欄位數量，不帶欄位值：
    它可能含使用者原文。
    """
    sections = _split_sections(markdown)
    try:
        steps = []
        for line in sections["Steps"]:
            match = _STEP_LINE.match(line)
            if match is None:
                raise ContentError(f"步驟格式不符：{line}")
            steps.append(StepDraft(number=int(match[1]), type=_step_type(match[2]),
                                   text=unescape_markdown(match[4]),
                                   feature_id=unescape_markdown(match[3])))
        return TutorialContent(
            title=_only_line(sections, "Title"),
            problem=_only_line(sections, "Problem"),
            prerequisites=[unescape_markdown(line.removeprefix("- "))
                           for line in sections["Prerequisites"]],
            steps=steps,
            expected_outcome=_only_line(sections, "Expected Outcome"),
        )
    except ValidationError as exc:
        raise ContentError(
            f"Markdown 內容不符 TutorialContent 限制：{exc.error_count()} 個欄位") from exc


# --- 6. 與前版的 unified diff ------------------------------------------------


def make_diff(previous_md: str | None, current_md: str, *, previous_name: str,
              current_name: str) -> str:
    """回 unified diff 文字；沒有前版時回 `""`（F50 選 C）。

    `previous_md is None` 是「第一版，沒有前一版可比較」，`""` 則同時涵蓋「兩版內容完全
    相同」；兩者在檔案裡長得一樣，所以**畫面上「第一版」要靠 `supersedes is None` 判斷，
    不是靠 diff 檔是否為空**（Phase 57）。Phase 23 兩種情況都照樣寫出 `v<n>.diff`，
    只是 v1 那個是 0 位元組。

    `splitlines()` 搭 `lineterm=""`：全文的每一行都已經沒有換行字元，讓 `difflib` 再補一次
    會讓每個表頭後面多一個空行。輸出非空時補一個結尾換行，與 `render_markdown` 一致。
    """
    if previous_md is None:
        return ""
    lines = difflib.unified_diff(
        previous_md.splitlines(), current_md.splitlines(),
        fromfile=previous_name, tofile=current_name, lineterm="",
    )
    text = "\n".join(lines)
    return f"{text}\n" if text else ""
