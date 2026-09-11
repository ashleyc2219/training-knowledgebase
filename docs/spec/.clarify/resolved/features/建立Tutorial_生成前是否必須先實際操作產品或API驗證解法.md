# 釐清問題

生成 Tutorial 前，是否必須先實際操作產品或 API 驗證解法？

# 定位

Feature：建立Tutorial / Rule：當發現新的 Knowledge Gap 且目前沒有 Tutorial 可以解決時建立 Tutorial v1
客服規格：RocketRide「實際操作產品介面或呼叫 API 把問題解決一遍」
design-draft：建立流程無此前置，直接 Generate tutorial
現有 Example：Given Knowledge Gap → When 建立 → Then path / v1，沒有驗證步驟
**依賴**：產品主軸題；`重放已驗證流程_Rote重放的對象是解票步驟還是教學工作流`

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 必須驗證成功才建立；驗證失敗則不建立 |
| B | 不需實際操作，可直接依票單與文件生成 |
| C | 嘗試驗證；失敗仍可建立，但必須標記未驗證 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

決定 `建立Tutorial` 是否新增驗證前置 Rule 與失敗 Example，以及 Tutorial.steps 是否必須來自已執行過的操作序列，並連動 Rote 捕捉時機。

# 優先級

High
---
# 解決記錄

- **回答**：B - 不需實際操作，可直接依票單與文件生成
- **更新的規格檔**：docs/spec/features/建立Tutorial.feature
- **變更內容**：不新增驗證 Rule
