"""Phase 42 Task 1：`validate_feedback`／`validate_view` 的純欄位契約（不碰 AWS）。

固定匯入的第一關只做欄位判斷：未知欄位、必填缺值、`rating` 嚴格整數、`ts` 形狀、
`user` 格式。圖譜查詢、退役判斷與去重都在 `import_feedback`／`import_view`，不在這裡。

三個共用的判斷一律呼叫既有函式，本檔連帶把它們的行為釘在固定匯入這條路徑上：

```text
ts    ingress._parsed_ts            aware ISO-8601 整秒；naive／格式錯／帶微秒都拒絕
user  source_ids.stable_user_from_import   ^[a-z0-9_-]{2,64}$
缺欄位 ingress.missing_nonempty_strings     一次回報所有缺的欄位
```

`rating` 的嚴格整數在 `models.Feedback` 已經有 `rating_is_strict_int`；入口自己再判斷一次
是為了吐 `IngressError(fields=("rating",))` 而不是 pydantic `ValidationError`（00A §6.8）。
"""

from datetime import UTC, datetime

import pytest

from training_kb.errors import IngressError
from training_kb.ingress import FEEDBACK_FIELDS, VIEW_FIELDS, validate_feedback, validate_view

NOW = datetime(2026, 9, 14, 3, 0, tzinfo=UTC)
FEEDBACK = {"id": "f_12", "tutorial_version": "prepare-meeting@v1", "rating": 2, "user": "u_01"}
VIEW = {"tutorial_version": "prepare-meeting@v1", "user": "u_01", "ts": "2026-08-02T09:00:00Z"}


def _without(payload: dict[str, object], key: str) -> dict[str, object]:
    return {name: value for name, value in payload.items() if name != key}


# --- 欄位清單本身 -------------------------------------------------------------


def test_the_two_field_sets_are_exactly_the_contract() -> None:
    """Given 00A §6.8 的欄位表／When 讀兩個 frozenset／Then 逐字相同。

    `project_id` 在兩張表裡但**不是**模型欄位：它只用來替操作紀錄分組（`DEFAULT_PROJECT_ID`）。
    """
    assert FEEDBACK_FIELDS == frozenset(
        {"id", "tutorial_version", "rating", "category", "comment", "user", "ts", "project_id"})
    assert VIEW_FIELDS == frozenset({"tutorial_version", "user", "ts", "project_id"})


# --- rating（`COL` Rule 3）----------------------------------------------------


@pytest.mark.parametrize("bad_rating", [True, False, "4", 3.5, 0, 6, None])
def test_rating_must_be_a_strict_integer_between_one_and_five(bad_rating: object) -> None:
    """Given rating 不是 1..5 的嚴格整數／When 驗證／Then `IngressError(("rating",))`。

    `True` 與 `False` 是 `int` 的子類別，`isinstance(True, int)` 為真，所以判斷用
    `type(value) is int`；`"4"` 與 `3.5` 也一律拒絕（設計 §7.1、文件 §9 第一列）。
    """
    with pytest.raises(IngressError) as error:
        validate_feedback({**FEEDBACK, "rating": bad_rating}, now=NOW)
    assert error.value.fields == ("rating",)


@pytest.mark.parametrize("rating", [1, 2, 3, 4, 5])
def test_every_rating_inside_the_range_is_accepted(rating: int) -> None:
    """Given 1..5 的整數／When 驗證／Then 原值進 `Feedback`，沒有被轉型。"""
    assert validate_feedback({**FEEDBACK, "rating": rating}, now=NOW).rating == rating


# --- ts（00A §3.5）-----------------------------------------------------------


def test_missing_feedback_ts_defaults_but_missing_view_ts_fails() -> None:
    """Given 缺 `ts`／When 驗證／Then 回饋補匯入時間、瀏覽紀錄直接拒絕（設計 §7.1、§9.2）。"""
    assert validate_feedback(FEEDBACK, now=NOW).ts == NOW
    with pytest.raises(IngressError) as error:
        validate_view(_without(VIEW, "ts"))
    assert error.value.fields == ("ts",)


def test_a_supplied_feedback_ts_is_used_instead_of_the_import_time() -> None:
    """Given 來源有給 `ts`／When 驗證／Then 用來源的值，不覆蓋成 `now`。"""
    parsed = validate_feedback({**FEEDBACK, "ts": "2026-08-02T09:00:00Z"}, now=NOW).ts
    assert parsed == datetime(2026, 8, 2, 9, 0, tzinfo=UTC) != NOW


@pytest.mark.parametrize("bad_ts", ["2026/08/02 09:00", "2026-08-02T09:00:00",
                                    "2026-08-02T09:00:00.500Z", ""])
def test_ts_must_be_an_aware_whole_second_iso_string(bad_ts: str) -> None:
    """Given 格式錯／naive／帶微秒的 `ts`／When 驗證兩個入口／Then 都是 `("ts",)`。

    帶微秒特別重要：`parse_iso` 會放行它，`view_pk` 內部的 `to_iso` 卻會丟
    `PermanentError`——那不是使用者輸入錯誤該有的形狀，所以兩個入口一律走 `_parsed_ts`。
    """
    with pytest.raises(IngressError) as view_error:
        validate_view({**VIEW, "ts": bad_ts})
    assert view_error.value.fields == ("ts",)
    with pytest.raises(IngressError) as feedback_error:
        validate_feedback({**FEEDBACK, "ts": bad_ts}, now=NOW)
    assert feedback_error.value.fields == ("ts",)


# --- user（`COL` Rule 9）------------------------------------------------------


@pytest.mark.parametrize("payload", [FEEDBACK, VIEW])
@pytest.mark.parametrize("bad_user", [None, "", "   ", "U_01", "u", "u_01!", "u" * 65])
def test_user_must_match_the_stable_user_pattern(payload: dict[str, object],
                                                 bad_user: object) -> None:
    """Given `user` 缺值或不符 `^[a-z0-9_-]{2,64}$`／When 驗證／Then `("user",)`。

    判斷直接重用 Phase 13 的 `stable_user_from_import`，本 Phase 不另寫一份（R10）。
    """
    candidate = dict(payload) if bad_user is None else {**payload, "user": bad_user}
    if bad_user is None:
        candidate.pop("user")
    with pytest.raises(IngressError) as error:
        if "rating" in candidate:
            validate_feedback(candidate, now=NOW)
        else:
            validate_view(candidate)
    assert error.value.fields == ("user",)


@pytest.mark.parametrize("user", ["u_01", "u_gh-90210", "ab"])
def test_both_stable_user_shapes_are_accepted(user: str) -> None:
    """Given demo 的 `u_01` 與 GitHub 來源的 `u_gh-<id>`／When 驗證／Then 都通過（D-47）。"""
    assert validate_feedback({**FEEDBACK, "user": user}, now=NOW).user == user
    assert validate_view({**VIEW, "user": user}).user == user


# --- 其餘欄位 -----------------------------------------------------------------


def test_feedback_id_must_carry_the_f_prefix() -> None:
    """Given `id` 沒有 `f_` 前綴／When 驗證／Then `("id",)`（設計 §7.1 的 ID 形狀）。"""
    with pytest.raises(IngressError) as error:
        validate_feedback({**FEEDBACK, "id": "12"}, now=NOW)
    assert error.value.fields == ("id",)


@pytest.mark.parametrize("missing", ["id", "tutorial_version"])
def test_missing_required_feedback_fields_are_reported(missing: str) -> None:
    """Given 缺 `id` 或 `tutorial_version`／When 驗證／Then 那個欄位名在 `fields` 裡。"""
    with pytest.raises(IngressError) as error:
        validate_feedback(_without(FEEDBACK, missing), now=NOW)
    assert error.value.fields == (missing,)


def test_an_unknown_field_is_reported_with_the_other_problems() -> None:
    """Given 多一個 `score` 欄位又缺 `user`／When 驗證／Then 兩個欄位一次回報（F51）。"""
    with pytest.raises(IngressError) as error:
        validate_feedback({**_without(FEEDBACK, "user"), "score": 9}, now=NOW)
    assert error.value.fields == ("score", "user")
    with pytest.raises(IngressError) as view_error:
        validate_view({**VIEW, "score": 9})
    assert view_error.value.fields == ("score",)


def test_a_rating_only_feedback_is_valid() -> None:
    """Given 只有評分、沒有 `category` 與 `comment`／When 驗證／Then 通過（D12）。

    空字串收斂成 `None`，不是原樣寫進表：`Feedback.carries_signal` 看的是三者是否全空，
    留一個空字串會讓「只有評分」與「留了空白留言」在下游長成兩種形狀。
    """
    feedback = validate_feedback({**FEEDBACK, "category": "", "comment": "  "}, now=NOW)
    assert (feedback.category, feedback.comment, feedback.rating) == (None, None, 2)


def test_non_string_category_or_comment_is_rejected() -> None:
    """Given `category` 給了數字／When 驗證／Then `("category",)`，不做隱性轉型。"""
    with pytest.raises(IngressError) as error:
        validate_feedback({**FEEDBACK, "category": 3}, now=NOW)
    assert error.value.fields == ("category",)


def test_the_category_value_is_kept_verbatim_for_phase_43() -> None:
    """Given 來源勾了一個類別／When 驗證／Then 原值保留，本 Phase 不收斂也不分類。"""
    feedback = validate_feedback({**FEEDBACK, "category": "找不到按鈕",
                                  "comment": "第三步沒有指出按鈕在哪一頁"}, now=NOW)
    assert feedback.category == "找不到按鈕"


def test_project_id_is_allowed_but_never_reaches_the_model() -> None:
    """Given payload 帶 `project_id`／When 驗證／Then 不是未知欄位，也不在模型欄位裡。"""
    feedback = validate_feedback({**FEEDBACK, "project_id": "demo"}, now=NOW)
    assert "project_id" not in feedback.model_dump()
    assert validate_view({**VIEW, "project_id": "demo"}).tutorial_version == VIEW[
        "tutorial_version"]


def test_a_full_view_payload_round_trips() -> None:
    """Given 完整的瀏覽紀錄／When 驗證／Then 三個欄位逐一對上，`ts` 是 aware UTC。"""
    view = validate_view(VIEW)
    assert (view.tutorial_version, view.user) == ("prepare-meeting@v1", "u_01")
    assert view.ts == datetime(2026, 8, 2, 9, 0, tzinfo=UTC)


def test_model_level_rejections_become_ingress_errors() -> None:
    """Given `tutorial_version` 帶了型別前綴／When 驗證／Then 收斂成 `IngressError`。

    `models.bare_id` 丟的是 pydantic `ValidationError`；00A §6.8 要求接入層一律收斂成
    `IngressError`，否則 handler 只認 `IngressError` 的呼叫端會看到 500 而不是明確拒絕。
    """
    with pytest.raises(IngressError) as error:
        validate_feedback({**FEEDBACK, "tutorial_version": "VERSION#prepare-meeting@v1"}, now=NOW)
    assert error.value.fields == ("tutorial_version",)
