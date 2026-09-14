"""教學內容模組：版號分配（Phase 20）、內容驗證（Phase 21）、Markdown 與 diff 私有產物
（Phase 22）、未發布版本與關係完整寫入（Phase 23）都在這一支檔案；Phase 26 之後還會在同一支
追加退役。欄位與函式名一律以 00A §6.6 為準。

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
from datetime import datetime

from pydantic import ValidationError

from training_kb.clock import to_iso
from training_kb.errors import (
    ContentError,
    CoordinationError,
    ObjectAlreadyExists,
    PermanentError,
    TransientError,
)
from training_kb.keys import (
    edge_sk,
    feature_pk,
    parse_pk,
    rule_pk,
    step_pk,
    tutorial_pk,
    version_pk,
)
from training_kb.models import (
    Feature,
    StepDraft,
    StepType,
    Tutorial,
    TutorialContent,
    TutorialStatus,
    TutorialVersion,
)
from training_kb.operations import OperationCoordinator
from training_kb.repository import DynamoValue, Repository, item_to_model

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


# --- 7. 私有 key 與條件寫入 --------------------------------------------------

PRIVATE_TUTORIAL_PREFIX = "tutorials/"
PUBLIC_SITE_PREFIX = "site/"


def _artifact_key(slug: str, number: int, suffix: str) -> str:
    """`tutorials/<slug>/v<n><suffix>`（00A §3.4）。

    第一行的 `make_version_id` 只當守門員：`slug` 含 `@`／`#`、有前後空白，或 `number < 1`
    時它丟 `ValueError`，避免產出 `tutorials/a@v1/v0.md` 這種對不上版本的 key。回傳值刻意
    不用——key 的形狀是 `<slug>/v<n>`，不是 `<slug>@v<n>`。
    """
    make_version_id(slug, number)
    return f"{PRIVATE_TUTORIAL_PREFIX}{slug}/v{number}{suffix}"


def markdown_key(slug: str, number: int) -> str:
    """該版全文的私有 key：`tutorials/<slug>/v<n>.md`。"""
    return _artifact_key(slug, number, ".md")


def diff_key(slug: str, number: int) -> str:
    """該版與前版差異的私有 key：`tutorials/<slug>/v<n>.diff`（v1 是 0 位元組）。"""
    return _artifact_key(slug, number, ".diff")


def put_private_artifact(repository: Repository, key: str, text: str,
                         content_type: str) -> None:
    """以條件寫入保存未發布產物；同 key 同內容視為重送，內容不同則拒絕覆寫。

    **公開前綴一律拒絕**（設計 §9.3、§13）：未發布全文落進 `site/` 就是已公開，
    「還沒放連結」不算私有。發布 staging 也不走這裡，P24 直接用 `Repository.put_object`。

    `ObjectAlreadyExists`（S3 412）用**型別**而不是訊息字串辨識（D-30）：只有它代表
    「同一個 key 已經有東西」，這時才比對 bytes——一樣就是同一次操作重送，靜靜通過；
    不一樣代表兩次不同內容搶同一版，丟 `ContentError` 並**保留既有物件**。
    `PermanentError` 的其他子類（例如建 `Repository` 時沒給 bucket）要原樣往上拋，
    攔太寬會把設定錯誤誤判成重送。
    """
    if not key.startswith(PRIVATE_TUTORIAL_PREFIX) or key.startswith(PUBLIC_SITE_PREFIX):
        raise ContentError(f"未發布產物只能寫私有前綴 tutorials/：{key}")
    body = text.encode("utf-8")
    try:
        repository.put_object(key, body, content_type, if_none_match=True)
    except ObjectAlreadyExists:
        if repository.get_object(key) != body:
            raise ContentError(f"S3 已有同一個 key 但內容不同，不覆寫：{key}") from None


# --- 8. 未發布版本與關係完整寫入 --------------------------------------------

MARKDOWN_CONTENT_TYPE = "text/markdown; charset=utf-8"
"""`tutorials/<slug>/v<n>.md` 的 content type；Phase 22 只建議、沒有定名，這裡定成常數。"""

DIFF_CONTENT_TYPE = "text/plain; charset=utf-8"
"""`tutorials/<slug>/v<n>.diff` 的 content type；v1 的空 diff 也用同一個值。"""


def _previous_markdown(plan: VersionPlan, repository: Repository) -> tuple[str | None, str]:
    """前一版的全文與它的 key；沒有前一版時回 `(None, "")`，`make_diff` 會回空字串。

    前一版存在卻讀不回全文是**內容問題**（00A §4.1 把「版本全文讀不回來」歸在
    `ContentError`），不是暫時故障：重試同樣讀不到，交給 ASL Retry 只會白跑三次。
    """
    if plan.supersedes is None:
        return None, ""
    previous = repository.get_version(plan.supersedes)
    if previous is None:
        raise ContentError(f"找不到前一版 {plan.supersedes}，無法產生 diff")
    body = repository.get_object(previous.s3_key)
    if body is None:
        raise ContentError(f"前一版 {plan.supersedes} 缺少 S3 全文 {previous.s3_key}")
    return body.decode("utf-8"), previous.s3_key


_VERSION_FIELDS = ("version_id", "slug", "supersedes", "reason", "rules_applied", "s3_key")
"""重送時要逐欄比對的 `TutorialVersion` 欄位；`published_at` 不在內（本模組永遠不寫它）。"""


def _planned_version(plan: VersionPlan) -> TutorialVersion:
    """plan 應該寫出來的 VERSION item（`published_at` 永遠是 `None`）。

    先確認 plan 自洽：`s3_key` 由 `slug`／`number` 組，VERSION item 的鍵由 `version_id` 組，
    三者對不起來時會寫出「item 說自己是 v1、全文卻放在 v2.md」的版本。`make_version_id`
    對不合法的 `slug`／`number` 丟的是 `ValueError`，這裡一律轉成呼叫端唯一要接的
    `ContentError`（00A §4.1）。
    """
    try:
        consistent = make_version_id(plan.slug, plan.number) == plan.version_id
    except ValueError:
        consistent = False
    if not consistent:
        raise ContentError(
            f"plan 不自洽：version_id={plan.version_id}，slug={plan.slug}、number={plan.number}")
    return TutorialVersion(version_id=plan.version_id, slug=plan.slug,
                           supersedes=plan.supersedes, reason=plan.reason,
                           rules_applied=list(plan.rules_applied),
                           s3_key=markdown_key(plan.slug, plan.number), published_at=None)


def _reject_changed_version(existing: TutorialVersion, planned: TutorialVersion) -> None:
    """重送必須帶同一份內容；欄位對不上就拒絕，**不靜默沿用既有 item**。

    與 `put_private_artifact` 比對 bytes 是同一個作法：同一個版號只能有一種內容。沿用舊
    item 卻照新 plan 寫邊，會寫出「`VERSION.rules_applied` 是空的，卻有一條
    `RULE#R-007 APPLIED_TO` 指向它」這種權威欄位與邊互相矛盾的版本（D17），而且核對還會
    通過。`published_at` 不比：本模組永遠不寫它，而「已發布不可覆寫」在更前面就擋掉了。
    """
    changed = [name for name in _VERSION_FIELDS
               if getattr(existing, name) != getattr(planned, name)]
    if changed:
        raise ContentError(
            f"版本 {existing.version_id} 已存在且內容不同，不覆寫：{'、'.join(changed)}")


def _verified(version_id: str, repository: Repository) -> TutorialVersion:
    """自我核對後回傳 VERSION item；有缺漏就丟 `ContentError`，**不刪任何已寫入的產物**。

    「寫入沒丟例外」不等於完整（設計 §8.2）：邊是逐筆寫的，中間當機時前幾筆已經落地。
    失敗時保留私有 S3 產物，重送才沿用得到同版號與同產物（F36）。
    """
    problems = _missing_parts(version_id, repository)
    if problems:
        raise ContentError("版本核對失敗：" + "；".join(problems))
    version = repository.get_version(version_id)
    assert version is not None  # _missing_parts 已確認它存在
    return version


def create_version(plan: VersionPlan, content: TutorialContent,
                   repository: Repository) -> TutorialVersion:
    """寫出一個 `published_at=None` 的完整版本，順序固定，最後自己核對一次。

    ```text
    已發布就拒絕 -> validate_content -> S3 .md -> S3 .diff -> VERSION META
                 -> STEP／SUPERSEDES／APPLIED_TO 邊 -> verify
    ```

    **`published_at` 一律不寫、`Tutorial.current_version` 一律不碰**（D25、F37）：建立與發布
    是兩件事，只有 Phase 24 的 publish 成功才會填值與切換。

    **重送要冪等，但只對同一份 plan 冪等。** 先讀 `get_version`：已發布就丟 `ContentError`
    （不可覆寫）；已存在但未發布代表上一次寫到一半，此時先把 plan 組出來的 VERSION item
    與既有那筆**逐欄比對**（`_reject_changed_version`），一致才跳過 `put_meta`（Phase 06 的
    `create_only=True` 會拒絕重複建立）只補寫產物與邊，不一致一律拒絕——這一步在任何寫入
    之前，所以被拒的重送不會留下半筆產物或邊。S3 那一段的冪等由 `put_private_artifact` 的
    條件寫入保證；邊的內容完全由 `plan` 與 `content` 決定，所以重寫同一筆邊是安全的。

    既有 Feature 由 `scan_entity("FEATURE")` 取得，每一筆都經 `item_to_model`（00A §3.6）：
    strict 模型不接受 `PK`／`SK`／`entity`／`_revision`，直接 `Feature.model_validate(item)`
    會整筆 `ValidationError`。
    """
    planned = _planned_version(plan)
    existing = repository.get_version(plan.version_id)
    if existing is not None:
        if existing.published_at is not None:
            raise ContentError(f"版本 {plan.version_id} 已發布，不可覆寫")
        _reject_changed_version(existing, planned)
    known = frozenset(item_to_model(item, Feature).feature_id
                      for item in repository.scan_entity("FEATURE"))
    validate_content(content, known)
    md_key = planned.s3_key
    current_md = render_markdown(content)
    previous_md, previous_name = _previous_markdown(plan, repository)
    put_private_artifact(repository, md_key, current_md, MARKDOWN_CONTENT_TYPE)
    put_private_artifact(
        repository, diff_key(plan.slug, plan.number),
        make_diff(previous_md, current_md, previous_name=previous_name, current_name=md_key),
        DIFF_CONTENT_TYPE,
    )
    if existing is None:
        repository.put_meta(planned)
    _write_edges(plan, content, repository)
    return _verified(plan.version_id, repository)


def _write_edges(plan: VersionPlan, content: TutorialContent, repository: Repository) -> None:
    """三種關係邊，順序固定：STEP 的 `REFERENCES`、`SUPERSEDES`、每條規則的 `APPLIED_TO`。

    **STEP 的 `attrs` 只放 `type` 與 `text`**：`entity` 是 `put_edge` 自己從 PK 前綴算出的保留
    屬性（多傳會被丟 `PermanentError`），`tutorial_version` 與 `number` 由
    `STEP#<version_id>#<n>` 還原、`feature_id` 由 `target` 還原，所以 Phase 08 的
    `get_steps` 讀得回完整的 `TutorialStep`（00A §3.6）。STEP 沒有 `META` item——這筆邊
    本身就是它。

    `APPLIED_TO` **只依 `plan.rules_applied` 產生**，不從前一版繼承：沿用原文不算套用
    （F29、D17），`VERSION.rules_applied` 才是權威，這條邊隨時可由 Phase 28 重建。

    邊的內容完全由 `plan` 與 `content` 決定，重送時重寫同一筆邊會得到一模一樣的 item，
    所以這裡用無條件 `put_edge`，不需要條件寫入。
    """
    version_key = version_pk(plan.version_id)
    for step in content.steps:
        repository.put_edge(
            step_pk(plan.version_id, step.number), "REFERENCES", feature_pk(step.feature_id),
            {"type": str(step.type), "text": step.text},
        )
    if plan.supersedes is not None:
        repository.put_edge(version_key, "SUPERSEDES", version_pk(plan.supersedes))
    for rule_id in plan.rules_applied:
        repository.put_edge(rule_pk(rule_id), "APPLIED_TO", version_key)


def verify_version_complete(version_id: str, repository: Repository) -> bool:
    """這個版本的 S3 產物、VERSION item、STEP 與三種邊是否齊全；只回 `True`／`False`。

    Phase 24 發布前一定要先問過它：關係不完整的版本一律不可發布。缺漏明細是
    module-private 的 `_missing_parts`，`create_version` 用它組出可讀的 `ContentError`；
    那不是跨模組 public API，呼叫端拿到的是一個布林值。
    """
    return not _missing_parts(version_id, repository)


def _expected_sk(relation: str, target: str) -> str | None:
    """`edge_sk` 的安全版：`target` 不是合法 PK（例如手改出來的 `FEATURE#`）時回 `None`。

    **核對是關卡，不是程式錯誤回報點。** 損壞的邊只可能來自 `put_edge` 以外的路徑（維護
    腳本、主控台手改），它要讓 `verify_version_complete` 回 `False`，不能變成 `ValueError`
    炸給 Phase 24——那會讓「不可發布」變成「發布流程當掉」。`PermanentError` 類的程式錯誤
    不在這裡吞，只有鍵格式的 `ValueError` 被收斂成「問題」。
    """
    try:
        return edge_sk(relation, target)
    except ValueError:
        return None


def _exact_edge_problems(repository: Repository, pk: str, relation: str,
                         expected: Sequence[str]) -> list[str]:
    """某個起點上的某種邊必須**恰好**等於 `expected`：缺的是問題，**多的也是問題**。

    只驗「不缺」會放行分岔的版本鏈（同一版兩條 `SUPERSEDES`），核對就不再是關卡。
    一律基表一致讀取，不查最終一致的 `by_target`。
    """
    endpoints: list[str] = []
    problems: list[str] = []
    for row in repository.query_pk(pk, sk_prefix=f"{relation}#", consistent=True):
        sort_key, target = str(row.get("SK", "")), str(row.get("target", ""))
        if sort_key != _expected_sk(relation, target):
            problems.append(f"{pk} 的 {relation} 邊 SK 與 target 不一致：{sort_key}")
            continue
        endpoints.append(target)
    problems += [f"缺少 {relation} 邊：{item}" for item in expected if item not in endpoints]
    problems += [f"多出 {relation} 邊：{item}" for item in endpoints if item not in expected]
    return problems


def _applied_to_problems(version_id: str, rules_applied: Sequence[str],
                         repository: Repository) -> list[str]:
    """指向這一版的 `APPLIED_TO` 邊必須**恰好**是 `rules_applied` 那幾條（D17、F29）。

    這些邊的起點是 `RULE#<rule_id>`，散在不同的 PK 上，所以「只查 `rules_applied` 那幾個
    起點」驗得出「不缺」、驗不出「不多」——上一版留下或維護腳本補錯的 `RULE#R-999` 會讓
    權威欄位與邊互相矛盾卻仍然通過。改用基表一致的 `scan_entity("RULE", meta_only=False)`
    （`entity` 等於 PK 前綴，所以邊會跟著本體一起被掃出來，00A §3.6），**不查 `by_target`**：
    GSI 最終一致，剛寫入的邊可能還看不到。
    """
    version_key = version_pk(version_id)
    sort_key = edge_sk("APPLIED_TO", version_key)
    found: list[str] = []
    problems: list[str] = []
    for row in repository.scan_entity("RULE", meta_only=False):
        if str(row.get("SK", "")) != sort_key:
            continue
        if str(row.get("target", "")) != version_key:
            problems.append(f"APPLIED_TO 邊的 target 與 SK 不一致：{str(row.get('PK', ''))}")
            continue
        found.append(parse_pk(str(row["PK"]))[1])
    problems += [f"規則 {rule_id} 缺少 APPLIED_TO 邊" for rule_id in rules_applied
                 if rule_id not in found]
    problems += [f"多出 APPLIED_TO 邊：規則 {rule_id} 不在 rules_applied" for rule_id in found
                 if rule_id not in rules_applied]
    return problems


def _extra_step_problems(version_id: str, steps: Sequence[StepDraft],
                         repository: Repository) -> list[str]:
    """基表裡不可以有 S3 全文以外的 STEP item：多出來的步驟同樣讓版本不完整。

    缺的步驟由 `_step_edge_problems`（該步 0 條邊）抓；這裡只抓多的——上一版留下的第 5 步
    會跟著這一版一起被 `get_steps` 讀出來、一起發布出去，全文卻沒有它。應有步驟的權威
    是 S3 全文（設計 §10、D-39），所以比較的基準是 `parse_markdown().steps` 的編號集合。
    """
    expected = {step.number for step in steps}
    extra = sorted({item.number for item in repository.get_steps(version_id)} - expected)
    return [f"多出全文沒有的 STEP item：第 {number} 步" for number in extra]


def _step_edge_problems(version_id: str, steps: Sequence[StepDraft],
                        repository: Repository) -> list[str]:
    """每一步都要恰好一條 `REFERENCES` 邊，`target` 等於 SK 終點，而且該 Feature 真的存在。

    「恰好一條」是 D05 在寫入端的最後一道確認：零條代表這一步根本沒寫出來，兩條代表同一步
    引用了多個 Feature，兩種都不可保存（`建立教學版本` Rule 9）。`target` 與 SK 終點不一致
    時停在這裡、不自動修正——寫壞的邊由 Phase 28 的維護批次處理。
    """
    problems: list[str] = []
    for step in steps:
        rows = repository.query_pk(step_pk(version_id, step.number), consistent=True)
        if len(rows) != 1:
            problems.append(f"第 {step.number} 步應恰好一條引用邊，實際 {len(rows)} 條")
            continue
        sort_key, target = str(rows[0].get("SK", "")), str(rows[0].get("target", ""))
        if not target.startswith("FEATURE#") or sort_key != _expected_sk("REFERENCES", target):
            problems.append(f"第 {step.number} 步的 SK 與 target 不一致：{sort_key}")
        elif repository.get_feature(parse_pk(target)[1]) is None:
            problems.append(f"第 {step.number} 步引用的 Feature 不存在：{target}")
    return problems


def _missing_parts(version_id: str, repository: Repository) -> list[str]:
    """回缺漏明細（空 list 代表完整）；module-private，不是跨模組 public API。

    **應有步驟的權威是 S3 全文**（設計 §10、D-39）：VERSION item 上沒有、也不可以有
    `step_count`（strict 模型只收模型欄位加保留屬性），所以步驟清單一律由
    `parse_markdown(全文).steps` 推得。全文讀不回來時後面的核對都沒有意義，直接返回。

    **全部用完整 PK 的 `query_pk(..., consistent=True)` 或基表一致 `scan_entity`**，不查最終
    一致的 `by_target`：剛寫入的邊在 GSI 裡可能還看不到，用它核對會誤判「關係不完整」，
    或更糟地把別人的舊資料當成本版的邊而誤判「完整」。

    **「不缺」與「不多」都要驗。** 只驗缺漏時，多出來的 STEP item、指向本版卻不在
    `rules_applied` 裡的 `APPLIED_TO` 邊、以及第二條 `SUPERSEDES` 都會安靜通過，
    讓 Phase 24 發布出一份「權威欄位與邊互相矛盾」的版本。
    """
    version = repository.get_version(version_id)
    if version is None:
        return [f"找不到 VERSION item {version_id}"]
    slug, number = parse_version_id(version_id)
    md_key, df_key = markdown_key(slug, number), diff_key(slug, number)
    version_key = version_pk(version_id)
    problems = [f"找不到 TUTORIAL item {slug}"] if repository.get_tutorial(slug) is None else []
    if version.s3_key != md_key:
        problems.append(f"s3_key 應為 {md_key}，實際 {version.s3_key}")
    body = repository.get_object(md_key)
    if body is None:
        return problems + [f"缺少 S3 全文 {md_key}"]
    if not repository.object_exists(df_key):
        problems.append(f"缺少 S3 差異檔 {df_key}")
    steps = parse_markdown(body.decode("utf-8")).steps
    try:
        problems += _step_edge_problems(version_id, steps, repository)
        problems += _extra_step_problems(version_id, steps, repository)
        expected_base = [] if version.supersedes is None else [version_pk(version.supersedes)]
        problems += _exact_edge_problems(repository, version_key, "SUPERSEDES", expected_base)
        problems += _applied_to_problems(version_id, version.rules_applied, repository)
    except ValueError as error:
        # 鍵或 item 損壞（`parse_step_pk`、`parse_pk`，以及 pydantic 的 `ValidationError`——
        # 它也是 `ValueError`）。收斂成一條「問題」而不是往外丟：關卡的答案只有齊全／不齊全。
        problems.append(f"關係資料損壞，無法核對：{error}")
    return problems


# --- 9. 教學退役與後繼導向 ---------------------------------------------------

RETIRED_NOTICE = "此教學已退役，內容僅供歷史查閱。"
"""公開頁**唯一**的過期說明（00A §6.6）。

刻意不含退役原因：`reason` 是 `release:<release_id>` 這種上游識別碼，設計 §13 把它列為
私有；讀者需要的資訊只有「這篇過期了、可以改看哪一篇」（F19）。`site.py` 與 Phase 57 的
完整退役頁都 `import` 這個常數，不各自抄一份字面值，改字只改這一處。
"""


def resolve_successor(slug: str, successor: str | None, *,
                      repository: Repository) -> str | None:
    """把「維護者填的後繼」收斂成「可以公開導向的後繼」；任何一關不過回 `None`，**不丟例外**。

    四項檢查的固定順序（設計 §8.4）：

    ```text
    None 或等於自己 -> None            自我導向會讓讀者原地打轉
    查不到 Tutorial -> None            指向不存在的教學＝壞連結
    status != active -> None           已退役的後繼只會再把讀者推一次
    current_version is None -> None    還沒有任何已發布版本＝讀者看不到內容
    沿 successor 往下走遇到重複節點 -> None
    ```

    **回 `None` 不是失敗**：F19 明訂「找不到合法後繼時保持空值，不能阻擋退役」，
    所以這裡的每一關都只是「不導向」，由 `retire_tutorial` 照常把教學退役掉。

    鏈走訪用 `visited` 而不是固定跳數上限：`visited` 直接描述「不形成循環」這件事，
    也順便擋掉 `A -> B -> C -> B` 這種**不含起點**的環。走到 `None` 就停；
    中途某一節點查不到時同樣回 `None`——鏈斷掉就無法證明它不成環，不放行比較安全。
    """
    if successor is None or successor == slug:
        return None
    target = repository.get_tutorial(successor)
    if target is None or target.status != TutorialStatus.ACTIVE:
        return None
    if target.current_version is None:
        return None
    visited = {slug, successor}
    cursor = target.successor
    while cursor is not None:
        if cursor in visited:
            return None
        visited.add(cursor)
        following = repository.get_tutorial(cursor)
        if following is None:
            return None
        cursor = following.successor
    return successor


def retire_tutorial(
    slug: str,
    *,
    reason: str,
    successor: str | None,
    repository: Repository,
    now: datetime,
) -> Tutorial:
    """把一篇教學標記為 `retired`，**只改 `TUTORIAL` metadata 的兩個欄位**。

    ```text
    reason 去頭尾後為空 ---------------------> PermanentError（沒有原因不准退役）
    to_iso(now) --------------------------> naive datetime／帶微秒的在這裡就被擋掉
    找不到 TUTORIAL ----------------------> PermanentError
    resolve_successor ---------------------> 合法就是 slug，不合法是 None（不丟例外）
    status 還不是 retired -----------------> changes["status"] = "retired"
    successor 目前是空的且新值合法 --------> changes["successor"] = 新值
    changes 是空的 ------------------------> 零次 update_meta（冪等），原樣回傳
    ```

    **寫入範圍固定就是這兩個欄位。** `current_version` 不動（讀者仍讀得到最後一個已發布
    版本）、`VERSION`／`STEP`／S3 `.md`／`.diff`／既有 `FEEDBACK` 與邊完全不碰：設計 §8.1
    要求退役保留歷史原文與版本，`retired` 是「不再維護」不是「清理」。

    **`successor` 只在目前為空時寫入。** 已經有值時一律保持原值，不論新值是 `None` 還是
    另一個合法 slug——改後繼是維護者的另一次明確決定，不是再退役一次的副作用。

    **`reason` 與 `now` 只做驗證，不寫進 item。** `Tutorial` 是嚴格模型（00A §3.6、D-40），
    多塞一個 `retired_at`／`retired_reason` 會讓下一次 `get_meta` 直接 `ValidationError`。
    實際紀錄由呼叫端（P52 的 `Retire` task）寫進私有的
    `operations/<operation_id>/retire.json`，它是一個 JSON 陣列，每篇一筆
    `{"slug", "reason", "retired_at", "successor"}`。

    `update_meta` 的 `expected_revision` 取自 `revision_of`（D-27，owner 是 Phase 06）。
    revision 不符代表有人在「讀 revision」與「寫入」之間改了這一篇，轉成 `TransientError`
    交給 ASL 的 Task Retry 重跑整段，不靜默覆蓋別人的修改。
    """
    if not reason.strip():
        raise PermanentError("退役必須帶原因，交給呼叫端寫進 operation 紀錄")
    to_iso(now)
    pk = tutorial_pk(slug)
    tutorial = repository.get_tutorial(slug)
    if tutorial is None:
        raise PermanentError(f"找不到教學 {slug}")
    chosen = resolve_successor(slug, successor, repository=repository)
    changes: dict[str, DynamoValue] = {}
    if tutorial.status != TutorialStatus.RETIRED:
        changes["status"] = TutorialStatus.RETIRED.value
    if chosen is not None and tutorial.successor is None:
        changes["successor"] = chosen
    if changes:
        try:
            repository.update_meta(pk, changes, expected_revision=repository.revision_of(pk))
        except CoordinationError as error:
            raise TransientError(f"{slug} 在退役寫入前有人同時改過，請重試") from error
    retired = repository.get_tutorial(slug)
    if retired is None:
        raise PermanentError(f"{slug} 在退役寫入後讀不到，停止")
    return retired
