"""Demo 種子資料與本機工具（Phase 56 建立，Phase 58 的控制台沿用）。

`demo/` **不是**要安裝的套件（`pyproject.toml` 的 `[tool.setuptools.packages.find]`
維持 `where = ["src"]`），只是專案根底下可以被 import 的本機工具與資料目錄；
測試靠 `[tool.pytest.ini_options]` 的 `pythonpath = ["."]` 找到它。

這裡的資料**全部是明示的合成資料**（每份 JSON 都帶 `"synthetic": true`），
不含任何真人資料、帳號或金鑰。
"""
