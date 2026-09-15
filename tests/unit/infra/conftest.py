"""`tests/unit/infra/` 共用器材：把 Lambda 相依 layer 指到 `tmp_path` 的假目錄。

CDK 合成要過 `TrainingKbStack._layer()` 的守門（`build_lambda_layer.is_built`，它查
`python/pydantic` 與 `python/jsonschema` 這兩個頂層套件目錄在不在），但單元測試既不該
真的裝 9 MB 的 wheel，也**不該在工作樹裡 `mkdir`**：

- 在 `build/lambda-layer/python/` 造空目錄會被收緊前的守門放行，部署出一支 import 才爆
  `Runtime.ImportModuleError` 的 Lambda（Phase 41 review 必修 2）。
- 只造 `python/`（不造 `pydantic`／`jsonschema`）則在乾淨 clone 上會 `FileNotFoundError`，
  本機會綠只是因為 `build/lambda-layer/` 剛好留著上一次真的裝好的東西。

所以一律 monkeypatch `LAYER_PATH`，放進本檔讓三支 infra 測試共用一份
（controller 2026-09-14 核准由 Phase 42 代改 Phase 54 的 `test_analytics_stack.py`）。
"""

import pathlib
import sys

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from infra import training_kb_stack as stack_module  # noqa: E402
from infra.scripts.build_lambda_layer import MARKERS  # noqa: E402


@pytest.fixture
def fake_layer(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> pathlib.Path:
    """把 layer 路徑指到 `tmp_path` 下一份**看起來裝好了**的目錄，不碰工作樹。

    目錄名取自 `build_lambda_layer.MARKERS`，所以守門條件改了測試會跟著改，
    不會出現「測試造的假 layer 通得過、真的 layer 反而不行」這種分岔。
    """
    for marker in MARKERS:
        (tmp_path / "python" / marker).mkdir(parents=True)
    monkeypatch.setattr(stack_module, "LAYER_PATH", tmp_path)
    return tmp_path
