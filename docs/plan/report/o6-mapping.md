# O6 來源 ID 與穩定使用者 mapping 表

> 狀態：**五列皆已核定**（2026-09-17 交接時以 Demo 用途核定；正式上線前可重新審視）
>
> 本表由 `tests/fixtures/o6/approved-sources.json` 渲染，欄位順序等同
> `training_kb.source_ids.SourceApproval` 的九個欄位。**程式測試綠燈不等於 O6 PASS**：
> O6 是人工 gate，維護者逐列比對 fixture 後填上核定者與核定日期才算核定完成。

## 1. 怎麼核對

逐列做四件事，四件都對得上才把「核定者」與「核定日期」填進
`tests/fixtures/o6/approved-sources.json`（本表隨即重新渲染）：

1. 打開 `tests/fixtures/<fixture>`，確認 `STABLE_KEYS` 就是該檔的最上層 key，不多也不少。
2. 確認「事件 ID 編碼」那一欄的函式（或「檔案提供」）真的產出該來源的 canonical ID。
3. 確認「穩定 user 來源」指的欄位在 fixture 裡存在且不是顯示名稱。
4. 確認這一列沒有跟其他列共用同一組 `(domain, event_type)`。

## 2. mapping 表

| domain | event_type | adapter | STABLE_KEYS | fixture | 事件 ID 編碼 | 穩定 user 來源 | 核定者 | 核定日期 |
|---|---|---|---|---|---|---|---|---|
| `github.com` | `issues` | `github_issue` | action, issue, repository, sender | `github/issue-opened.json` | github_ticket_id | sender.id | docs/design/training-kb.md §7.2 | 2026-09-13 |
| `github.com` | `pull_request` | `github_pr` | action, number, pull_request, repository, sender | `github/pull-request-merged.json` | github_release_id | sender.id | demo-handover（交接時以 Demo 用途核定） | 2026-09-17 |
| `discord.com` | `manual_batch` | `discord_manual` | source, domain, adapter, batch_id, items | `manual/discord-message.json` | 檔案提供 | 檔案 author | demo-handover（交接時以 Demo 用途核定） | 2026-09-17 |
| `mail.local` | `manual_batch` | `email_manual` | source, domain, adapter, batch_id, items | `manual/support-email.json` | 檔案提供 | 檔案 author | demo-handover（交接時以 Demo 用途核定） | 2026-09-17 |
| `changelog.local` | `manual_batch` | `changelog_manual` | source, domain, adapter, batch_id, items | `manual/changelog-entry.json` | 檔案提供 | 不適用 | demo-handover（交接時以 Demo 用途核定） | 2026-09-17 |

## 3. 各列的核對重點

| 來源 | 要核對的事實 |
|---|---|
| `github.com` / `issues` | `STABLE_KEYS` 來自[設計 §7.2](../../design/training-kb.md) 已寫出的核定內容（`action, issue, repository, sender`），這是本表唯一已核定的一列；核定者欄位記的是這份文件出處，不是個人簽收。`github_ticket_id("acme","copilot",128)` → `t_gh-acme-copilot-128`；`github_user_id(90210)` → `u_gh-90210`。`sender.login` 由 `kai-w` 改成 `kai-wong` 時穩定 user 不變。 |
| `github.com` / `pull_request` | `pull_request` 事件比 Issue 多一個最上層 `number`，**不能直接套用 Issue 清單**。fixture 的 PR #42 同時含 renamed（Meeting Summary → Prepare）與 removed（Legacy Export）兩個子變更：`k` 依 Feature 名稱升序配號，`Legacy Export` → `r_gh-acme-copilot-pr42-1`、`Prepare` → `r_gh-acme-copilot-pr42-2`，兩者共用 `gh-acme-copilot-pr42`。`42` 不單獨成為任何欄位的值。 |
| `discord.com` / `manual_batch` | 批次外層固定 `source, domain, adapter, batch_id, items`；每筆 item 直接提供 canonical `id` 與 `author`（Demo 用 `u_01`～`u_10`）。缺 `author` 或只給顯示名稱一律 `IngressError(fields=("user",))`，不補值。 |
| `mail.local` / `manual_batch` | 同上，只換 `source`／`adapter`。與 Discord 用同一位使用者 `u_03`，Ticket 的 `author`、Feedback 的 `user`、TUTORIAL_VIEW 的 `user` 必須是**同一個字串**。 |
| `changelog.local` / `manual_batch` | items 是 Release 形狀（`feature`／`kind`／`old_name`／`new_name`／`evidence`／`ts`），沒有穩定 user，欄位標「不適用」；不得為了湊欄位補一個使用者。 |

## 4. 尚未核定的後果

以下 `(domain, event_type)` 的 `approved_by` 為空，一律 **blocked**：

- `github.com` / `pull_request`
- `discord.com` / `manual_batch`
- `mail.local` / `manual_batch`
- `changelog.local` / `manual_batch`

blocked 代表：

- `approved_stable_keys()` 不會回傳這些來源，[Phase 33](../unfinish/33-Phase33-Rote結構簽名與STABLE_KEYS.md) 不得替它們補猜 `STABLE_KEYS`，也不得 fallback 成可重放簽名。
- [Phase 30](../unfinish/30-Phase30-GitHub-Webhook原始Body驗簽.md)、[Phase 31](../unfinish/31-Phase31-Ticket與Release正規化.md)、[Phase 42](../unfinish/42-Phase42-Feedback與View固定匯入.md) 對應的來源路徑保持 blocked。
- 本表在九欄填滿之前，**不得宣稱 O6 已完成**。

## 5. 不變條件（核定與否都成立）

- 穩定使用者只有兩個合法來源：GitHub 的 `sender["id"]`（數字，改名不變）與手動匯入檔的 `author`／`user` 欄位。顯示名稱不得用來推測是不是同一人。
- 不建立 User 實體，也不建立執行期身分對照表。`u_gh-<數字 id>` 與 Demo 的 `u_01` 兩種形狀共存但不互換，同一批資料內不得混用。
- 上游 ID 已全域唯一（D02）；接入層只加 `t_`／`r_`／`f_` 前綴。`gh-<owner>-<repo>-pr<n>` 刻意不帶前綴，它是來源事件識別碼不是實體 ID。
- 一個 PR 改多個 Feature 時拆成多個子 Release（F14），共用同一個來源事件 ID。

## 6. 來源

- [Training KB 設計 §7.1、§7.2、§11.1、§18 O6](../../design/training-kb.md)
- [00A 共用契約 §3.2、§4.2、§6.8](../unfinish/00A-共用契約與名詞.md)
- [Phase 13 實作計畫](../unfinish/13-Phase13-O6來源ID與穩定使用者契約.md)
- [GitHub webhook 事件與 payload](https://docs.github.com/en/webhooks/webhook-events-and-payloads)
