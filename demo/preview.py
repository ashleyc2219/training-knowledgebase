"""B 教學的「規則關／開」隔離預覽（Phase 58 Task 2）。

設計 §11.4、§19.2 決策 F47：同一批 B 工單跑兩次寫作，一次**不注入**規則、一次注入
`R-007`，兩份結果都只寫**私有** S3 `demo/previews/<run_id>/`，**不進正式資料**：

```text
        同一批 B（分享摘要）的工單文字
                     |
       +-------------+--------------+
       v                            v
  規則區塊 = 空白              規則區塊 = render_rules_block([rule])
       |                            |
  generate_json(node=preview-off)   generate_json(node=preview-on)
       |                            |
  render_markdown                render_markdown
       v                            v
  demo/previews/<run_id>/off.md  demo/previews/<run_id>/on.md
```

**這支函式寫得到的只有上面那兩個 key。** 它不呼叫 `put_meta`、`put_edge`、`update_meta`、
`allocate_version`、`create_version`，也不回傳任何 `version_id`——所以 TUTORIAL／VERSION
item、`rules_applied`、FEEDBACK 與效果統計都不可能因為預覽而變動
（守門測試：`tests/integration/test_demo_preview.py`，逐 byte 比對整張表）。

`PREVIEW_PREFIX` 落在 Phase 09 `infra/training_kb_data_stack.py:PRIVATE_PREFIXES` 裡，
公開的 `site/*` bucket policy 永遠不會把它露出去。**它是 S3 key 前綴，不是本機路徑**：
本機原始碼目錄 `demo/` 與 S3 的 `demo/previews/` 同名不同層，任何程式都不得拿它組本機路徑。

**O5 BLOCKED**：真實 Bedrock 上這兩次 `generate_json` 會 `ValidationException: Operation
not allowed` → `PermanentError`，原樣往外拋，由呼叫端記成 BLOCKED。這裡**沒有**「模型不可用
就拿預先產好的檔案頂替」的分支；要標示備援是 `demo/view_model.py:Banner.fallback_reason`
的事，而且必須明寫「目前顯示預先執行結果」（設計 §11.5）。
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from training_kb.content import render_markdown
from training_kb.errors import ContentError
from training_kb.models import AuthoringRule, Ticket, TutorialContent
from training_kb.pipelines.ticket import known_features
from training_kb.repository import Repository
from training_kb.rules import render_rules_block
from training_kb.writing.client import Writer
from training_kb.writing.prompts import prompt_write_tutorial
from training_kb.writing.schemas import TutorialDraft

PREVIEW_PREFIX = "demo/previews/"
"""兩份預覽的**私有** S3 key 前綴（已在 Phase 09 的 `PRIVATE_PREFIXES` 內）。"""

PREVIEW_NODES: tuple[str, str] = ("preview-off", "preview-on")
"""兩次 `generate_json` 的 `node`。**一定要不同**：`node` 原樣寫進 `CallTrace`，
`demo/view_model.py:call_breakdown` 靠它把兩次呼叫分開數（Phase 15）。"""

PREVIEW_HEADER = "合成資料示範｜隔離預覽｜不寫入正式教學與統計"
"""兩份檔案固定的第一行（Phase 58 §6）。改字只改這一處。"""

SWITCH_LABELS: tuple[str, str] = ("關閉（off）", "開啟（on）")
CONTENT_TYPE = "text/markdown; charset=utf-8"


@dataclass(frozen=True)
class PreviewResult:
    """一次隔離預覽的結果。

    **刻意沒有 `version_id`**：預覽不建版，回傳它會讓呼叫端以為有正式版本可以連過去。
    `model_calls` 是這次真的送出的生成請求數（關／開各一次，固定 2）。
    """

    run_id: str
    rule_id: str
    off_key: str
    on_key: str
    model_calls: int


def _preview_key(run_id: str, name: str) -> str:
    """`demo/previews/<run_id>/<name>.md`；`run_id` 由呼叫端提供並寫進檔頭。"""
    return f"{PREVIEW_PREFIX}{run_id}/{name}.md"


def _as_content(payload: dict[str, Any]) -> TutorialContent:
    """`generate_json` 回的是 dict，不是模型；這裡是唯一的 `model_validate`（D-02）。

    訊息只放欄位數，**不放模型輸出**（00A §3.8）。
    """
    try:
        return TutorialContent.model_validate(payload)
    except ValidationError as error:
        raise ContentError(f"preview_draft_invalid: {error.error_count()} 個欄位") from error


def _document(content: TutorialContent, *, run_id: str, rule: AuthoringRule | None,
              switch: str, writer: Writer) -> str:
    """檔頭 ＋ `render_markdown` 的全文。

    檔頭除了 `PREVIEW_HEADER`、`run_id` 與規則開關狀態，還寫上 **writer 類別名**：
    O5 BLOCKED 時兩份預覽是假 Writer 產的，人工驗收要能一眼分辨「隔離預覽」與
    「模型未開通」兩件事（Phase 58 §8 的現況核對）。
    """
    rule_id = "（未注入）" if rule is None else rule.rule_id
    header = (f"{PREVIEW_HEADER}\n"
              f"run_id={run_id}｜規則開關={switch}｜規則={rule_id}｜"
              f"writer={type(writer).__name__}\n")
    return f"{header}\n{render_markdown(content)}"


def run_rule_toggle_preview(tickets: Sequence[Ticket], *, rule: AuthoringRule,
                            repository: Repository, writer: Writer,
                            run_id: str) -> PreviewResult:
    """同一批工單跑兩次寫作（規則關／開），只寫兩個私有 key。

    順序固定：`off` 先產生、先寫入，再產生 `on`、寫入。兩個 key 都用
    `put_object(..., if_none_match=True)`（Phase 07 的條件寫入），所以同一個 `run_id`
    重跑會在**第一次寫入**就拿到 `ObjectAlreadyExists`（`PermanentError` 子類）而中止，
    不會蓋掉現場已經展示過的對照檔，也不會白跑第二次模型呼叫。要重跑就換 `run_id`。

    `allowed_features` 由 `known_features(repository)` 唯讀取得（Phase 40 用同一份），
    順序固定所以 prompt 可重現；本函式除了兩個 `put_object` 之外**不做任何寫入**。
    """
    source_text = "\n".join(ticket.text for ticket in tickets)
    features = [feature.feature_id for feature in known_features(repository)]
    operation_id = f"op-demo-preview-{run_id}"
    keys: list[str] = []
    calls = 0
    for node, name, switch, injected in (
            (PREVIEW_NODES[0], "off", SWITCH_LABELS[0], None),
            (PREVIEW_NODES[1], "on", SWITCH_LABELS[1], rule)):
        rules_block = "" if injected is None else render_rules_block([injected])
        system, user = prompt_write_tutorial(source_text, features, rules_block)
        payload = writer.generate_json(system, user, TutorialDraft,
                                       operation_id=operation_id, node=node)
        calls += 1
        body = _document(_as_content(payload), run_id=run_id, rule=injected,
                         switch=switch, writer=writer)
        key = _preview_key(run_id, name)
        repository.put_object(key, body.encode("utf-8"), CONTENT_TYPE, if_none_match=True)
        keys.append(key)
    return PreviewResult(run_id=run_id, rule_id=rule.rule_id, off_key=keys[0],
                         on_key=keys[1], model_calls=calls)
