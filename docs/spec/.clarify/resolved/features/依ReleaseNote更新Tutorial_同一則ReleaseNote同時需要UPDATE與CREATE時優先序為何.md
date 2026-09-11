# 釐清問題

同一則 Release Note 同時需要 UPDATE 與 CREATE 時，優先序為何？

# 定位

Feature：依ReleaseNote更新Tutorial
- Rule：更新受影響內容並發布新版本（動作 UPDATE）
- Rule：Release Notes 也可用來判斷是否需要建立新的 Tutorial（動作 CREATE）
已有釐清：出現 new_feature 且尚無對應 Tutorial 時動作為何；找不到受影響 Tutorial 且非需新建時行為為何
未覆蓋：同一則 Note 同時含 renamed/changed（有受影響 Tutorial）與 new feature（無 Tutorial）

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 同一則 Note 可同時 UPDATE 既有 Tutorial 並 CREATE 新 Tutorial |
| B | 先 UPDATE 既有，CREATE 留到下一次處理 |
| C | 只做其中一個：有受影響 Tutorial 就只 UPDATE，不 CREATE |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

決定 `依ReleaseNote更新Tutorial` 的 Then 可否同時出現 `UPDATE` 與 `CREATE`，以及與 `建立Tutorial` 的交界。影響 Release Note demo 能不能一則稿同時展示兩條路徑。

# 優先級

High
---
# 解決記錄

- **回答**：C - 只做其中一個：有受影響 Tutorial 就只 UPDATE，不 CREATE
- **更新的規格檔**：docs/spec/features/依ReleaseNote更新Tutorial.feature
- **變更內容**：Release 不觸發 CREATE；只 UPDATE 或 RETIRE。
