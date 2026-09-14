"""`pipelines` 套件入口：三條固定流程（`ticket-analysis`／`release-update`／`feedback-review`）。

這裡**不做 re-export**。00A 第 6.9 節把共用名稱的 import 路徑逐字定在
`training_kb.pipelines.common` 與 `training_kb.pipelines.asl`（例如
`from training_kb.pipelines.asl import CATCH, RETRY, task_state`），
只留一條 import 路徑，下游 Phase 就不會出現兩種寫法指向同一個物件。
"""
