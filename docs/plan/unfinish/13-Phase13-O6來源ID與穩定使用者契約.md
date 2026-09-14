# Phase 13：O6 來源 ID 與穩定使用者契約實作計畫

> **給實作者：** 依 checkbox 逐步執行；每個 Task 先建立失敗測試，再寫最小實作。執行時使用 `superpowers:executing-plans` 或同等逐項流程。

**目標：** 用真實的 GitHub Issue／PR payload 與手動匯入檔，把來源 ID 編碼、穩定使用者來源與各來源 `STABLE_KEYS` 固定下來，並產出維護者可以逐列核對的 mapping 表。

**架構：** 本 Phase 只做「來源事實」與「確定性編碼」兩件事：fixture 保存真實結構，`source_ids.py` 用純函式把上游識別轉成 canonical ID。驗簽在 Phase 30、正規化在 Phase 31、簽名白名單在 Phase 33 消費本 Phase 的核定紀錄。

**技術：** Python 3.12、pytest、JSON fixture；本 Phase 不呼叫 AWS、不呼叫模型、不連 GitHub API。

## 全域限制

- 唯一主來源是 [Training KB 設計 §7.1、§7.2、§9.1、§11.1、§18 O6](../../design/training-kb.md)。
- 前置為 [Phase 12：O3 發布切換整合驗證](./12-Phase12-O3發布切換整合驗證.md)；Phase 12 的 FAIL 只阻擋公開路徑，不阻擋本 Phase。下一階段是 [Phase 14：O5 模型可用性與參數驗證](./14-Phase14-O5模型可用性與參數驗證.md)。
- 本階段不驗簽、不正規化、不計算結構簽名、不寫入 DynamoDB 或 S3；模型不得產生任何 ID。
- **不建立 User 實體，也不建立執行期身分對照表。** 穩定使用者 ID 一律由來源提供或由來源的不變識別確定性編碼而來；顯示名稱（login、暱稱、寄件人姓名）不得用來推測是不是同一人。
- **O6 是前期阻擋 gate。** 核定紀錄中 `approved_by` 為空的 `(domain, event_type)` 一律 blocked，[Phase 30](./30-Phase30-GitHub-Webhook原始Body驗簽.md)、[Phase 31](./31-Phase31-Ticket與Release正規化.md)、[Phase 33](./33-Phase33-Rote結構簽名與STABLE_KEYS.md)、[Phase 42](./42-Phase42-Feedback與View固定匯入.md) 不得替該來源補猜清單。
- 以下程式檔均是實作時預計建立或修改；本計畫本身不代表它們已存在。

---

## 1. 你在整體流程的位置

```text
真實 GitHub payload / 維護者手動匯入檔
                |
                v
   [你在這裡：fixture + 確定性編碼 + 核定紀錄]
                |
  +-------------+--------------+--------------+
  |             |              |              |
Phase 30      Phase 31      Phase 33       Phase 42
驗簽 fixture   canonical ID   STABLE_KEYS   Feedback/View user
```

核定紀錄是文件與 fixture，不是第十一個業務實體，也不是執行期的使用者對照表。

## 2. 完成後看得到什麼

輸入真實的 `acme/copilot` Issue #128 與 PR #42（同時含 renamed 與 removed 兩個 Feature 變更）：

```text
來源                         | canonical 結果
-----------------------------+------------------------------------------------------
Issue #128                   | t_gh-acme-copilot-128     author u_gh-90210
PR #42 removed Legacy Export | r_gh-acme-copilot-pr42-1  event gh-acme-copilot-pr42
PR #42 renamed -> Prepare    | r_gh-acme-copilot-pr42-2  event gh-acme-copilot-pr42
手動 Discord 匯入            | t_dc-1180042-8891         author u_03（檔案直接提供）
```

把 `sender.login` 從 `kai-w` 改成 `kai-wong`，`u_gh-90210` 不變；把 `issue.number` 改成 129，`t_gh-acme-copilot-129` 跟著變。PR 編號 42 只出現在 `r_` 與事件 ID 的中段，任何欄位都不會單獨等於 `42`。

## 3. 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| 上游 ID／canonical ID | 上游 ID 是來源系統自己就有且不重複的識別（例如 repo 全名加 issue 編號）；canonical ID 是本系統保存用的 ID，固定加 `t_`／`r_`／`f_` 前綴。同一個 PR 改多個 Feature 時拆成多個子 Release，共用同一個來源事件 ID。 |
| 穩定使用者 ID | 同一個人在工單、回饋、瀏覽紀錄裡一模一樣的字串；不是顯示名稱。 |
| `STABLE_KEYS` | 某個來源與事件型別固定必備的 payload 最上層 key 清單，由核定紀錄決定。 |
| 核定紀錄 | 維護者簽收過的「來源 → 清單與編碼」對照文件；沒簽收就是 blocked。 |
| O6／D02／F02／F14 | 設計文件的編號：`O1`–`O7` 是[設計 §18](../../design/training-kb.md) 的待確認事項（O6 就是本 Phase 這一條），`D` 與 `F` 開頭是 §19 已解決的資料／功能決策。 |

## 4. 預計檔案

| 動作 | 路徑 | 責任 |
|---|---|---|
| 新增 | `tests/fixtures/github/issue-opened.json`、`pull-request-merged.json` | 真實結構的 Issue 與 PR payload（PR 含 renamed 與 removed 兩個變更），Phase 30／31 共用。 |
| 新增 | `tests/fixtures/manual/discord-message.json`、`support-email.json`、`changelog-entry.json` | 三份手動匯入檔，同一外層格式。 |
| 新增 | `tests/fixtures/o6/approved-sources.json`、`src/training_kb/source_ids.py` | 各來源的 `STABLE_KEYS`、ID 編碼與核定欄位；確定性 ID 與穩定 user 編碼純函式。 |
| 新增 | `docs/plan/report/o6-mapping.md` | 由核定紀錄渲染的九欄 mapping 表，交維護者逐列簽收。 |
| 測試 | `tests/unit/test_source_ids.py` | 編碼穩定性、PR number 不是 `Release.id`、拒絕猜測。 |
| 測試 | `tests/integration/test_o6_fixture_contract.py` | fixture 與核定紀錄一致；未核定即 blocked；輸出 mapping 表。 |

## 5. 固定介面

### Consumes

```text
設計 §7.1：Ticket.author、Feedback.user、TUTORIAL_VIEW.user 必須是同一字串
設計 §18 O6：對已有來源穩定 ID 做確定性編碼，匯入檔採同一 user 命名方式
D02：上游 ID 已全域唯一；接入層產出 t_ / r_ / f_ 前綴且不撞號
F14：多 Feature 變更拆成多個子 Release，保留相同父來源事件識別碼
IngressError(message: str, fields: tuple[str, ...])
```

### Produces

```python
def github_ticket_id(owner: str, repo: str, number: int) -> str: ...
def github_release_id(owner: str, repo: str, pr_number: int, k: int) -> str: ...
def github_source_event_id(owner: str, repo: str, pr_number: int) -> str: ...
def github_user_id(numeric_id: int) -> str: ...
def stable_user_from_import(value: str) -> str: ...

@dataclass(frozen=True)
class SourceApproval:
    domain: str
    event_type: str
    adapter: str
    stable_keys: tuple[str, ...]
    fixture: str            # 相對於 tests/fixtures/ 的路徑
    id_encoder: str         # 事件 ID 編碼函式名或「檔案提供」
    stable_user_source: str # 穩定 user 來自哪個欄位
    approved_by: str
    approved_at: str

def load_source_approvals(path: str | Path) -> tuple[SourceApproval, ...]: ...
def approved_stable_keys(rows: Sequence[SourceApproval]) -> dict[tuple[str, str], frozenset[str]]: ...

# 本 Phase 另建的兩個輔助純函式（00A §6.8 未列名，屬 source_ids.py 內部延伸）
def sub_release_ids(owner: str, repo: str, pr_number: int,
                    features: Sequence[str]) -> tuple[tuple[str, str], ...]: ...
def render_mapping_table(rows: Sequence[SourceApproval]) -> str: ...
```

`sub_release_ids` 是第 6.2 節「依 Feature 名稱升序配 `k`」的唯一實作處，回 `(feature, release_id)`
序對；空清單與重複 Feature 名稱一律 `IngressError(fields=("feature",))`。`render_mapping_table`
把核定紀錄渲染成第 6.3 節的九欄，讓 `docs/plan/report/o6-mapping.md` 由紀錄產生而不是手抄。

`SourceApproval` 的九個欄位就是[第 6.3 節](#63-維護者核對用的-mapping-表) mapping 表的九欄，順序一致，報告可直接由紀錄渲染。[Phase 33](./33-Phase33-Rote結構簽名與STABLE_KEYS.md) 的 `STABLE_KEYS` 常數只能由 `approved_stable_keys()` 產生，或逐條抄寫本 Phase 的核定紀錄；不在紀錄裡的 `(domain, event_type)` 一律 blocked。

## 6. 設計細節

### 6.1 fixture 保留真實結構

GitHub `issues` 事件的最上層固定有 `action`、`issue`、`repository`、`sender`，另有 `assignee`、`changes`、`enterprise`、`installation`、`organization` 等視情況出現的欄位。F02 只規定「每一種來源與事件類型各有自己的固定必備 top-level key 清單」；已核定的那份清單就是[設計 §7.2](../../design/training-kb.md) 寫出的前四個，其餘不進 `STABLE_KEYS`。fixture 精簡但不改結構：

```json
{
  "action": "opened",
  "issue": {"id": 2410551234, "node_id": "I_kwDOABCD12MAAAAB", "number": 128,
            "title": "會前摘要在哪裡開啟？", "state": "open",
            "created_at": "2026-09-01T08:12:30Z",
            "user": {"login": "kai-w", "id": 90210, "type": "User"}},
  "repository": {"id": 552301, "name": "copilot", "full_name": "acme/copilot",
                 "owner": {"login": "acme", "id": 771, "type": "Organization"}},
  "sender": {"login": "kai-w", "id": 90210, "type": "User"}
}
```

`pull_request` 事件的最上層是 `action`、`number`、`pull_request`、`repository`、`sender`，比 Issue 多一個最上層 `number`，**不能直接套用 Issue 清單**；PR 候選清單由 fixture 提出，維護者核定後才寫進紀錄。手動來源的匯入檔一律是「批次外層 + items」，每筆直接提供 canonical 欄位：

```json
{
  "source": "discord", "domain": "discord.com", "adapter": "discord_manual",
  "batch_id": "manual-2026-09-06-01",
  "items": [{"id": "t_dc-1180042-8891", "text": "如何看到開會前整理的重點？",
             "author": "u_03", "ts": "2026-09-02T03:14:00Z", "project_id": "demo"}]
}
```

email 與 changelog 用同一外層，只換 `source`／`adapter` 與 items 欄位；Feedback 與 View 匯入檔同外層，由 Phase 42 消費。

### 6.2 ID 編碼與穩定使用者

```text
github_ticket_id("acme","copilot",128)   -> t_gh-acme-copilot-128
github_release_id("acme","copilot",42,1) -> r_gh-acme-copilot-pr42-1
github_source_event_id("acme","copilot",42) -> gh-acme-copilot-pr42
github_user_id(90210)                    -> u_gh-90210

PR #42 --+--> removed Legacy Export                       --> r_...-pr42-1
         +--> renamed Meeting Summary -> Prepare          --> r_...-pr42-2
         +--> 兩者共用 source_event_id = gh-acme-copilot-pr42

42 ---X--> Release.id      login ---X--> 穩定使用者 ID（改名不改人，只用數字 id）
```

`k` 從 1 起算，順序由子變更的 Feature 名稱升序決定，讓同一個 PR 重送得到完全相同的一組 ID（`Legacy Export` 排在 `Prepare` 前面，所以 removed 是 `k=1`、renamed 是 `k=2`；renamed 的 Feature 名稱取改名後的新名稱）。`owner`／`repo` 先轉小寫，只允許 `[a-z0-9._-]`，其餘字元一律拒絕而不是取代，避免兩個不同 repo 編出同一個 ID。穩定使用者只有兩個合法來源：

- **GitHub：** 用 `sender["id"]`（數字、改名不變），不用 `login`。`github_user_id` 是純函式，不查表。
- **手動匯入：** 檔案的 `author`／`user` 欄位直接就是 ID（Demo 用 `u_01`～`u_10`）。`stable_user_from_import` 只做格式檢查，缺值時拋 `IngressError`，不補值、不從顯示名稱猜、不隨機產生。

兩種形狀**共存但不互換**：真實 GitHub 事件一律 `u_gh-<數字 id>`，Demo 種子（[Phase 56](./56-Phase56-O7核定Demo種子資料.md)）一律 `u_01` 這種形狀。系統不建立兩者之間的對照表，同一批資料內也不得混用；跨來源比對（[Phase 54](./54-Phase54-重開票與呼叫規則指標.md) 的重開票）只在同一形狀內成立。`project_id` 一律用設定檔的值（預設 `demo`），不在匯入檔自創第二套專案代號。

### 6.3 維護者核對用的 mapping 表

`docs/plan/report/o6-mapping.md` 固定九欄，維護者逐列簽收；`核定者` 為空即 blocked。

| domain | event_type | adapter | STABLE_KEYS | fixture | 事件 ID 編碼 | 穩定 user 來源 | 核定者 | 核定日期 |
|---|---|---|---|---|---|---|---|---|
| `github.com` | `issues` | `github_issue` | action, issue, repository, sender | `github/issue-opened.json` | `github_ticket_id` | `sender.id` | `docs/design/training-kb.md §7.2` | 2026-09-13 |
| `github.com` | `pull_request` | `github_pr` | 候選：action, number, pull_request, repository, sender | `github/pull-request-merged.json` | `github_release_id` | `sender.id` | 待維護者核定 | 待維護者核定 |
| `discord.com` | `manual_batch` | `discord_manual` | 候選：source, domain, adapter, batch_id, items | `manual/discord-message.json` | 檔案提供 | 檔案 `author` | 待維護者核定 | 待維護者核定 |
| `mail.local` | `manual_batch` | `email_manual` | 候選：source, domain, adapter, batch_id, items | `manual/support-email.json` | 檔案提供 | 檔案 `author` | 待維護者核定 | 待維護者核定 |
| `changelog.local` | `manual_batch` | `changelog_manual` | 候選：source, domain, adapter, batch_id, items | `manual/changelog-entry.json` | 檔案提供 | 不適用 | 待維護者核定 | 待維護者核定 |

只有 `("github.com", "issues")` 的清單來自[設計 §7.2](../../design/training-kb.md) 已寫出的核定內容，因此它的核定者欄位記的是**文件出處**而不是個人簽收（00A §4.2：「只有 `("github.com", "issues")` 的 `action, issue, repository, sender` 已核定」）；其餘四列是本計畫依 fixture 提出的**候選**，`approved_by` 留空即 blocked，核定前不得當成已定案。九欄與 `SourceApproval` 的九個欄位一一對應（`fixture` 欄存相對於 `tests/fixtures/` 的路徑）。

## 7. TDD Tasks

### Task 1：鎖定確定性 ID 編碼

- [x] **Step 1：建立失敗測試**

```python
def test_github_ids_are_deterministic_and_never_bare_pr_number():
    assert github_ticket_id("Acme", "Copilot", 128) == "t_gh-acme-copilot-128"
    assert github_release_id("acme", "copilot", 42, 1) == "r_gh-acme-copilot-pr42-1"
    assert github_release_id("acme", "copilot", 42, 2) != "r_gh-acme-copilot-pr42-1"
    assert github_source_event_id("acme", "copilot", 42) == "gh-acme-copilot-pr42"
    with pytest.raises(IngressError) as error:
        github_ticket_id("acme/evil", "copilot", 1)
    assert error.value.fields == ("owner",)
    with pytest.raises(IngressError):
        github_release_id("acme", "copilot", 42, 0)
```

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_source_ids.py -q -k github_ids
```

預期：FAIL，訊號包含 `cannot import name 'github_ticket_id'`。

- [x] **Step 3：建立最小實作**

```python
SLUG_PATTERN = re.compile(r"^[a-z0-9._-]+$")

def _part(value: str, field: str) -> str:
    lowered = value.strip().lower() if isinstance(value, str) else ""
    if not SLUG_PATTERN.fullmatch(lowered):
        raise IngressError(f"{field} 含不允許的字元", (field,))
    return lowered

def _positive(value: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise IngressError(f"{field} 必須是大於 0 的整數", (field,))
    return value

def _repo_part(owner: str, repo: str) -> str:
    return f"{_part(owner, 'owner')}-{_part(repo, 'repo')}"

def github_ticket_id(owner: str, repo: str, number: int) -> str:
    return f"t_gh-{_repo_part(owner, repo)}-{_positive(number, 'number')}"

def github_release_id(owner: str, repo: str, pr_number: int, k: int) -> str:
    pr, index = _positive(pr_number, "pr_number"), _positive(k, "k")
    return f"r_gh-{_repo_part(owner, repo)}-pr{pr}-{index}"

def github_source_event_id(owner: str, repo: str, pr_number: int) -> str:
    return f"gh-{_repo_part(owner, repo)}-pr{_positive(pr_number, 'pr_number')}"
```

- [x] **Step 4：補子 Release 排序並跑完整檔案確認綠燈**

同一個 PR 的子變更先依 Feature 名稱升序排好，再從 1 開始逐一配 `k`，這樣同一份 PR fixture 重送兩次會得到完全相同的一組 `r_` ID。加一個測試：對同一份 fixture 跑兩次，兩次 ID 清單相等。

```bash
uv run pytest tests/unit/test_source_ids.py -q
```

- [x] **Step 5：提交**

```bash
git add src/training_kb/source_ids.py tests/unit/test_source_ids.py
git commit -m "feat(ingress): 固定來源識別碼編碼"
```

### Task 2：鎖定穩定使用者只能來自來源

- [x] **Step 1：建立失敗測試**

```python
SENDER = {"login": "kai-w", "id": 90210, "type": "User"}

@pytest.mark.parametrize("bad", ["", "  ", "Kai Wong", "u_01!"])
def test_stable_user_comes_only_from_source(bad):
    renamed = {**SENDER, "login": "kai-wong"}
    assert github_user_id(SENDER["id"]) == "u_gh-90210"
    assert github_user_id(renamed["id"]) == "u_gh-90210"
    with pytest.raises(IngressError) as error:
        stable_user_from_import(bad)
    assert error.value.fields == ("user",)
```

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_source_ids.py -q -k user
```

預期：FAIL，訊號包含 `cannot import name 'github_user_id'`。

- [x] **Step 3：建立最小實作**

```python
USER_PATTERN = re.compile(r"^[a-z0-9_-]{2,64}$")

def github_user_id(numeric_id: int) -> str:
    if isinstance(numeric_id, bool) or not isinstance(numeric_id, int) or numeric_id <= 0:
        raise IngressError("GitHub 使用者識別必須是正整數", ("user",))
    return f"u_gh-{numeric_id}"

def stable_user_from_import(value: str) -> str:
    candidate = value.strip() if isinstance(value, str) else ""
    if not USER_PATTERN.fullmatch(candidate):
        raise IngressError("匯入檔必須提供合法的穩定使用者 ID", ("user",))
    return candidate
```

- [x] **Step 4：補跨來源一致性測試並跑完整檔案確認綠燈**

加一個測試：從 `tests/fixtures/manual/` 的三份匯入檔取同一位 Demo 使用者（Discord 與 email 各一筆 `author = u_03`；changelog 是 Release 匯入檔，穩定 user「不適用」，測試改斷言它沒有 `author`／`user` 欄位），再以同一個字串建 `Ticket`、`Feedback`、`TutorialView`，斷言 Ticket 的 `author`、Feedback 的 `user`、View 的 `user` 三個字串完全相同（不做大小寫或空白正規化後再比）。**Feedback／View 的匯入檔 fixture owner 是 [Phase 42](./42-Phase42-Feedback與View固定匯入.md)（00A §3.2），本 Phase 不建立那兩份檔。**

```bash
uv run pytest tests/unit/test_source_ids.py -q
```

- [x] **Step 5：提交**

```bash
git add src/training_kb/source_ids.py tests/fixtures/manual tests/unit/test_source_ids.py
git commit -m "feat(ingress): 只接受來源提供的穩定使用者"
```

### Task 3：核定紀錄與未核定即 blocked

- [x] **Step 1：建立失敗測試**

```python
FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "tests" / "fixtures"   # 不依賴 cwd

def test_unapproved_source_is_blocked_and_fixture_matches_keys():
    approvals = load_source_approvals(FIXTURE_ROOT / "o6/approved-sources.json")
    keys = approved_stable_keys(approvals)
    assert keys[("github.com", "issues")] == frozenset({"action", "issue", "repository", "sender"})
    assert ("discord.com", "manual_batch") not in keys
    for row in approvals:
        payload = json.loads((FIXTURE_ROOT / row.fixture).read_text("utf-8"))
        assert set(row.stable_keys) <= set(payload)
```

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/integration/test_o6_fixture_contract.py -q
```

預期：FAIL，訊號包含 `cannot import name 'load_source_approvals'`。

- [x] **Step 3：建立最小實作**

```python
def load_source_approvals(path: str | Path) -> tuple[SourceApproval, ...]:
    rows = json.loads(Path(path).read_text("utf-8"))
    return tuple(
        SourceApproval(**{**row, "stable_keys": tuple(row["stable_keys"])}) for row in rows
    )

def approved_stable_keys(rows: Sequence[SourceApproval]) -> dict[tuple[str, str], frozenset[str]]:
    approved: dict[tuple[str, str], frozenset[str]] = {}
    for row in rows:
        if not row.approved_by.strip() or not row.approved_at.strip():
            continue
        approved[(row.domain, row.event_type)] = frozenset(row.stable_keys)
    return approved
```

- [x] **Step 4：產出 mapping 表並跑完整檔案確認綠燈**

把 `load_source_approvals()` 的九個欄位依序寫成 `docs/plan/report/o6-mapping.md` 的九欄。再加一個測試：把 fixture 的 `issue.id`、`created_at` 與 `title` 換成別的值後重跑，canonical ID 只隨 `issue.number` 改變，穩定 user 完全不變。

```bash
uv run pytest tests/integration/test_o6_fixture_contract.py -q
```

- [x] **Step 5：提交**

```bash
git add src/training_kb/source_ids.py tests/fixtures tests/integration/test_o6_fixture_contract.py docs/plan/report/o6-mapping.md
git commit -m "test(ingress): 核定來源清單與 mapping 表"
```

## 8. 驗收矩陣

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy | Issue #128 fixture；PR #42 兩個 Feature 變更 | `t_gh-acme-copilot-128` 配 author `u_gh-90210`；兩個不同 `r_` ID 共用 `gh-acme-copilot-pr42`。 |
| Failure | 匯入檔缺 `author` 或只給顯示名稱 | `IngressError(fields=("user",))`，不補值也不產生新 ID。 |
| Failure | `("github.com","pull_request")` 尚未核定 | 不出現在 `approved_stable_keys()`，Phase 33 該來源 blocked。 |
| Boundary | `sender.login` 改名、`issue.title` 改字；`owner="acme/evil"`、`k=0` | 前者穩定 user 與 canonical ID 都不變；後者明確拒絕，不做字元取代。 |

人工驗收：打開 `docs/plan/report/o6-mapping.md`，對每一列用 fixture 手動比對 `STABLE_KEYS`、ID 編碼與 user 來源，再由維護者填入核定者與日期。九欄沒有填滿就不是核定完成。

## 9. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| `Release.id` 就是 `42`；改名後變成另一個人 | 把顯示編號當全域唯一；用 `login` 當穩定 ID | 改用 `github_release_id` 與 `sender.id`；停止 Phase 31 並重跑一致性測試。 |
| PR 沿用 Issue 的四個 key | 未區分事件型別 | 依 F02 各自核定；未核定就讓 PR 路徑 blocked。 |
| 匯入檔沒有 user 就自動編號 | 把缺值當可補 | 直接拒絕並指出欄位；不得隨機或用模型產生。 |
| 建了一張 user 對照表，或把 Demo 的 `r_42` 當真實 GitHub ID | 想用顯示名稱配對；混用合成配方與真實編碼 | 停止；設計明示不建立 User 或身分對照表，Demo ID 只在 Phase 56 的種子使用。 |

## 10. 來源與 Rule 對照

primary 與「相關」的分工依 [00B 需求覆蓋對照](00B-需求覆蓋對照.md) 第 3.2 節；標「相關」的測試保留，但不得宣稱是該 Rule 的唯一驗收。

- [接入來源事件.feature](../../spec/features/接入來源事件.feature)
  - Rule 24：「正規化物件的 id 直接使用已全域唯一的上游識別碼」→ **primary**。Task 1 斷言編碼確定性且 PR 編號不單獨成為 `Release.id`。
  - Rule 22：「Ticket 接入時 id、source、text、author、ts 與 project_id 必填」→ 相關（primary 在 [Phase 31](./31-Phase31-Ticket與Release正規化.md)）：Task 2 只補「匯入檔缺 `author` 即拒絕」這個案例。
  - Rule 3：「來源簽名使用來源網域、有意義的 header 名稱與穩定 payload key 計算」→ 相關（primary 在 [Phase 33](./33-Phase33-Rote結構簽名與STABLE_KEYS.md)）：Task 3 只提供核定紀錄，簽名計算本身不在本 Phase。
- [收集教學回饋.feature](../../spec/features/收集教學回饋.feature) Rule 9：「Feedback 接入時必須提供穩定使用者 ID」→ 相關（primary 在 [Phase 42](./42-Phase42-Feedback與View固定匯入.md)）：本 Phase 只提供 `stable_user_from_import` 的編碼契約與缺值拒絕。
- [依改版更新教學.feature](../../spec/features/依改版更新教學.feature) Rule 1：「從 PR diff 或 changelog 抽出 feature、kind、old_name 與 new_name」→ 相關（primary 在 [Phase 37](./37-Phase37-Rote-Agent回退與成功提交.md)）：本 Phase 只提供含 renamed 與 removed 兩個子變更的 PR fixture。
- 設計 §7.1、§11.1、§18 O6：跨來源共用同一個穩定使用者 ID，對已有來源穩定 ID 做確定性編碼，不建立身分對照表；Demo 的 `r_42` 是合成上游 ID，與人看的 PR #42 分開。
- [GitHub webhook 事件與 payload](https://docs.github.com/en/webhooks/webhook-events-and-payloads)：`issues` 的最上層含 `action`／`issue`／`repository`／`sender`；`pull_request` 另有最上層 `number`。

## 11. 完成清單

- [x] Issue 與 PR fixture 是真實結構，僅精簡欄位、未改鍵名；手動 Discord／email／changelog 匯入檔使用同一外層格式。
- [x] 四個 `github_*` 編碼函式的輸出與本文件逐字相同；PR 編號不會單獨成為 `Release.id`，多 Feature 共用同一個來源事件 ID。
- [x] 穩定使用者只來自來源數字 id 或匯入檔欄位，沒有顯示名稱推測與隨機值。
- [x] `approved-sources.json` 中未填核定者的來源不會進入 `approved_stable_keys()`。
- [x] `docs/plan/report/o6-mapping.md` 九欄齊全並已交維護者核對（狀態：待維護者核定，四列 blocked）。
- [x] 尚未核定時，Phase 30／31／33／42 的對應來源標為 blocked，未宣稱 O6 已完成。
