# Phase 22：Markdown 與 Diff 私有產物實作計畫

> **給實作者：** 依 checkbox 逐步執行；每個 Task 先建立失敗測試，再寫最小實作。執行時使用 `superpowers:executing-plans` 或同等逐項流程。

**目標：** 把已驗證的 `TutorialContent` 變成格式固定、可反解、已轉義的 Markdown 全文與 unified diff，並只以條件寫入放進私有 S3 前綴。

**架構：** `content` 模組負責格式，`Repository` 負責 S3。`render_markdown` 與 `parse_markdown` 互為反函式，所以 Phase 23 可以用 S3 全文重新核對版本內容。公開的 `site/` 只有發布流程能寫，本階段一律拒絕。

**技術：** Python 3.12、標準函式庫 `difflib` 與 `re`、pytest、Phase 07 的 S3 條件寫入。

## 全域限制

- 唯一主來源是 [Training KB 設計 §8.2、§8.3、§9.3、§13](../../design/training-kb.md)。
- 前置為 [Phase 21：教學內容與步驟引用驗證](./21-Phase21-教學內容與步驟引用驗證.md) 與 [Phase 07：S3 物件與關係邊讀寫](./07-Phase07-S3物件與關係邊讀寫.md)。前置未通過時停止。
- 下一階段是 [Phase 23：未發布版本與關係完整寫入](./23-Phase23-未發布版本與關係完整寫入.md)。
- 本階段不寫 DynamoDB、不切 `current_version`、不產生 HTML、不呼叫模型、不刪除任何既有物件；也只能寫 `tutorials/` 前綴，任何往 `site/` 的寫入都是錯誤，不是「還沒放連結所以等於私有」。
- 與本 Phase 有關的 gate：O3 仍待 [Phase 12](./12-Phase12-O3發布切換整合驗證.md) 驗證。即使本階段全綠，也不得宣稱發布故障切點已驗收。以下程式檔均是實作時預計建立或修改。

---

## 1. 你在整體流程的位置

```text
Phase 21 已驗證的 TutorialContent
                 v
  [你在這裡：render_markdown + make_diff]
       |                          |
   v<n>.md 文字               v<n>.diff 文字
       +-------------+------------+
                     v
   put_private_artifact -> tutorials/<slug>/v<n>.md｜.diff
                     v
  Phase 23 寫 VERSION/STEP -> publish 後才進 site/
```

`parse_markdown` 是回程：Phase 23 用它把 S3 全文讀回 `TutorialContent`，核對基表 STEP 是否一致。

## 2. 完成後看得到什麼

`prepare-meeting` 的 v1 與 v2 都是四步，只有第 3 步改寫。`v1.diff` 是 0 位元組（第一版沒有前版可比較）；`v2.diff` 只有兩行變動：

```text
--- tutorials/prepare-meeting/v1.md
+++ tutorials/prepare-meeting/v2.md
@@ -13,7 +13,7 @@
 1. (type=read, feature=Prepare) 開啟行事曆。
 2. (type=click_ui, feature=Prepare) 選擇今天的會議。
-3. (type=click_ui, feature=Prepare) 開啟摘要。
+3. (type=click_ui, feature=Prepare) 在會議頁面右上角選擇 Prepare。
 4. (type=read, feature=Prepare) 確認摘要內容。
```

這是節錄：`---`／`+++`／`@@` 是 unified diff 的固定表頭（`@@` 的行號隨前置條件有幾行而變），以空白開頭的行沒有變動、只是上下文，實際輸出還會帶到 `## Steps` 前後的空行。真正變動的只有開頭 `-` 與 `+` 的那兩行。

## 3. 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| 固定格式 | 每一版都用完全相同的標題與行結構；格式一變，diff 會變成「整篇都改了」。 |
| 反函式 | `parse_markdown(render_markdown(x)) == x`；把全文讀回結構化內容不會失真。 |
| 轉義 | 在使用者或模型文字中的 Markdown 符號前加反斜線，讓它只是字元，不會變成標題或連結。 |
| unified diff | `difflib` 產生的標準差異格式，只列出有變動的行與前後脈絡。 |
| 條件寫入 | S3 `IfNoneMatch="*"`：只有該 key 還不存在時才寫成功，避免盲目覆蓋。 |
| 私有前綴 | `tutorials/`；未發布產物只能放這裡，公開站只讀 `site/`。 |
| F50／D25 這類編號 | 設計文件第 19 節已解決決策的編號：`D` 是資料決策，`F` 是功能決策，查[設計 §19](../../design/training-kb.md) 就能看到原文。 |

## 4. 預計檔案

| 動作 | 路徑 | 責任 |
|---|---|---|
| 修改 | `src/training_kb/content.py` | 轉義、`render_markdown`、`parse_markdown`、`make_diff`、key 與條件寫入。 |
| 測試 | `tests/unit/test_markdown.py`、`tests/integration/test_private_artifacts.py` | 固定格式、轉義、round-trip、diff，以及條件寫入與公開前綴拒絕。 |

## 5. 固定介面

### Consumes

```text
TutorialContent / StepDraft / StepType                                # Phase 03
ContentError(PermanentError)、PermanentError                          # Phase 02
ObjectAlreadyExists(PermanentError)                                   # Phase 07（放在 errors.py）
make_version_id(slug: str, number: int) -> str                        # Phase 20
Repository.put_object(key, body: bytes, content_type: str, *, if_none_match: bool) -> None
Repository.get_object(key: str) -> bytes | None                       # 以上兩個來自 Phase 07
```

`put_object` 在 key 已存在且 `if_none_match=True` 時（S3 回 412）丟 `ObjectAlreadyExists`，併發刪除的 409 才是 `TransientError`，這是 Phase 07 的承諾。`put_private_artifact` **用型別而不是訊息字串**分辨「同 key 已存在」與其他永久失敗。

### Produces

```python
PRIVATE_TUTORIAL_PREFIX: str
PUBLIC_SITE_PREFIX: str
def markdown_key(slug: str, number: int) -> str: ...
def diff_key(slug: str, number: int) -> str: ...
def escape_markdown(text: str) -> str: ...
def unescape_markdown(text: str) -> str: ...
def render_markdown(content: TutorialContent) -> str: ...
def parse_markdown(markdown: str) -> TutorialContent: ...
def make_diff(previous_md: str | None, current_md: str, *, previous_name: str,
              current_name: str) -> str: ...
def put_private_artifact(repository: Repository, key: str, text: str,
                         content_type: str) -> None: ...
```

## 6. 設計細節

全文格式固定如下；`<...>` 是會被替換的內容，其餘每個字元都是常數。**下圖的空行就是檔案裡真的空行**：每個標題與它的內容之間、每個區塊之間都恰好隔一個空行，檔案以一個換行結尾。

```text
# <title>

## Problem

<problem>

## Prerequisites

- <第一項>
- <第二項>

## Steps

1. (type=click_ui, feature=Prepare) <第一步文字>
2. (type=read, feature=Prepare) <第二步文字>

## Expected Outcome

<expected_outcome>
```

**本計畫選擇：每個欄位只有一行。** `title`、每個 prerequisite、每步文字、`problem` 與 `expected_outcome` 都不得含換行，否則 `render_markdown` 丟 `ContentError`。這讓 `parse_markdown` 成為精確反函式，也讓 diff 的最小變更單位就是「一步」。多段落排版留給 Phase 57 的 HTML renderer。

**轉義與反轉義必須一對一。** `escape_markdown` 只在特定字元前插入一個反斜線；`unescape_markdown` 只把反斜線後的下一個字元原樣取出，結尾落單的反斜線丟 `ContentError`。因此 `unescape_markdown(escape_markdown(x)) == x` 對任何字串成立。要轉義的是行內符號 `` \ ` * _ [ ] < > # | ( ) ``（`#` 讓使用者文字無法偽造 `# `／`## ` 標題，`( )` 讓步驟行的 `feature=...)` 不會被提前關閉），再加上行首的 `-`、`+` 與「數字後接句點」這兩種會開啟清單或編號的寫法。`>` 已在行內清單裡，不必再處理一次行首；`feature_id` 則額外禁止括號，讓解析沒有歧義。

**v1 的 diff 是空的，但檔案要存在。** F50 的答案是 C：`make_diff(None, ...)` 回 `""`，Phase 23 仍寫出 0 位元組的 `v1.diff`。畫面上「第一版，沒有前一版可比較」由 `supersedes is None` 判斷，不是靠 diff 檔是否為空（Phase 57）。

## 7. TDD Tasks

`four_step_content(**overrides)` 與 [Phase 21](./21-Phase21-教學內容與步驟引用驗證.md) 同名同語意，寫在 `tests/unit/test_markdown.py` 裡：預設 `title="準備會議"`，四步編號 1–4、`type` 依序 `read`／`click_ui`／`click_ui`／`read`、`feature_id` 都是 `Prepare`、第 3 步文字 `開啟摘要。`。本 Phase 的所有 override 都是合法值，不需要 `model_construct`。整合測試的 `repository` fixture 沿用 [Phase 06](./06-Phase06-Repository-Metadata與實體讀寫.md) 建立、[Phase 07](./07-Phase07-S3物件與關係邊讀寫.md) 加上 moto bucket 的 `tests/integration/conftest.py`，名稱一律是 `repository`，不要另外取名。

### Task 1：固定格式、轉義與精確 round-trip

- [ ] **Step 1：建立失敗測試**

```python
def test_render_uses_fixed_headings_and_step_prefix():
    markdown = render_markdown(four_step_content())
    assert markdown.splitlines()[0] == "# 準備會議"
    assert "## Expected Outcome" in markdown and "3. (type=click_ui, feature=Prepare) " in markdown

def test_user_text_cannot_inject_markdown():
    markdown = render_markdown(four_step_content(title="# 假標題 <script>", step3_text="- 假清單"))
    assert markdown.count("\n# ") == 0 and "\\<script\\>" in markdown

@pytest.mark.parametrize("title", ["準備會議", "# 假標題", "1. 假步驟", "反斜線\\結尾字"])
def test_round_trip_restores_content(title):
    content = four_step_content(title=title)
    assert parse_markdown(render_markdown(content)) == content
```

另外加兩個：`test_broken_markdown_is_rejected` 把 `## Expected Outcome` 改成 `## Outcome` 後，`parse_markdown` 必須丟 `ContentError` 且訊息含「缺少區塊」；`test_model_limit_becomes_content_error` 把步驟行的編號從 `1.` 改成 `2.`（違反 Phase 03 的連號限制），必須丟 `ContentError` 而不是 pydantic 的 `ValidationError`。

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_markdown.py -q
```

預期：FAIL，訊號包含 `cannot import name 'render_markdown'`。

- [ ] **Step 3：建立轉義與反轉義**

```python
_MD_SPECIALS = frozenset("\\`*_[]<>#|()")

def escape_markdown(text: str) -> str:
    escaped = "".join(f"\\{ch}" if ch in _MD_SPECIALS else ch for ch in text)
    if escaped[:1] in ("-", "+"):
        return "\\" + escaped
    head, dot, rest = escaped.partition(".")
    if dot and head.isdigit():
        return f"{head}\\.{rest}"
    return escaped

def unescape_markdown(text: str) -> str:
    if re.search(r"(?<!\\)(?:\\\\)*\\$", text):
        raise ContentError("Markdown 以落單的反斜線結尾")
    return re.sub(r"\\(.)", r"\1", text)
```

- [ ] **Step 4：建立 render 與 parse 並跑完整檔案**

```python
_SECTIONS = ("Title", "Problem", "Prerequisites", "Steps", "Expected Outcome")
_STEP_LINE = re.compile(r"^(\d+)\. \(type=([a-z_]+), feature=([^)]*)\) (.*)$")

def render_markdown(content: TutorialContent) -> str:
    steps = [f"{s.number}. (type={s.type}, feature={_one_line('feature_id', s.feature_id)}) "
             f"{_one_line('step.text', s.text)}" for s in content.steps]
    items = "\n".join(f"- {_one_line('Prerequisites', i)}" for i in content.prerequisites)
    blocks = [f"# {_one_line('Title', content.title)}",
              "## Problem\n\n" + _one_line("Problem", content.problem),
              "## Prerequisites\n\n" + items,
              "## Steps\n\n" + "\n".join(steps),
              "## Expected Outcome\n\n" + _one_line("Expected Outcome", content.expected_outcome)]
    return "\n\n".join(blocks) + "\n"
```

`_one_line(label, value)` 先拒絕 `\n`、`\r`（`feature_id` 另外拒絕括號），再回傳 `escape_markdown(value)`；`label` 只用來組錯誤訊息。回程是三個函式：

```python
def _split_sections(markdown: str) -> dict[str, list[str]]:
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

def _only_line(sections: dict[str, list[str]], name: str) -> str:
    lines = sections[name]
    if len(lines) != 1:
        raise ContentError(f"{name} 區塊必須恰好一行，實際 {len(lines)} 行")
    return unescape_markdown(lines[0])

def parse_markdown(markdown: str) -> TutorialContent:
    sections = _split_sections(markdown)
    try:
        steps = []
        for line in sections["Steps"]:
            match = _STEP_LINE.match(line)
            if match is None:
                raise ContentError(f"步驟格式不符：{line}")
            steps.append(StepDraft(number=int(match[1]), type=match[2],
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
    except ValidationError as exc:     # 模型層的限制（步驟連號、type 合法、區塊非空）也是內容錯
        raise ContentError(f"Markdown 內容不符 TutorialContent 限制：{exc.error_count()} 個欄位") from exc
```

先判斷 `## ` 再判斷 `# `，否則 `## Problem` 會被誤認成標題行；空行一律丟掉，所以 render 的空行數量不影響解析。`StepDraft`／`TutorialContent` 是 Phase 03 的嚴格模型，遇到不合法內容丟的是 pydantic 的 `ValidationError`；**呼叫端（Phase 23）只認得 Phase 02 的錯誤契約**，所以這裡一律轉成 `ContentError`（`PermanentError` 子類），不讓第三方例外型別外洩（`from pydantic import ValidationError`）。執行 `uv run pytest tests/unit/test_markdown.py -q`，預期五個測試 PASS。

- [ ] **Step 5：提交**

```bash
git add src/training_kb/content.py tests/unit/test_markdown.py
git commit -m "feat(content): 固定格式全文與可反解的轉義"
```

### Task 2：unified diff 與 v1 空 diff

- [ ] **Step 1：建立失敗測試**

```python
def test_first_version_has_empty_diff():
    assert make_diff(None, "# 準備會議\n", previous_name="", current_name="v1.md") == ""

def test_diff_only_contains_changed_step():
    previous = render_markdown(four_step_content())
    current = render_markdown(four_step_content(step3_text="在會議頁面右上角選擇 Prepare。"))
    diff = make_diff(previous, current, previous_name="v1.md", current_name="v2.md")
    changed = [line for line in diff.splitlines()
               if line[:1] in {"-", "+"} and line[:3] not in {"---", "+++"}]
    assert len(changed) == 2
    assert "開啟摘要" in changed[0] and "右上角" in changed[1]
```

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_markdown.py -q
```

預期：FAIL，訊號包含 `cannot import name 'make_diff'`。

- [ ] **Step 3：建立最小實作**

```python
def make_diff(previous_md, current_md, *, previous_name, current_name) -> str:
    if previous_md is None:
        return ""
    lines = difflib.unified_diff(
        previous_md.splitlines(), current_md.splitlines(),
        fromfile=previous_name, tofile=current_name, lineterm="",
    )
    text = "\n".join(lines)
    return f"{text}\n" if text else ""
```

- [ ] **Step 4：補上「內容完全相同」案例並跑綠燈**

同一份全文比同一份全文也回 `""`；這與 v1 的空 diff 意義不同，所以 Phase 57 用 `supersedes is None` 判斷第一版。執行 `uv run pytest tests/unit/test_markdown.py -q`，預期整檔 PASS。

- [ ] **Step 5：提交**

```bash
git add src/training_kb/content.py tests/unit/test_markdown.py
git commit -m "feat(content): 產生與前版的 unified diff"
```

### Task 3：私有 key 與條件寫入

- [ ] **Step 1：建立失敗測試**

`test_keys_are_private` 是純字串比對，放 `tests/unit/test_markdown.py`；另外兩個要真的寫 S3，放 `tests/integration/test_private_artifacts.py`。

```python
# tests/unit/test_markdown.py
def test_keys_are_private():
    assert markdown_key("prepare-meeting", 2) == "tutorials/prepare-meeting/v2.md"
    assert diff_key("prepare-meeting", 2) == "tutorials/prepare-meeting/v2.diff"
    assert not markdown_key("prepare-meeting", 2).startswith(PUBLIC_SITE_PREFIX)

# tests/integration/test_private_artifacts.py
def test_public_prefix_refused(repository):
    with pytest.raises(ContentError, match="私有前綴"):
        put_private_artifact(repository, "site/prepare-meeting/v2.md", "x", "text/markdown")

def test_same_key_same_content_is_idempotent(repository):
    key, kind = markdown_key("prepare-meeting", 2), "text/markdown; charset=utf-8"
    put_private_artifact(repository, key, "# 準備會議\n", kind)
    put_private_artifact(repository, key, "# 準備會議\n", kind)
    with pytest.raises(ContentError, match="內容不同"):
        put_private_artifact(repository, key, "# 別的\n", kind)
```

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_markdown.py tests/integration/test_private_artifacts.py -q
```

預期：FAIL，訊號包含 `cannot import name 'put_private_artifact'`。

- [ ] **Step 3：建立最小實作**

```python
PRIVATE_TUTORIAL_PREFIX = "tutorials/"
PUBLIC_SITE_PREFIX = "site/"

def _artifact_key(slug: str, number: int, suffix: str) -> str:
    make_version_id(slug, number)
    return f"{PRIVATE_TUTORIAL_PREFIX}{slug}/v{number}{suffix}"

def put_private_artifact(repository, key: str, text: str, content_type: str) -> None:
    if not key.startswith(PRIVATE_TUTORIAL_PREFIX) or key.startswith(PUBLIC_SITE_PREFIX):
        raise ContentError(f"未發布產物只能寫私有前綴 tutorials/：{key}")
    body = text.encode("utf-8")
    try:
        repository.put_object(key, body, content_type, if_none_match=True)
    except ObjectAlreadyExists:
        if repository.get_object(key) != body:
            raise ContentError(f"S3 已有同一個 key 但內容不同，不覆寫：{key}") from None
```

`markdown_key`／`diff_key` 各自委派 `_artifact_key`，副檔名分別是 `.md` 與 `.diff`。第一行的 `make_version_id(slug, number)` 只當守門員：`slug` 含 `@`／`#` 或 `number < 1` 時它丟 `ValueError`，避免產出 `tutorials/a@v1/v0.md` 這種對不上版本的 key；回傳值刻意不用，因為 key 的形狀是 `<slug>/v<n>`。只攔 `ObjectAlreadyExists`（S3 412）也是重點：`PermanentError` 的其他子類別（例如沒設定 bucket）要原樣往上拋，不能被誤判成「同操作重送」。

- [ ] **Step 4：以 moto 驗證條件寫入語意，並確認器材真的會擋**

斷言：第一次寫成功；同 key 同內容第二次不丟例外也不改內容；同 key 不同內容丟 `ContentError`；`site/` 前綴永遠被拒。

**先確認 Phase 07 的器材能力探針已通過。** 舊版 moto 不執行 `IfNoneMatch`（[getmoto/moto#8091](https://github.com/getmoto/moto/issues/8091)），這時第二次 `put_object` 會成功、`ObjectAlreadyExists` 不會丟出，「同 key 不同內容」的測試會安靜地變成**覆寫舊產物**。正確處理是升級 moto 並把版本寫進測試報告；不可改成「先 `object_exists` 再寫」的假條件，也不可刪掉斷言。無法升級時把本 Task 標記 BLOCKED，不往 Phase 23 前進。

執行 `uv run pytest tests/unit/test_markdown.py tests/integration/test_private_artifacts.py -q`，預期全部 PASS；moto PASS 只代表本機模擬，O3 仍維持未通過。

- [ ] **Step 5：提交**

```bash
git add src/training_kb/content.py tests/unit/test_markdown.py tests/integration/test_private_artifacts.py
git commit -m "feat(content): 以條件寫入保存私有版本產物"
```

## 8. 驗收矩陣

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy | 四步內容，且只改第 3 步；v1 則 `previous_md=None` | 標題固定、步驟行為 `<n>. (type=..., feature=...) <text>`；diff 只有兩行變動，v1 回 `""` 但仍寫出 0 位元組 `v1.diff`。 |
| Failure | 標題含 `# `、`<script>` 或行首 `- `；或欄位含換行、步驟行不符 pattern、少一個區塊、key 是 `site/...` | 前者轉義後不產生新標題或清單；後者一律 `ContentError`，不產生殘缺內容，S3 也沒有任何寫入。 |
| Boundary | 同 key 重寫相同／不同內容 | 前者視為儲存重試通過，後者丟 `ContentError` 並保留既有物件。 |

人工驗收：實際下載 `v1.md` 與 `v2.diff`，用肉眼確認格式與變更行，再把 `v2.md` 餵進 `parse_markdown` 比對原始 `TutorialContent`；不能只看測試顯示 PASS。

## 9. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| 每一版 diff 都顯示整篇改變 | 格式不固定（步驟前綴或空行數量會變） | 停止發布，把格式改回固定樣板。 |
| 使用者留言在頁面變成標題 | 沒有轉義就寫進 Markdown | 補 `escape_markdown`；已產生的公開頁視為缺陷，需重新產出。 |
| 未發布全文出現在公開站 | 寫入時用了 `site/` 前綴 | 立即停止並移除；不可用「沒有連結」當作未公開。 |
| round-trip 後少一步 | `parse_markdown` 不是精確反函式 | 停止 Phase 23 核對，先修正解析。 |
| 重試覆寫舊產物 | 用無條件 `put_object`，或 moto 太舊沒實作 `IfNoneMatch` | 改條件寫入並比對內容，不同就丟 `ContentError`；先跑 Phase 07 的器材能力探針。 |
| 把所有 `PermanentError` 都當成「同操作重送」 | `except PermanentError` 攔太寬 | 只攔 `ObjectAlreadyExists`，其餘往上拋。 |

## 10. 來源與 Rule 對照

以下兩條的 primary Phase 都是本 Phase（Phase 12 的 O3 切點觀察與 Phase 57 的 v1 空 diff 文案只是相關），對照表見 [00B 需求覆蓋對照](./00B-需求覆蓋對照.md)。

- [建立教學版本.feature](../../spec/features/建立教學版本.feature)
  - Rule 5：「每個版本的完整內容儲存在 `tutorials/<slug>/v<n>.md`」→ Task 3 的 `test_keys_are_private`（`tests/unit/test_markdown.py`）與 `tests/integration/test_private_artifacts.py` 直接斷言。
  - Rule 7：「與前版的 diff 儲存在 `tutorials/<slug>/v<n>.diff`」→ `tests/unit/test_markdown.py` 的 `diff_key` 與 `test_first_version_has_empty_diff` 直接斷言；v1 空檔依 F50。
- 設計 §8.2、§8.3：S3 全文與 diff 的寫入順序、v1 空 diff、未發布不可公開，以及同 key 已存在時先核對再決定，不盲目重寫。
- 設計 §9.3、§13：`tutorials/` 私有、`site/` 只由發布流程寫入，且只有可公開的示範教學能進 `site/`。
- [Python difflib.unified_diff](https://docs.python.org/3/library/difflib.html#difflib.unified_diff) 提供 `lineterm=""` 搭配 `splitlines()` 的用法；[S3 條件寫入](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html) 的 `IfNoneMatch="*"` 在物件已存在時回 412，對應 Phase 07 的 `ObjectAlreadyExists`（併發刪除的 409 才是 `TransientError`）。

## 11. 完成清單

- [ ] 八個公開函式與兩個前綴常數的名稱、簽名符合本文件；全文格式與固定樣板逐字一致。
- [ ] 轉義與反轉義互為反函式，含落單反斜線的錯誤案例。
- [ ] `parse_markdown(render_markdown(x)) == x` 有多組參數化測試；缺區塊與壞步驟行被拒絕。
- [ ] v1 回空 diff 且仍寫出 `v1.diff`；只改一步時 diff 只有兩行變動；`site/` 前綴被拒。
- [ ] 同 key 相同內容冪等、不同內容失敗；`put_private_artifact` 只攔 `ObjectAlreadyExists`，不攔整個 `PermanentError`。
- [ ] Phase 07 的 moto `IfNoneMatch` 能力探針已通過並記錄版本，條件寫入不是假綠燈。
- [ ] 單元與整合測試已實際執行並保存輸出，且沒有把綠燈說成 O3 發布 gate 已通過。
