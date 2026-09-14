# O1：metadata sort key

Status: accepted
Date: 2026-09-14
Approver: Timmy Lin
Sort-Key: META

上面四個欄位是 `tests/unit/test_keys.py::test_metadata_sort_key_matches_the_recorded_o1_decision`
與 `rg -n '^(Status|Date|Approver|Sort-Key): '` 共同核對的固定欄位，**不得在同一行加註解**，
否則 `^Status: (accepted|rejected)$` 這類行尾錨定的正則會比不到。

## 核定依據

- [設計 §18 O1](../design/training-kb.md#s18) 把 metadata SK 列為「ERM Project note 明留未定義」，
  並給出黑客松最省的建議：「各 metadata 統一 META；Step 保持既定 REFERENCES 鍵」。
- [設計 §9.1](../design/training-kb.md#s9) 的十列表格中，九個實體的 SK 標「建議 META」或
  「META，設計選擇」，只有 `TUTORIAL_STEP` 已明確是 `REFERENCES#<Feature PK>`。
- [00A 共用契約 §6.2](../plan/unfinish/00A-共用契約與名詞.md) 已把 `META` 的 canonical 簽名寫成
  `META: str`（值 `"META"`），owner 是 P05，P06 起全部消費。
- 本紀錄由 Phase 05 實作者代為建檔，核定者為 repo 維護者（git `user.name`）。維護者若不同意，
  改寫本檔的 `Status`／`Sort-Key` 並同步改 `src/training_kb/keys.py` 的 `META` 常數即可；
  測試會強制兩者一致，不允許各實體各自猜值，也不允許空字串。

## 決策內容

- 十個邏輯實體的 metadata item 一律用 sort key `META`；`TUTORIAL_STEP` 不在此列，
  它以 `REFERENCES#<Feature PK>` 當 SK（設計 §9.1），所以 **STEP 沒有 `META` item**。
- 關係邊的 SK 是 `<關係>#<終點 PK>`，與 `META` 在同一張表上只差在 SK 的形狀；
  `scan_entity` 預設 `meta_only=True`（只回 `SK == META`），`get_steps` 是唯一要傳
  `meta_only=False` 的呼叫（00A §3.3、§3.6）。
- 採用 `META` 不改變任何實體的 PK 形狀，也不新增欄位或第十一個實體。

## 對十實體的影響

| 邏輯實體 | PK（`keys.py` builder） | SK | 受影響的讀寫路徑 |
|---|---|---|---|
| TUTORIAL | `TUTORIAL#<slug>`（`tutorial_pk`） | `META` | P06 `get_meta`／`put_meta`／`update_meta`、P08 `list_tutorials`、P24 發布時更新 `current_version`、P26 退役。 |
| TUTORIAL_VERSION | `VERSION#<slug>@v<n>`（`version_pk`） | `META` | P06 metadata 讀寫、P08 `list_versions_of_tutorial`、P23 建版、P24／P25 發布、P55 前後版比較。 |
| TUTORIAL_STEP | `STEP#<slug>@v<n>#<i>`（`step_pk`） | `REFERENCES#<FEATURE PK>` | **不走 `META`**：P07 `put_edge` 寫入、P08 `get_steps`（`meta_only=False`）以 `parse_step_pk` 還原步驟號、P27 功能反查引用步驟。 |
| FEATURE | `FEATURE#<建立時名稱>`（`feature_pk`） | `META` | P06 metadata 讀寫、P08 `list_features`、P49 alias 定位；改名只動 `name`／`aliases`，PK 不遷移。 |
| TICKET | `TICKET#<id>`（`ticket_pk`） | `META` | P06 metadata 讀寫、P08 `list_tickets`、P38 分群、P40 CREATE／KEEP；`ASKS_ABOUT#` 邊與本體同 PK。 |
| RELEASE | `RELEASE#<id>`（`release_pk`） | `META` | P06 metadata 讀寫、P31 正規化後寫入、P49–P52 Release 流程。 |
| FEEDBACK | `FEEDBACK#<id>`（`feedback_pk`） | `META` | P06 metadata 讀寫、P42 固定匯入、P43 類別判定、P53 指標；`REFERS_TO#` 邊與本體同 PK。 |
| TUTORIAL_VIEW | `VIEW#<三元組 SHA-256>`（`view_pk`） | `META` | P06 metadata 讀寫、P42 匯入去重、P54 重開票與瀏覽指標；同三元組重送得到同一把鍵。 |
| AUTHORING_RULE | `RULE#<rule_id>`（`rule_pk`） | `META` | P06 metadata 讀寫、P19 active 規則選取、P28 `APPLIED_TO#` 投影重建、P55 狀態轉移。 |
| PROVEN_WORKFLOW | `PROC#<signature>`（`proc_pk`） | `META` | P06 metadata 讀寫、P34 兩層命中、P35 生命週期；沒有圖譜邊。 |

非業務前綴 `OPS#`、`CONFIG#`、`SEQ#`、`LEASE#` 不走模型也不走 builder，由 P10 的
`put_meta_item`／`get_meta_item` 直接組字串（00A §3.6），本決策不涵蓋它們的 SK。

## 若改為 rejected

必須在本檔寫出**具體替代字串**（例如 `#META` 或 `ENTITY`）與改用理由，再同步修改
`src/training_kb/keys.py` 的 `META` 常數；測試只比對常數與 `Sort-Key` 是否一致，
不接受空字串，也不接受各實體各自定義。

## 這份紀錄沒有宣稱什麼

- accepted 只代表鍵**命名**定案。實表 CRUD（真實 DynamoDB 的 metadata 讀寫與 `_revision`
  樂觀鎖）是 [Phase 06](../plan/unfinish/06-Phase06-Repository-Metadata與實體讀寫.md) 與
  [Phase 09](../plan/unfinish/09-Phase09-AWS資料資源與最小IAM.md) 各自留證，Phase 05 只跑本機契約測試。
- 本決策不影響 O2、O3、O4、O5、O6、O7 任何一個 gate 的狀態。
