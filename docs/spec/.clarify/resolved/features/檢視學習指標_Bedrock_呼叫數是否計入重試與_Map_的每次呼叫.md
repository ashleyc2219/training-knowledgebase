# 釐清問題

Bedrock 呼叫數是否計入重試與 Map 的每次呼叫？

# 定位

- 追蹤 ID：F45
- [檢視學習指標，Rule 7「每次執行的 Bedrock 呼叫數包含 Step Functions 內的呼叫節點與 Rote 層呼叫」](../../features/檢視學習指標.feature)，第 46 行。
- [執行教學流程，Rule 5「每個 Step Functions Task 設定 Retry」](../../features/執行教學流程.feature)，第 28 行。
- [接入來源事件，Rule 10「接入層命中已驗證流程的重放路徑不呼叫 LLM」](../../features/接入來源事件.feature)，第 60 行。

現況：指標文字是節點數加 Rote 呼叫數，容易混淆靜態節點與實際請求；這會改變 8→2 的成本敘事。

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 計算每次實際送出的呼叫嘗試，包含重試、每個 Map item 與 Rote 呼叫。 |
| B | 計算執行過的不同 Bedrock 節點數，重試或 Map 重複不增加節點數，再加 Rote 呼叫。 |
| C | 只計成功回傳的實際模型呼叫，失敗嘗試另列不併入此指標。 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

決定執行紀錄需提供的計數、失敗重試與多步改寫的數字；接入重放零 LLM 不代表整條 pipeline 零 LLM。

# 優先級

Medium

- 影響邊界行為、資料一致性或驗收完整性。

---
# 解決記錄

- **回答**：A - 計算每次實際送出的呼叫嘗試，包含重試、每個 Map item 與 Rote 呼叫。
- **更新的規格檔**：docs/spec/features/檢視學習指標.feature
- **變更內容**：Bedrock 呼叫數含重試、每個 Map item 與 Rote 的每次實際送出。
