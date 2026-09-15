"""三份 ASL 快照的靜態檢查（Phase 59 Task 3）：兩條 Retry、一條 Catch、`PipelineFailed` 終點。

```bash
uv run python -m infra.scripts.check_asl                 # 掃 infra/stepfunctions/*/v*.json
uv run python -m infra.scripts.check_asl <path> [...]    # 只檢查指定的定義
```

這支腳本**包裝** Phase 29 的 `assert_safe_asl`，不重寫它的結構規則（`StartAt` 在同層、
`Choice` 要有 `Default`、Catch 的 `Next` 要指到同層 `Fail`）：那一份才是部署路徑真正用的
守門，兩份規則分家遲早分岔。本模組自己做的是它做不到的三件事：

1. **收齊全部問題**。`assert_safe_asl` 在第一個問題就丟 `PermanentError`，改一次只看得到
   一個錯；`check_asl_document` 走完所有 Task（含 `Map` 的 `ItemProcessor`／`Iterator` 與
   `Parallel` 的 `Branches`）再把 `assert_safe_asl` 的訊息當最後一筆追加。
2. **逐字比對 D-53 的第二條 retrier**（`LAMBDA_SERVICE_ERRORS`）。`assert_safe_asl` 比對整個
   `RETRY` 前綴，所以第二條不見時它的訊息是「前 2 條 Retry 不是固定參數」；這裡另外指名
   `Lambda.ServiceException`，看訊息就知道少的是哪一類。
3. **Catch 的終點名稱**。`assert_safe_asl` 只要求導向同層任何一個 `Fail`；本檢查要求就是
   `PipelineFailed`（00A §6.9、D-15）。

掃不到任何檔案一律回非 0 並印「找不到 ASL 定義」，**不得靜靜回 0**：三份定義由 P41／P48／
P52 建立，缺檔代表前置沒到位，靜靜通過會讓 CI 以為檢查過了。
"""

import json
import sys
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from training_kb.errors import PermanentError
from training_kb.pipelines.asl import CATCH, FAIL_STATE_NAME, RETRY, assert_safe_asl

ASL_ROOT = Path("infra/stepfunctions")
"""預設掃描根目錄；與 `asl.ASL_LOCAL_PATH`（`infra/stepfunctions/{pipeline}/v{number}.json`）
同一套佈局。相對路徑，所以一律從 repo 根目錄執行。"""

ASL_GLOB = "*/v*.json"

LAMBDA_SERVICE_ERRORS: list[str] = [
    "Lambda.ServiceException", "Lambda.AWSLambdaException",
    "Lambda.SdkClientException", "Lambda.TooManyRequestsException",
]
"""D-53 第二條 retrier 的四個錯誤名，逐字對應 `asl.RETRY[1]["ErrorEquals"]`
（`test_check_asl.py` 有一條測試把兩者釘在一起）。"""

NESTED_KEYS = ("ItemProcessor", "Iterator")
"""`Map` 的兩種寫法；`Parallel` 走 `Branches`。"""


def iter_task_states(states: Mapping[str, Any], prefix: str = "") -> Iterator[tuple[str, Any]]:
    """走訪這一層（與所有巢狀層）的 Task state，回 `(完整位置, state)`。

    位置格式與 `assert_safe_asl` 的訊息一致（`Fan.ItemProcessor.Inner`、
    `Split.Branches[0].Left`），兩邊的輸出才對得起來。名稱排序後走訪，讓同一份定義
    每次印出的問題順序固定。
    """
    for name in sorted(states):
        state = states[name]
        if not isinstance(state, dict):
            continue
        where = f"{prefix}{name}"
        if state.get("Type") == "Task":
            yield where, state
        for key in NESTED_KEYS:
            nested = state.get(key)
            if isinstance(nested, dict):
                yield from iter_task_states(nested.get("States") or {}, f"{where}.{key}.")
        branches = state.get("Branches")
        if isinstance(branches, list):
            for index, branch in enumerate(branches):
                if isinstance(branch, dict):
                    yield from iter_task_states(branch.get("States") or {},
                                                f"{where}.Branches[{index}].")


def _expected(items: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """把唯讀常數複製成可比較的 list；`ErrorEquals` 那層 list 也複製，避免共用。"""
    return [{key: list(value) if isinstance(value, list) else value
             for key, value in item.items()} for item in items]


def check_asl_document(doc: Mapping[str, Any], *,
                       fail_state: str = FAIL_STATE_NAME) -> list[str]:
    """回這份定義的所有問題；完全合格回空 list。**只讀不寫，不碰 AWS。**"""
    problems: list[str] = []
    states = doc.get("States") or {}
    for where, state in iter_task_states(states):
        retries = state.get("Retry") or []
        catches = state.get("Catch") or []
        if retries[: len(RETRY)] != _expected(RETRY):
            problems.append(f"Task {where} 的前 {len(RETRY)} 條 Retry 與 Phase 29 的 RETRY 不同")
        if not any(isinstance(item, dict) and item.get("ErrorEquals") == LAMBDA_SERVICE_ERRORS
                   for item in retries):
            problems.append(
                f"Task {where} 缺少涵蓋 Lambda.ServiceException 的 retrier（D-53 第二條）")
        if catches != _expected(CATCH) or catches[0].get("Next") != fail_state:
            problems.append(f"Task {where} 的 Catch 沒有把 States.ALL 導向 {fail_state}")
    destination = states.get(fail_state)
    if not isinstance(destination, dict) or destination.get("Type") != "Fail":
        problems.append(f"缺少 Type=Fail 的 {fail_state} 終點")
    try:
        assert_safe_asl(dict(doc))
    except PermanentError as error:
        problems.append(f"assert_safe_asl：{error}")
    return problems


def main(argv: list[str] | None = None) -> int:
    """檢查指定路徑（或預設 glob）的每一份定義；任何一份不通過就回 1。

    `argv` 為 `None`／空 list 時掃 `infra/stepfunctions/*/v*.json`；掃不到就回 2 並說明，
    與「掃到但不通過」的 1 分開，呼叫端看得出是缺檔還是檢查沒過。
    """
    paths = [Path(item) for item in argv] if argv else sorted(ASL_ROOT.glob(ASL_GLOB))
    if not paths:
        print(f"找不到 ASL 定義：{ASL_ROOT / ASL_GLOB}（三份定義由 P41／P48／P52 建立）")
        return 2
    failed = False
    for path in paths:
        problems = check_asl_document(json.loads(path.read_text(encoding="utf-8")))
        print(f"[{'通過' if not problems else '不通過'}] {path}")
        for item in problems:
            print(f"  - {item}")
        failed = failed or bool(problems)
    return 1 if failed else 0


if __name__ == "__main__":  # pragma: no cover - 命令列進入點
    sys.exit(main())
