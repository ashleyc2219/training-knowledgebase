"""`analytics` 套件：指標與規則狀態的離線寫入端。

本檔只是套件初始化（`[tool.setuptools.packages.find]` 靠 `__init__.py` 找得到子套件），
**不 re-export 任何名稱**：00A §3.2 把 `analytics/__init__.py` 的 owner 記給 Phase 53，
Phase 40 只因為要放 `status_writer.py` 的讀取端而先建立最小版本（D-28、D-28 的檔案表）。
Phase 53 要在這裡加東西時直接改，不必先刪。
"""
