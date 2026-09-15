"""修正波（final review C#3）：兩個故障注入開關對「正式環境」與「打錯的值」答案一致。

專案有兩個互補的注入開關：`faults.maybe_fail`（library 路徑上的五個切點）與
`pipelines.common.maybe_fail_task`（Lambda Task 層的 `TKB_FAULT_TASK`）。它們原本各寫
一份判斷：

```text
faults.active_fault        TKB_ENV.strip().lower() == "prod"  ->  不注入
common.maybe_fail_task     TKB_ENV == "prod"                  ->  不注入   <- 會漏擋
faults.active_fault        打錯切點名 -> PermanentError
common.maybe_fail_task     打錯值     -> 靜靜當成沒開          <- 演練白跑
```

本檔守的就是這兩條分岔被補起來：`faults.is_production` 是**唯一**的正式環境判斷，
`TKB_FAULT_TASK` 打錯一律 `PermanentError`。
"""

import pytest

from training_kb import faults
from training_kb.errors import PermanentError, TransientError
from training_kb.pipelines.common import FAULT_TASK_ENV, maybe_fail_task

PROD_SPELLINGS = ("prod", "PROD", " prod", "prod ", " Prod ")
"""同一個意思的五種寫法；正式環境的保險寧可誤擋，不可因大小寫或空白漏擋。"""


@pytest.mark.parametrize("value", PROD_SPELLINGS)
def test_is_production_accepts_every_spelling(value: str) -> None:
    assert faults.is_production({faults.ENV_NAME_ENV: value}) is True


@pytest.mark.parametrize("value", ("", "dev", "staging", "production-like"))
def test_is_production_rejects_everything_else(value: str) -> None:
    assert faults.is_production({faults.ENV_NAME_ENV: value}) is False


@pytest.mark.parametrize("value", PROD_SPELLINGS)
def test_both_switches_agree_on_production(value: str) -> None:
    """Given 同一份環境變數，Then 兩個開關都不注入（原本 Task 層只認逐字 `prod`）。"""
    env = {faults.ENV_NAME_ENV: value, faults.FAULT_ENV: "s3_after_md",
           FAULT_TASK_ENV: "ticket-analysis:name_gap"}

    assert faults.active_fault(env) is None
    assert maybe_fail_task("ticket-analysis", "name_gap", env) is None


@pytest.mark.parametrize("value", ("name_gap", "ticket-analysis", "a:b:c", ":name_gap",
                                   "ticket-analysis:"))
def test_a_malformed_fault_task_value_fails_loudly(value: str) -> None:
    """Given `TKB_FAULT_TASK` 不是 `<pipeline>:<task>`，Then `PermanentError`。

    靜靜當成「沒有注入」會讓一次復原演練白跑，事後也分不出是開關沒生效還是流程
    真的沒失敗——與 `faults.active_fault` 對打錯切點名的處理同一個理由。
    """
    with pytest.raises(PermanentError, match=FAULT_TASK_ENV):
        maybe_fail_task("ticket-analysis", "name_gap", {FAULT_TASK_ENV: value})


def test_an_unknown_pipeline_in_the_fault_task_value_fails_loudly() -> None:
    with pytest.raises(PermanentError, match="pipeline"):
        maybe_fail_task("ticket-analysis", "name_gap",
                        {FAULT_TASK_ENV: "ticket-analysys:name_gap"})


def test_a_wellformed_value_still_only_hits_its_own_task() -> None:
    env = {FAULT_TASK_ENV: "ticket-analysis:name_gap"}

    assert maybe_fail_task("ticket-analysis", "ensure_embedding", env) is None
    with pytest.raises(TransientError):
        maybe_fail_task("ticket-analysis", "name_gap", env)


def test_an_unset_switch_is_not_an_error() -> None:
    assert maybe_fail_task("ticket-analysis", "name_gap", {}) is None
    assert maybe_fail_task("ticket-analysis", "name_gap", {FAULT_TASK_ENV: ""}) is None
