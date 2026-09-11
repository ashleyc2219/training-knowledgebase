# 釐清問題

票量暴增、無教學覆蓋與 SLA 訊號，是僅供展示還是會觸發系統動作？

# 定位

Feature：監測即時票務 / Rule：缺失功能
客服規格 hotdata：查票量暴增、完全沒有對應教學、SLA 快超時，並算 deflection rate
design-draft hotdata：Ratings／Feedback／Ticket Counts／Tutorial Performance，用來觸發 Periodic Refinement，無 SLA／暴增動作
已有釐清：輪詢到新票後下一步、自動回覆條件——未問這三類監測訊號本身
**依賴**：產品主軸題；`Ticket_是否要有SLA期限或問題類別欄位`

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 僅查詢展示，不觸發 CREATE、回覆或轉真人 |
| B | 無覆蓋可觸發分析或 CREATE；暴增與 SLA 只展示 |
| C | 三類都會觸發對應動作（無覆蓋→建教學，暴增→優先處理，SLA→轉真人） |
| D | 不進入作用中規格，只當 Demo 旁白 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

B1：要不要新增 `監測即時票務`。選 A／D 不新增動作 Rule；選 B／C 必須補各訊號的 When／Then。不在此題定義 SLA 時限數字。

# 優先級

Medium
---
# 解決記錄

- **回答**：D - 不進入作用中規格，只當 Demo 旁白
- **更新的規格檔**：無
- **變更內容**：不進作用中規格
