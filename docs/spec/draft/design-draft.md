# 自我優化的 Copilot 教學知識庫

## 1. 專案概要

這個專案要打造一個給企業內部 IT / Copilot Enablement 團隊使用的 **單一 Agent、自我優化教學知識庫**。

系統會持續從三種來源學習：

1. **Support Tickets** —— 使用者想學什麼。
2. **User Feedback / Ratings** —— 哪些教學不清楚、效果不好。
3. **Release Notes** —— 哪些產品功能或 UI 流程發生變化。

Agent 會根據這些訊號，自動進行：

* 建立新的 Tutorial
* 更新已過期的 Tutorial
* 優化品質不佳的 Tutorial
* 下架已失效的 Tutorial
* 保留目前效果良好的 Tutorial

目標是降低 IT / Copilot Champion 目前需要反覆處理的工作，包括：

* 回答重複問題
* 維護教學文件
* 追蹤產品更新
* 閱讀課後 Feedback
* 判斷哪些 Tutorial 需要修改

---

# 2. 核心問題

IT Enablement 團隊目前會不斷重複做相似的事情：

* 回答課後反覆出現的問題
* 人工判斷哪些問題值得做成新的教學文件
* 每當產品更新時，人工檢查與修改 Tutorial
* 人工閱讀問卷與 Feedback
* 人工決定哪些 Tutorial 應該被優化

此外，像 Copilot 這類產品會持續推出新功能與 UI 更新，因此靜態的教學內容很容易過期。

## Problem Statement

> **IT Enablement 團隊需要不斷為重複出現的問題建立教學內容；當產品更新時，還必須人工維護文件，並定期人工閱讀使用者 Feedback，判斷哪些 Tutorial 應該被改善。**

---

# 3. 解決方案

> **建立一個會自我優化的 Training Knowledge Base：從 Support Tickets 發現新的教學需求、在產品 Release 時自動更新既有 Tutorial，並定期根據真實 User Feedback 優化教學內容。**

整個系統形成一個持續學習循環：

```text
觀察
↓
建立 / 更新
↓
發布
↓
收集 Feedback
↓
學習
↓
優化
↓
再次循環
```

核心概念：

> **Release Notes 讓知識保持最新。
> User Feedback 讓知識持續變好。**

---

# 4. 輸入資料來源

## 4.1 Support Tickets

Support Tickets 告訴系統：

* 使用者最近都在問什麼
* 哪些問題重複出現
* 哪些工作流程目前沒有對應的 Tutorial

例如：

```text
Ticket 1:
「我要怎麼用 Copilot 產生 Meeting Brief？」

Ticket 2:
「Meeting Preparation 功能在哪裡？」

Ticket 3:
「我要怎麼用 Copilot 準備客戶會議？」
```

Agent 可以把語意相似的 Tickets 聚集在一起，判斷是否存在一個新的 Knowledge Gap。

### 主要用途

> **Support Tickets 用來決定是否應該建立新的 Tutorial。**

---

## 4.2 User Feedback / Ratings

每篇 Tutorial 都可以收集結構化 Feedback。

例如：

```text
tutorial_id
tutorial_version
rating
feedback_category
comment
timestamp
```

Feedback 類別可以包含：

* 指示不清楚
* 缺少資訊
* UI 與 Tutorial 不一致
* Tutorial 太長
* Tutorial 沒有解決問題
* 缺少自己的使用情境

例如：

```text
Tutorial:
Prepare Customer Meeting

平均評分:
3.1 / 5

Feedback:
- 「Step 3 很難懂。」
- 「Prepare 按鈕在哪？」
- 「我不知道這個選項是做什麼的。」
- 「Step 3 應該再寫詳細一點。」
```

系統不應該因為某一個使用者給低分，就立刻修改 Tutorial。

而是要觀察一段時間累積下來的 **pattern**。

### 主要用途

> **User Feedback 用來決定哪些既有 Tutorial 應該被優化。**

---

## 4.3 Release Notes

Release Notes 告訴系統：

* 新功能
* 功能重新命名
* Workflow 改變
* UI 改版
* 功能被 deprecated 或移除

例如：

```text
Release Note:

"Meeting Summary" 功能已重新設計，
並更名為 "Prepare"。
```

Agent 會將新的 Release Note 與既有 Tutorial Knowledge 進行比對。

### 主要用途

> **Release Notes 用來判斷哪些 Tutorial 可能已經過期，以及是否需要建立新的 Tutorial。**

---

# 5. Tutorial Lifecycle

系統對 Tutorial 可以做五種主要動作：

```text
CREATE
UPDATE
REFINE
KEEP
RETIRE
```

---

## CREATE

當系統發現新的 Knowledge Gap 時觸發。

```text
Support Tickets
      ↓
Agent 分析 recurring questions
      ↓
發現新的 Knowledge Gap
      ↓
目前沒有 Tutorial 可以解決
      ↓
建立 Tutorial v1
      ↓
Publish
```

---

## UPDATE

當產品 Release 導致原本 Tutorial 過期時觸發。

```text
Release Note
      ↓
偵測 Feature / UI 改變
      ↓
找到受影響的 Tutorials
      ↓
標記為可能過期
      ↓
更新受影響內容
      ↓
發布新版本
```

---

## REFINE

當定期 Feedback Review 發現 Tutorial 效果不好時觸發。

```text
累積 Feedback
      ↓
分析 Ratings + Comments
      ↓
找出 recurring friction
      ↓
找到 Tutorial 中較弱的部分
      ↓
產生改善版本
      ↓
Publish
```

---

## KEEP

如果：

* Tutorial 內容仍然符合目前產品
* Feedback 表現良好
* 沒有相關產品變更

則保持 Tutorial 不變。

---

## RETIRE

如果 Release Note 表示某個 Feature 已經被移除或取代：

```text
Feature 被 Deprecated / Removed
      ↓
找出相關 Tutorials
      ↓
標記為 Obsolete
      ↓
Retire 或導向新的 Tutorial
```

---

# 6. 兩個 Tutorial 更新觸發點

對既有 Tutorial 的修改，主要只有兩個 Trigger。

---

## Trigger 1 — 新的 Release Note

**類型：Event-driven**

目的：

> 當產品發生改變時，自動偵測哪些 Training Content 已經過期。

流程：

```text
New Release Note
      ↓
Extract:
- new features
- changed features
- renamed features
- deprecated features
- UI changes
      ↓
與 Tutorial Knowledge 比對
      ↓
找出受影響的 Tutorials
      ↓
Update / Create / Retire
```

### 範例

原本：

```text
Tutorial v1

Step 3:
Click "Meeting Summary"
```

新的 Release Note：

```text
"Meeting Summary" 已重新設計，
並更名為 "Prepare"。
```

Agent 更新：

```diff
- Click "Meeting Summary"
+ Click "Prepare"
```

最後：

```text
Tutorial v1
    ↓
Product Update
    ↓
Release Note
    ↓
Agent 找到 affected content
    ↓
Tutorial v2
```

這個 Trigger 解決的是：

> **產品已經更新，但 Training Content 還停留在舊版本。**

---

## Trigger 2 — 定期 User Feedback Review

**類型：Scheduled**

例如：

```text
每天
或
每週
```

目的：

> 找出「雖然沒有過期，但實際上不好用」的 Tutorial。

流程：

```text
Ratings
Comments
Questions
Low-rated tutorials
Repeated complaints
      ↓
Agent 分析 pattern
      ↓
找出較弱的 Tutorial / Section
      ↓
Refine
      ↓
Publish 新版本
```

### 範例

修改前：

```text
Step 3:
Click "Prepare."
```

累積 Feedback：

```text
- 「Prepare 是做什麼的？」
- 「這個按鈕在哪？」
- 「這一步需要更多說明。」
```

Agent 產生新的版本：

```diff
- Click "Prepare."

+ Open Copilot and select "Prepare" in the upper-right corner.
+ This generates a summary of your upcoming customer meeting
+ using recent emails, notes, and meeting history.
```

這個 Trigger 解決的是：

> **文件本身沒有過期，但使用者實際上看不懂。**

---

# 7. 完整系統流程

```text
                     Support Tickets
                           ↓
                  發現新的 Knowledge Gap
                           ↓
                     建立新 Tutorial
                           ↓
                        Publish
                           ↓
                      User 使用
                           ↓
                    User Feedback
                           ↓
                          DB
                           ↓
             ┌─────────────┴─────────────┐
             │                           │
             │                           │
      NEW RELEASE NOTE            PERIODIC REVIEW
             │                           │
             ▼                           ▼
       偵測產品變更               分析累積 Feedback
             │                           │
             ▼                           ▼
   找出 affected tutorials        找出品質較差的 Tutorial
             │                           │
             ▼                           ▼
       Update Tutorial             Refine Tutorial
             │                           │
             └─────────────┬─────────────┘
                           ↓
                       New Version
                           ↓
                         Publish
                           ↓
                           ↻
```

---

# 8. Self-Learning 定義

在這個專案裡，**Self-Learning 並不是指 Model Fine-tuning。**

系統的 Learning 來自：

1. 觀察新的 User Need
2. 儲存 Structured Knowledge
3. 追蹤 Tutorial Outcome
4. 找出 recurring patterns
5. 根據過去 outcome 改變未來生成 Tutorial 的方式

例如：

```text
Tutorial v1
Average Rating: 2.9

Recurring complaint:
「Step 3 很難懂」

        ↓

Agent 學到：
Step 3 缺乏足夠 context

        ↓

Tutorial v2
Average Rating: 4.4

Recurring complaints 減少
```

真正重要的是：

> **Past outcomes change future system behavior.**

也就是：

> **過去使用者的結果，會真正改變系統下一次的行為。**

---

# 9. 三種 Knowledge Signals

| Input           | Agent 學到什麼       |
| --------------- | ---------------- |
| Support Tickets | 使用者想知道什麼         |
| User Feedback   | 哪些 Tutorial 沒有效果 |
| Release Notes   | 產品發生了什麼變化        |

這些訊號分別對應：

| Signal                | Action |
| --------------------- | ------ |
| 新的 recurring question | CREATE |
| Product Feature 改變    | UPDATE |
| Tutorial 效果不好         | REFINE |
| Tutorial 效果良好         | KEEP   |
| Feature 被移除           | RETIRE |

---

# 10. Single-Agent Architecture

系統只使用一個主要 Agent。

Agent 負責：

```text
分析 Tickets
↓
找 recurring knowledge gaps
↓
Retrieve existing tutorial knowledge
↓
Generate tutorial
↓
Analyze release notes
↓
Identify impacted tutorials
↓
Analyze feedback
↓
決定 CREATE / UPDATE / REFINE / KEEP / RETIRE
↓
Publish 下一版 Tutorial
```

Agent 負責的是：

> **Decision Making**

其他技術元件則負責：

* Memory
* Analytics
* Orchestration
* Deterministic Replay

---

# 11. Hackathon 技術 Stack 對應

## Cognee — Memory Construction

Cognee 負責把原始資料轉換成 Structured Knowledge。

輸入：

```text
Support Tickets
Release Notes
Tutorial Content
User Feedback
```

可能的 Entities：

```text
UserProblem
Feature
Tutorial
TutorialVersion
Feedback
Release
Workflow
```

可能的 Relationships：

```text
Ticket -> asks_about -> Feature

Tutorial -> explains -> Feature

Feedback -> refers_to -> TutorialVersion

Release -> changes -> Feature

TutorialVersion -> supersedes -> TutorialVersion
```

---

## HydraDB — Durable Memory

HydraDB 儲存長期 Knowledge Graph。

例如 Agent 可以詢問：

```text
哪些 Tutorials 在解釋這個 Feature？

哪些 Tutorials 受到這次 Release 影響？

這個 Release 之前使用的是哪一版 Tutorial？

哪些 User Problems 經常與這個 Feature 有關？
```

HydraDB 提供的是：

> **跨 Session 的長期記憶。**

---

## Hotdata — Live Analytics

Hotdata 負責分析：

```text
Ratings
Feedback
Ticket Counts
Tutorial Performance
Tutorial Version Performance
```

例如：

```sql
SELECT
    tutorial_id,
    AVG(rating) AS avg_rating,
    COUNT(*) AS feedback_count
FROM feedback
GROUP BY tutorial_id
ORDER BY avg_rating ASC;
```

可以用來找：

```text
Tutorial rating < 3.5
+
Feedback 數量足夠
+
存在 recurring complaints
```

這些 Tutorial 就可以進入：

> **Periodic Refinement Process**

---

## RocketRide — Agent Orchestration

RocketRide 負責控制 Single-Agent Workflow。

例如：

```text
Ticket Analysis Pipeline

Release Note Update Pipeline

Periodic Feedback Review Pipeline
```

RocketRide 控制 Agent：

* 什麼時候讀 Memory
* 什麼時候查 Hotdata
* 什麼時候生成 Tutorial
* 什麼時候更新既有版本

---

## Rote — Muscle Memory

Rote 負責記錄成功且重複出現的 Workflow。

例如：

```text
Release Note arrives
↓
Extract changed features
↓
Find impacted tutorials
↓
Generate new versions
↓
Publish
```

第一次需要 Agent Reasoning。

之後如果同類工作再次出現：

```text
Run 1:
More reasoning

Run N:
Reuse proven workflow
```

也就是：

> **不要每次都重新思考已經成功處理過的固定流程。**

---

## Snyk — Security

Submission 前：

* 掃描 Dependencies
* 掃描 Source Code
* 修掉 High-Severity Vulnerabilities
* 避免 API Key / Secret 被提交到 Repo

---

# 12. Minimum Viable Product

MVP 最少要展示一個完整 Learning Loop。

---

## Feature 1 — Ticket Ingestion

準備 Synthetic Support Tickets。

例如：

```text
20–30 tickets
```

Agent 分析後找出一個 recurring question。

---

## Feature 2 — Generate Tutorial v1

系統自動產生：

```text
tutorials/
└── prepare-meeting.md
```

Tutorial 包含：

```text
Title
Problem
Prerequisites
Steps
Expected Outcome
```

---

## Feature 3 — Feedback Collection

每一篇 Tutorial 可以收：

```text
1–5 Rating
Feedback Category
Optional Comment
```

Feedback 存進 Database，等待後續分析。

---

## Feature 4 — Periodic Refinement

事先 Seed 一批 Feedback：

```text
很多 User 表示：
Step 3 很難懂
```

接著執行：

```text
Feedback DB
↓
Agent
↓
Detect weak section
↓
Tutorial v1 → v2
```

Demo 顯示：

```text
Version Diff
```

---

## Feature 5 — Release Note Update

輸入一個假的 Release Note：

```text
"Meeting Summary has been renamed to Prepare."
```

系統：

```text
Detect affected tutorial
↓
Update relevant step
↓
Create new version
```

然後 Demo 顯示：

```text
Tutorial Diff
```

---

# 13. Demo Script

## Demo Part 1 — 發現 Knowledge Gap

先展示幾個 Support Tickets：

```text
「我要怎麼準備 meeting？」

「Meeting Summary 在哪？」

「Copilot 要怎麼幫我準備客戶會議？」
```

Agent 判斷：

```text
Recurring Topic:
Meeting Preparation
```

接著自動建立：

```text
Tutorial v1
```

---

## Demo Part 2 — 從 Feedback Self-Improve

展示累積 Feedback：

```text
Average Rating:
2.9 / 5

Common Complaint:
「Step 3 很難懂。」
```

觸發 Periodic Feedback Review。

Agent 產生：

```text
Tutorial v2
```

展示：

```diff
Tutorial v1
→
Tutorial v2
```

並顯示：

```text
Reason:
Repeated feedback indicates Step 3 lacks context.
```

---

## Demo Part 3 — Product Update

輸入新的 Release Note：

```text
Meeting Summary has been renamed to Prepare.
```

Agent 找出：

```text
Affected Tutorial:
prepare-meeting.md
```

然後自動產生：

```text
Tutorial v3
```

Demo：

```diff
- Click "Meeting Summary"
+ Click "Prepare"
```

---

# 14. Demo Metrics

最後要讓評審看到量化改善。

例如：

| Metric             |  v1 |  v2 |
| ------------------ | --: | --: |
| Average Rating     | 2.9 | 4.4 |
| Negative Feedback  |   8 |   2 |
| Repeated Questions |   7 |   2 |
| Outdated Steps     |   1 |   0 |

Hackathon 可以使用 seeded demo data。

真正要傳達的是：

> **系統不是只有 Generate Content，而是會衡量 Content 有沒有成功，然後讓結果影響下一版。**

---

# 15. Scope Guardrails

不要做：

* 完整 LMS
* Video Generation
* Teams Integration
* 真正 Enterprise Authentication
* 複雜 Dashboard
* 十幾種 Persona
* 完整 Microsoft Graph Integration
* Automatic Fine-tuning

只專注兩條 Loop。

### Loop 1

```text
Ticket
↓
Tutorial
↓
Feedback
↓
Refinement
```

### Loop 2

```text
Release Note
↓
Affected Tutorial
↓
Update
```

只要這兩條 Loop 可以穩定 Demo，Hackathon 核心故事就成立。

---

# 16. Pitch

## One-Line Problem

> **IT 團隊不斷回答相同問題，同時還必須維護會隨著產品更新快速過期的 Training Content。**

## One-Line Solution

> **我們打造一個自我優化的 Training Knowledge Base：它知道使用者想學什麼、知道哪篇 Tutorial 不好用，也知道產品什麼時候發生改變。**

## Short Pitch

> Support Tickets 告訴我們員工需要學什麼。
> User Feedback 告訴我們他們還有哪裡看不懂。
> Release Notes 告訴我們產品改了什麼。
>
> 我們的 Agent 把這三種訊號結合起來，持續自動建立、更新與優化 Training Content。

## Core Message

> **Training 應該隨著每一位使用者持續變好，也應該隨著每一次產品更新保持最新。**
