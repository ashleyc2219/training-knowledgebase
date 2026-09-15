"""Phase 50 Task 2／3：Safety Net 的觸發條件、候選排序、逐版確認與空結果（不連 AWS）。

本檔自備 fixture，**不動** `tests/unit/conftest.py`（COMMON.md R3.6 只有 P55 能改），也不與
同波次的 Phase 49 共用：`FakeWriter` 記的是有 `.node`／`.user` 屬性的 dataclass，而共用的
`RecordingWriter` 記的是 dict、回覆是依序 pop 的 list，兩者形狀不同。

`FakeWriter.embed` 把查詢文字回成 `[1.0, 0.0, …]`、把分數為 `s` 的步驟回成
`[s, sqrt(1 - s²), 0.0, …]`，所以 Phase 16 的**真** `cosine` 算出來剛好等於 `s`，
排序不會被浮點誤差推翻；`generate_json` 依 `user` 裡出現的 `version_id` 取回覆。
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

from training_kb.models import Feature, Release
from training_kb.pipelines.release import StepHit, needs_safety_net

NOW = datetime(2026, 9, 14, 9, 0, tzinfo=UTC)
FEATURE = "Prepare"
ALIAS = "Meeting Summary"
HIT = StepHit("prepare-meeting", "prepare-meeting@v2", 3)


def make_release(*, kind: str, old_name: str | None, new_name: str | None) -> Release:
    return Release(id="r_42", source="github_pr", feature=FEATURE, kind=kind,
                   old_name=old_name, new_name=new_name,
                   evidence="PR #42 rename Meeting Summary -> Prepare", ts=NOW)


def make_feature(feature_id: str, *, name: str, aliases: Sequence[str] = ()) -> Feature:
    return Feature(feature_id=feature_id, name=name, aliases=list(aliases), first_seen=NOW)


@dataclass
class JsonCall:
    """一次 `generate_json`：屬性存取版，因為共用 `RecordingWriter` 記的是 dict。"""

    system: str
    user: str
    schema: Mapping[str, Any]
    node: str


@dataclass
class FakeWriter:
    """只夠跑 `safety_net` 的假 Writer；`scores` 沒列到的步驟一律 0.0。"""

    scores: dict[tuple[str, int], float] = field(default_factory=dict)
    replies: dict[str, Mapping[str, Any]] = field(default_factory=dict)
    default_reply: Mapping[str, Any] = field(
        default_factory=lambda: {"confirmed_step_numbers": [], "reason": "沒有步驟提到這個功能"})
    embed_calls: list[tuple[str, str]] = field(default_factory=list)
    json_calls: list[JsonCall] = field(default_factory=list)

    def embed(self, text: str, *, operation_id: str, node: str) -> list[float]:
        self.embed_calls.append((node, text))
        located = _locate(text)
        if located is None:
            return [1.0, 0.0] + [0.0] * 1022          # 查詢向量：只有第 0 軸
        score = self.scores.get(located, 0.0)
        return [score, math.sqrt(1.0 - score * score)] + [0.0] * 1022

    def generate_json(self, system: str, user: str, schema: Mapping[str, Any], *,
                      operation_id: str, node: str) -> dict[str, Any]:
        self.json_calls.append(JsonCall(system=system, user=user, schema=schema, node=node))
        for version_id, reply in self.replies.items():
            if version_id in user:
                return dict(reply)
        return dict(self.default_reply)


def _locate(text: str) -> tuple[str, int] | None:
    """從步驟文字還原 `(version_id, number)`；不是步驟文字（查詢文字）就回 `None`。"""
    head, separator, rest = text.partition(" 第 ")
    number, _, _ = rest.partition(" 步")
    if not separator or not number.isdecimal():
        return None
    return head, int(number)


@pytest.fixture
def fake_writer() -> FakeWriter:
    return FakeWriter()


@pytest.fixture
def renamed_release() -> Release:
    return make_release(kind="renamed", old_name=ALIAS, new_name=FEATURE)


# --- Task 2：Safety Net 的觸發條件（F16 四種組合） --------------------------


@pytest.mark.parametrize(("kind", "old_name", "hits", "expected"), [
    ("renamed", ALIAS, [HIT], False),           # alias 命中，不是重大改名
    ("renamed", "Legacy Name", [HIT], True),    # alias 未命中 -> 重大改名
    ("changed", None, [], True),                # 反查為零 -> 獨立觸發
    ("changed", None, [HIT], False),
])
def test_safety_net_trigger_follows_f16(kind: str, old_name: str | None,
                                        hits: Sequence[StepHit], expected: bool,
                                        fake_writer: FakeWriter) -> None:
    """REL Rule 6／F16：Given 四種（kind, alias 是否命中, 有無反查命中）組合，
    When 問要不要補漏，Then 只有「alias 已命中且已有反查命中」完全不觸發；
    而且這一步是純函式，零次 `embed`（要不要花錢的判斷不該有副作用）。"""
    release = make_release(kind=kind, old_name=old_name,
                           new_name=FEATURE if kind == "renamed" else None)
    feature = make_feature(FEATURE, name=FEATURE, aliases=[ALIAS])
    assert needs_safety_net(release, feature, hits) is expected
    assert fake_writer.embed_calls == []


def test_safety_net_trigger_ignores_case_and_padding_of_old_name() -> None:
    """Given 舊名稱只差大小寫與前後空白，When 比對 alias，
    Then 用 Phase 49 的 `normalize_feature_name` 判定為已命中，不觸發補漏。"""
    release = make_release(kind="renamed", old_name="  meeting summary  ", new_name=FEATURE)
    feature = make_feature(FEATURE, name=FEATURE, aliases=[ALIAS])
    assert needs_safety_net(release, feature, [HIT]) is False


def test_safety_net_trigger_is_true_when_renamed_and_nothing_found() -> None:
    """Given 重大改名而且反查為零，When 問要不要補漏，Then 觸發（兩個條件都成立）。"""
    release = make_release(kind="renamed", old_name="Legacy Name", new_name=FEATURE)
    feature = make_feature(FEATURE, name=FEATURE, aliases=[ALIAS])
    assert needs_safety_net(release, feature, []) is True


def test_removed_release_with_hits_does_not_trigger() -> None:
    """Given `removed` 且已有反查命中，When 問要不要補漏，
    Then 不觸發：只有 renamed 才需要比 alias。"""
    release = make_release(kind="removed", old_name=None, new_name=None)
    feature = make_feature(FEATURE, name=FEATURE, aliases=[ALIAS])
    assert needs_safety_net(release, feature, [HIT]) is False
