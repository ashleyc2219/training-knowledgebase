# 釐清問題

Tutorial 與教學文章是否為同一概念？

# 定位

ERM：`Table Tutorial`（教學文件；CREATE / UPDATE / REFINE / KEEP / RETIRE）
Feature：`建立Tutorial`、`依ReleaseNote更新Tutorial`、`定期優化Tutorial`、`收集Feedback` 皆以 Tutorial 為標的
來源衝突：design-draft.md 使用 Tutorial / Training Content / 教學文件；客服自助教學生成器 — 系統架構規格.md 使用教學文章（回覆顧客的 deflection 內容）

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 同義，canonical 名稱為 Tutorial；中文可寫「教學」但規格實體不另建教學文章 |
| B | 同義，canonical 名稱為教學文章；ERM / Features 的 Tutorial 全部改名 |
| C | 不同概念：Tutorial 是內部培訓文件，教學文章是回給顧客的 deflection 內容，需兩實體或明確子集關係 |
| Short | 提供其他簡短答案（<=5 字） |

# 影響範圍

決定核心產出物命名、HydraDB 節點、Publish 對象，以及 Feature 是否繼續叫「建立 Tutorial」。若選 C，客服回覆連結指向的物件與 Champion 維護的物件必須分開建模。

# 優先級

High
---
# 解決記錄

- **回答**：A - 同義，canonical 名稱為 Tutorial；中文可寫「教學」但規格實體不另建教學文章
- **更新的規格檔**：docs/spec/erm.dbml
- **變更內容**：Tutorial Note 註明同義詞為教學文章，規格一律用 Tutorial；未另建教學文章表。
