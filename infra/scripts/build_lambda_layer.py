"""把 Lambda runtime **沒有**的兩個相依裝進 `build/lambda-layer/python/`（COMMON.md R2）。

`lambda_.Code.from_asset("src")` 只帶原始碼：`pydantic`／`jsonschema` 不在裡面，而
`pydantic-core` 是編譯套件，本機（arm64 macOS）裝出來的 wheel 在 Lambda 上 import 會爆。
所以 wheel 平台固定 `x86_64-manylinux2014`，必須與 `lambda_.Architecture.X86_64` 一致；
兩邊不一致時 `cdk synth` 與 `cdk deploy` 都不會報錯，只有 invoke 才會
`Runtime.ImportModuleError`。

`boto3` **不放進 layer**：Lambda runtime 自帶，放進去只會蓋掉執行環境的版本。

用法（`cdk synth` 之前一定要先跑，asset 目錄不存在時 synth 會直接失敗）：

```bash
uv run python -m infra.scripts.build_lambda_layer
```
"""

import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

LAYER_ROOT = PROJECT_ROOT / "build" / "lambda-layer"
"""layer asset 的根目錄；`build/` 已在 `.gitignore`，產物不進版控。"""

LAYER_PYTHON_DIR = LAYER_ROOT / "python"
"""Lambda layer 的固定佈局：`python/` 底下的東西才會進 `sys.path`。"""

PYTHON_VERSION = "3.12"
PYTHON_PLATFORM = "x86_64-manylinux2014"
"""必須與 `lambda_.Architecture.X86_64` 一致；改 arm64 要同時改這裡與 stack 的 `architecture=`。"""

REQUIREMENTS = ("pydantic>=2,<3", "jsonschema>=4,<5")
"""`pyproject.toml` 三個 runtime 相依裡「Lambda 沒有的」兩個。"""

MARKERS = ("pydantic", "jsonschema")
"""`is_built` 要看到的頂層套件目錄；空的 `python/` 不算建好。"""


def is_built(root: Path = LAYER_ROOT) -> bool:
    """layer **真的裝好了嗎**——不是只看目錄在不在。

    只查 `is_dir()` 會被一個空的 `build/lambda-layer/python/` 騙過去（測試或手動
    `mkdir` 都可能留下），然後部署出一支 import 才爆 `Runtime.ImportModuleError`
    的 Lambda。所以這裡查的是每個頂層套件目錄。
    """
    return all((root / "python" / name).is_dir() for name in MARKERS)


def command(target: Path = LAYER_PYTHON_DIR) -> list[str]:
    """完整的 uv 指令；獨立出來讓報告與測試都引用同一份，不各自抄一次。"""
    return ["uv", "pip", "install", "--target", str(target),
            "--python-platform", PYTHON_PLATFORM, "--python-version", PYTHON_VERSION,
            "--only-binary=:all:", *REQUIREMENTS]


def build(root: Path = LAYER_ROOT) -> Path:
    """重建 layer 目錄並回傳 `python/` 的路徑；每次都先刪掉，避免留下上一次的殘骸。"""
    target = root / "python"
    if root.exists():
        shutil.rmtree(root)
    target.mkdir(parents=True)
    subprocess.run(command(target), check=True, cwd=PROJECT_ROOT)
    return target


def main() -> int:
    target = build()
    packages = sorted(path.name for path in target.iterdir()
                      if not path.name.endswith(".dist-info"))
    print(f"layer: {target}")
    print(f"packages: {', '.join(packages)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
