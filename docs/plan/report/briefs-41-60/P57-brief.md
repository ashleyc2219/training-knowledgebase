# P57 brief — S3 靜態教學站與回饋下載

文件：`docs/plan/unfinish/57-Phase57-S3靜態教學站與回饋下載.md`（W0 已更新，commit `fde3f65`）。波次 **W1**。

## 1. 單一交付物與停止點
- **交付物：** 完整的公開教學站——`SiteRenderer` 三個方法的完整實作（版本選擇／差異連結／版本紀錄／退役）、`demo/site_assets/{widget.js,style.css}`，以及**只公開 `site/*`** 的 bucket policy ＋ website hosting。
- **停止點：** 公開範圍就是 `site/`。任何私有前綴（`tutorials/`、`operations/`、`stepfunctions/`、`demo/previews/`）可公開讀即停止部署；widget 只在瀏覽器產生檔案，**永遠不得顯示「已送出」**。

## 2. 已存在、直接重用
| file:name | 用途／注意 |
|---|---|
| `src/training_kb/site.py:SiteRenderer` | `__init__(*, notice="", batch="", categories=(), asset_prefix="/site/assets")` 四參數都有預設；三個 render 方法簽名**不得改** |
| `src/training_kb/site.py:_retired_block`／`_successor_line`／`SUCCESSOR_PREFIX`／`RETIRED_PLACEHOLDER` | **退役區塊已經做完了**（P26＋修正波 `f1ef75a`，D-83），兩個頁面共用；href 逐字 `../<slug>/index.html`（D-78）。**不要重寫、不要改名、不要搬位置** |
| `src/training_kb/site.py:_version_number`／`_items`／`_SECTIONS` | 版號用 `parse_version_id(...)[1]`（D-19，不自訂 `version_number`） |
| `src/training_kb/publishing.py:_diff_copy_key(version_id)` | **已經回 `tutorials/<slug>/v<n>.diff.txt`**；docstring 明寫「Phase 57 的 `site_diff_key` 回同一個字串」→ 改成公開名稱即可 |
| `src/training_kb/publishing.py:` `site_key`／`tutorial_index_key`／`site_index_key`／`_public_key`／`_public_pairs`／`public_site_keys`／`UNPUBLISHED_MARKER`／`promote_site_objects`／`Publisher` | D-54；只消費不重定義 |
| `src/training_kb/content.py:PUBLIC_SITE_PREFIX = "site/"`（P22）／`RETIRED_NOTICE`（P26）／`parse_version_id`（P20） | `SITE_PREFIX` 是 `PUBLIC_SITE_PREFIX` 的別名，值必須相同 |
| `src/training_kb/errors.py:PermanentError`／`PublishError` | **`PublishError` 直接繼承 `Exception`，不是 `PermanentError` 子類**；`_diff_block` 缺 `supersedes` 丟 `PermanentError`（00A §6.7），`render_version_page` 既有的步驟不同步仍丟 `PublishError` |
| `infra/training_kb_data_stack.py:PRIVATE_PREFIXES`／`TrainingKbDataStack` | bucket 現況 `BLOCK_ALL` ＋ `enforce_ssl=True`，資料角色**沒有 `site/`** |
| 既有測試（**不得修改**） | `tests/unit/test_site_renderer.py`（P24）、`test_retired_page.py`＋`test_retire_tutorial.py`（P26）、`test_publisher_single.py`／`test_publisher_batch.py`（P24/25） |

## 3. 要新增／修改的東西
| 檔 | 名稱 | 備註 |
|---|---|---|
| `src/training_kb/site.py` | `SITE_PREFIX`／`ASSET_KEYS`／`NO_PREVIOUS_TEXT`／`NOT_SENT_TEXT`／`escape_text`／`_page_href`／`_diff_block`／`_version_switch`；三個 render 換實作；版本頁加 `data-retired` | **同波只有本 Phase 動** |
| `src/training_kb/publishing.py` | `site_diff_key(version_id)` — 把 `_diff_copy_key` 改成公開名稱，`_public_pairs` 改呼叫它 | 00A §6.7 ＋ controller preflight scan 都把它放這支檔。P59 在 W4 才碰這支，本波無併行 |
| `demo/site_assets/widget.js`、`style.css` | 純資產（測試只 `read_text()`，**不需要** `demo` 可 import） | `demo/` 目前不存在 |
| `infra/training_kb_data_stack.py` | website hosting、BPA 放寬兩項、`enforce_ssl=False`、`site/*` 公開讀 policy、**資料角色 `site/` 寫入**（REP §8 第 6 項）、website URL 的 `CfnOutput` | 新增 `PUBLISH_PREFIX = "site/"`，**不要**塞進 `PRIVATE_PREFIXES` |
| `tests/unit/test_data_stack.py`（P09 既有） | 四條斷言要改，見 §6 表 | **只用 Edit**，只動那幾條 |
| 新測試 | `tests/unit/test_site_pages.py`、`test_site_assets.py`、`test_infra_site_hosting.py`、`tests/integration/test_site_widget_roundtrip.py` | 檔名照 00A §3.3 |

## 4. Task 順序與紅燈訊號
```bash
# Task 1 RED
uv run pytest tests/unit/test_site_pages.py -q          # cannot import name 'NO_PREVIOUS_TEXT'
# Task 1/2 GREEN 之後，一定要跑別人的既有測試
uv run pytest tests/unit/test_site_pages.py tests/unit/test_site_renderer.py \
   tests/unit/test_retired_page.py tests/unit/test_retire_tutorial.py \
   tests/unit/test_publisher_single.py tests/unit/test_publisher_batch.py -q
# Task 3 RED
uv run pytest tests/unit/test_site_assets.py tests/integration/test_site_widget_roundtrip.py -q
#   -> FileNotFoundError: demo/site_assets/widget.js
# Task 4 RED
uv run pytest tests/unit/test_infra_site_hosting.py -q  # 沒有 WebsiteConfiguration / BucketPolicy
uv run pytest tests/unit/test_data_stack.py -q          # 改 CDK 後這支會紅四條（預期）
# Task 5 真實 AWS
AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 command npx aws-cdk@2 diff TrainingKbData
AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 command npx aws-cdk@2 deploy TrainingKbData \
  --require-approval any-change --outputs-file "$SCRATCH/trainingkbdata-outputs.json"
# 全套
uv run pytest tests -q -W error && uv run ruff check src tests infra && uv run mypy
```

## 5. 00B primary Rule ＋ 測試
| Rule | 出處 | 對應測試 |
|---|---|---|
| `PUB` Rule 2 發布的教學透過 S3 靜態 docs 站提供 | 發布教學版本.feature | `tests/unit/test_infra_site_hosting.py` 的 bucket policy 測試 ＋ 整站掃描（公開 key 只在 `site/`） |
| `PUB` Rule 3 發布的教學提供 feedback widget | 發布教學版本.feature | `tests/unit/test_site_assets.py` 守門 ＋ `tests/integration/test_site_widget_roundtrip.py` |

相關（primary 在別份）：`COL` 2／3／9（P42）、`VER` 7（P22）、`PRP` 17（P26）。文件 §10 已對齊 00B，無缺漏。

## 6. 風險與陷阱
1. **循環 import（最大陷阱）。** `publishing.py:74` 已經 `from training_kb.site import SiteRenderer`；文件原本要 `site.py` 反向 import `site_key`／`tutorial_index_key`。**不行。** 頁面裡的 href 改成同目錄相對檔名（`v2.html`／`v3.diff.txt`／`index.html`），`site.py` 只用 `parse_version_id`。這與 `_successor_line` 既有的 `../<slug>/index.html`（D-78）同一套規則。
2. **兩支別人的測試已經鎖死相對 href：** `tests/unit/test_retired_page.py::test_retired_page_links_to_the_successor_tutorial_index` 與 `tests/unit/test_retire_tutorial.py:284` 都斷言 `<a href="../{successor}/index.html">`。R3.6 不得修改它們。
3. **`render_tutorial_index` 整頁不得含 `index.html`**（沒有 successor 時）：`test_tutorial_index_omits_the_link_when_the_successor_was_rejected` 斷言 `"index.html" not in page`。→ 索引頁**不能**加「回站台索引」連結。
4. **索引必須保留完整 `version_id` 文字**（`test_render_tutorial_index_lists_only_published_versions` 斷言 `V1 in page`）與 `data-site-version="v<n>"`（O3 觀察腳本靠它）。
5. **版本頁的退役區塊要留著。** REP §8 第 8 項提過「拿掉」的選項，但修正波實際選了「兩處都輸出」，P26 的四個版本頁測試正在守它。拿掉會紅燈且要改別人的測試。
6. **`test_outputs_expose_the_three_names` 會因為新 output 而紅** — 文件原本沒提到這條。
7. **`test_s3_statement_covers_every_private_prefix_and_never_site` 斷言 `"site/" not in rendered`** — 加資料角色 `site/` 寫入就會紅；要拆成「私有那條不含 site」＋「新增一條只給 `site/*`」。`test_list_bucket_is_limited_to_the_private_prefixes` 同理。
8. **`enforce_ssl=False` 之後 `test_data_role_has_no_wildcard_action_or_resource` 的註解過時**（那段 Deny 不存在了），斷言本身仍會過（公開讀是 `AWS::S3::BucketPolicy` 不是 `AWS::IAM::Policy`）。
9. **P42／P43 在本 Phase 之後**（W2／W3）：`import_feedback`／`import_view`／`ImportResult`／`approved_categories` 目前不存在 → roundtrip 的匯入斷言本波做不了。
10. **O3 FAIL**：頁面打得開 ≠ O3 PASS。**O5 BLOCKED**：真實演練不要靠 pipeline 產教學。
11. `Repository.put_object` 的 `if_none_match` 沒有預設值；`UNPUBLISHED_MARKER` 已經是 runtime 守門，整站掃描是第二道。

## 7. 需要裁決的點 → 建議裁決
1. **站內 href 用絕對還是相對？** → **相對（同目錄）**：`v2.html`、`v3.diff.txt`、`index.html`，後繼維持 `../<slug>/index.html`。理由：避開循環 import；D-78 已有先例；P26 的兩支測試已經鎖死；href 不是 key，不違反 00A §3.4。文件的絕對 href 斷言已全部改掉。
2. **`site_diff_key` 放哪？** → **`publishing.py`**（00A §6.7 的「三個公開 key helper 都在 `training_kb.publishing`」那一段 ＋ controller preflight scan）。把既有私有 `_diff_copy_key` 改成公開名稱，一份字串兩個用途。`escape_text` 與四個文字常數留 `site.py`。
3. **版本頁的退役區塊拿不拿掉？** → **留著**（見 §6 第 5 點）。
4. **`successor == tutorial.slug` 時要不要在 renderer 擋一次？** → **不要**。責任在 P26 的 `resolve_successor`（`site.py` 現有註解明寫理由）；測試改成斷言「renderer 原樣輸出」。要加的話先跑 P26 的兩支測試確認全綠。
5. **資料角色的 `site/` 寫入誰做？** → **本 Phase**（`training_kb_data_stack.py` 的修改者只有 P57，00A §3.2）。P41 負責的是 `training_kb_stack.py` 裡 Lambda 執行角色。作法：新增 `PUBLISH_PREFIX = "site/"` ＋ 獨立一條 `PolicyStatement`（`GetObject`／`PutObject` on `site/*`），`ListBucket` 的 `s3:prefix` 條件擴成 `PRIVATE_PREFIXES + (PUBLISH_PREFIX,)`；**不要**把 `site/` 塞進 `PRIVATE_PREFIXES`。
6. **roundtrip 本波寫什麼？** → 只斷言下載封套形狀（`{kind, source, generated_at, note, items}`、`items[0]` 具 `id`／`tutorial_version`／`rating`／`user`、`type(rating) is int`、ID 形狀 `f_site-<slug>-<user>-<epoch>`，00A §6.7）＋ 用**已存在**的 `models.Feedback` 驗 strict `rating`；真正的 `import_feedback` roundtrip 由 P42（W2）補進同一支檔。
7. **`categories` 從哪來？** → 本波測試直接傳 `("找不到按鈕", "缺少資訊")` tuple；`site.py` 一個字都不寫類別清單（P43 落地後由呼叫端注入 `approved_categories(repository)`）。

## 8. 對 AWS 的實際操作（R1：本 Phase 在名單內）
- **Region `us-east-1`**（`aws configure` 預設是 ap-northeast-1，CLI 一律帶 `--region us-east-1`）。Stack `TrainingKbData` 已部署，本次是**更新**。
- CDK 一律 `command npx aws-cdk@2 <子命令>`（本機 `node` 被擋），帶 `AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1`；`--outputs-file` 指到 scratchpad（專案外）。**不提交 `cdk.out/` 與 outputs 檔。**
- Bucket：`training-kb-content-example`。Website endpoint：`http://<bucket>.s3-website-us-east-1.amazonaws.com`。
- 必留證據（貼報告 §4，**不貼 bucket 內容**）：
  1. `cdk diff` 輸出（BPA 兩項 true→false ＋ 新增 bucket policy ＋ 新增 output）。
  2. `curl -si .../site/index.html` → **HTTP 200** ＋ 回應標頭。
  3. `curl -si .../tutorials/prepare-meeting/v1.md` → **403 或 404**（私有前綴沒有公開 Allow）。
  4. `aws s3api get-bucket-policy --bucket <bucket> --region us-east-1` → `Resource` 結尾是 `/site/*`，不是 `/*`。
- O5 BLOCKED → 不要靠 pipeline 產教學；用 `Publisher` 發一篇測試資料的版本，或直接 `aws s3 cp` 渲染好的頁面。報告要寫清楚用哪一種。
- 報告 §7 只能寫「website endpoint 可讀、公開範圍僅 `site/`、只有 HTTP」，**不得**寫 O3 PASS。
