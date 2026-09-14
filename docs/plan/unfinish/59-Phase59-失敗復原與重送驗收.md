# Phase 59：失敗復原與重送驗收實作計畫

> **給實作者：** 依 checkbox 逐步執行；每個 Task 先建立失敗測試，再寫最小實作。執行時使用 `superpowers:executing-plans` 或同等逐項流程。

**目標：** 用可控的 `TKB_FAULT` 開關在儲存、發布與接入的五個切點注入失敗，證明讀者看到的永遠是整批舊狀態，而且同一個 operation 重送會沿用原版號與原模型輸出把東西補齊。

**架構：** `training_kb/faults.py` 提供五個固定切點與只在非正式環境生效的開關；`content.py`、`publishing.py`、`ingress.py` 各在真實路徑上呼叫 `maybe_fail`。整合測試在每個切點注入後核對 DynamoDB 與 `site/` 的對外可見狀態，再清掉開關以同一個 `operation_id` 重送。`infra/scripts/check_asl.py` 包裝 Phase 29 的 `assert_safe_asl`，靜態檢查三份 ASL 的兩條 Retry 與 Catch。真實 AWS 驗收另標 `aws` marker，證據寫成固定格式。

**技術：** Python 3.12、pytest（`aws` marker）、moto、boto3、AWS Step Functions Standard。

## 全域限制

- 唯一主來源是 [Training KB 設計 §8.2、§8.3、§14.1、§14.2、§15、§16（S3／S8）、§18 O2／O3](../../design/training-kb.md)。
- 前置為 [Phase 58：Demo 控制台與規則開關預覽](./58-Phase58-Demo控制台與規則開關預覽.md)；另需 [Phase 01](./01-Phase01-專案骨架與離線品質門檻.md) 在 `pyproject.toml` 註冊的 `aws` marker、[Phase 11](./11-Phase11-O2接受順序與重啟整合驗證.md) 的 lease 與 `accept_seq`、[Phase 12](./12-Phase12-O3發布切換整合驗證.md) 的 O3 切點命名、[Phase 20](./20-Phase20-版本分配與重試重用.md) 的版號重用、[Phase 23](./23-Phase23-未發布版本與關係完整寫入.md) 的建版、[Phase 24](./24-Phase24-單篇教學發布提交.md)／[Phase 25](./25-Phase25-多篇教學整批發布.md) 的 `Publisher` 與 `pending-promote.json`、[Phase 29](./29-Phase29-共用Pipeline執行器與ASL失敗語意.md) 依裁決 D-53 固定的兩條 retrier、[Phase 32](./32-Phase32-事件接受去重與流程啟動.md) 的去重與啟動、[Phase 35](./35-Phase35-PROC成功失敗與退役生命週期.md) 的 PROC 樣本。前置未通過時停止。
- 下一階段是 [Phase 60：安全檢查與端到端完成證據](./60-Phase60-安全檢查與端到端完成證據.md)。
- 本階段不做：不為了取得綠燈修改業務契約；不新增 CloudFront、公開讀取 API 或待審佇列；不放寬 F49 的「整次失敗不發布」；不把注入開關帶進正式環境；不改 Phase 12 與本 Phase 任何一套切點名稱。
- 與本 Phase 有關的 O1–O7 gate 狀態：這是 O2 與 O3 的追驗階段。切點 `publish_after_transact_before_site` 正是設計 §18 O3 明說的缺口，**此階段完成前不可宣稱 publish 故障驗收已通過**。只要出現對外可見的 partial publish、新版號、新模型輸出或重複樣本，就保留 FAIL 並停止依賴路徑。
- 本 Phase 沒有 primary Rule：[00B 需求覆蓋對照](./00B-需求覆蓋對照.md) 把 P25、P41、P59、P60 列為驗收型，第 10 節的 Rule 一律是「相關」，直接斷言在各自的 primary Phase。
- 以下程式檔均是實作時預計建立或修改；本計畫本身不代表它們已存在。

---

## 1. 你在整體流程的位置

```text
一次 Release 事件從接入到公開的真實路徑與五個注入切點（五個都在同一條線上）

ingress.accept_release（Phase 32）
  保存 RELEASE -> [5 start_execution] -> starter.start("release-update", ...)
              |
              v
content.create_version（Phase 20–23）
  allocate_version -> validate_content -> put_object(v2.md) -> [1 s3_after_md]
     -> put_object(v2.diff) -> put_meta(VERSION) -> [2 ddb_after_version]
     -> put STEP/REFERENCES -> put SUPERSEDES/APPLIED_TO -> verify_version_complete
              |
              v
publishing.Publisher.commit（Phase 24／25）
  prepare -> inspect -> [3 publish_before_transact]
     -> transact(published_at + current_version)
     -> put_object(operations/<op>/pending-promote.json)（多篇整批才寫，Phase 25）
     -> [4 publish_after_transact_before_site] -> promote_site_objects
     -> site/tutorials/prepare-meeting/v2.html

[你在這裡] Phase 59：逐一注入 -> 核對對外可見狀態 -> 清掉開關 -> 同 operation 重送
```

## 2. 完成後看得到什麼

以 Release `r_42` 讓 `prepare-meeting` 從 v1 更新到 v2 為例（`operation_id` = `op-release-r_42`）；每個切點注入後外部可見狀態必須是下表，任何一格對不上就是 FAIL。

```text
切點                                 current_   v2 的         私有產物       site/ 有
                                     version    published_at  (md/diff)      v2 頁？
-----------------------------------  ---------  ------------  -------------  --------
1 s3_after_md                        v1 不變    VERSION 未建   md 有 diff 無  沒有
2 ddb_after_version                  v1 不變    None           齊全           沒有
3 publish_before_transact            v1 不變    None           齊全           沒有
4 publish_after_transact_before_site v2 已切換  有值           齊全           沒有 <- O3 缺口
5 start_execution                    v1 不變    不適用         不適用         沒有
-----------------------------------  ---------  ------------  -------------  --------
共同不變量：任一切點後打開公開站讀到的都仍是 v1 全文；
  site/tutorials/prepare-meeting/v2.html 不存在，index.html 也沒有指向 v2 的連結。
```

清掉開關後以同一個 `operation_id` 重送，五個切點都收斂到同一個結果：版號仍是 `prepare-meeting@v2`、模型輸出沿用既有 `model_output_refs`、`site/tutorials/prepare-meeting/v2.html` 出現、回饋樣本與 PROC 成功樣本各自沒有增加。切點 4 的重送只讀 `operations/op-release-r_42/pending-promote.json` 的 `site_keys` 補寫公開物件，不再跑一次條件交易。

## 3. 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| 切點 | 程式裡一個明確位置，注入開關可以讓它在那裡丟例外。 |
| `InjectedFault` | 人工注入的暫時錯誤，會先被 ASL 的 Retry 攔到，重試耗盡才進 Catch。 |
| lease | 同篇教學同時只有一個寫入者的短期租約；租約不等於接受順序，TTL 也不保證準時解鎖。 |
| closed execution | 同名 Step Functions 執行已經結束；再啟動會得到 `ExecutionAlreadyExists`。 |
| partial publish | 多篇一起發布時 A 已公開、B 還沒，對外看得到不一致；F49 禁止。 |
| 補償重送 | 交易已提交但公開物件未寫時，重送只補寫它們，不再跑一次條件交易。 |
| `pending-promote.json` | Phase 25 在交易成功後寫進私有操作紀錄的待補公開 key 清單，重送照它補齊。 |
| `aws` marker | pytest 標籤；標它的測試需要真實 AWS 帳號，由 Phase 01 在 `pyproject.toml` 註冊。 |

## 4. 預計檔案

| 動作 | 路徑 | 責任 |
|---|---|---|
| 建立 | `src/training_kb/faults.py` | 五個切點名稱、`InjectedFault`、`active_fault`、`maybe_fail`。 |
| 修改 | `src/training_kb/content.py` | 切點 1、2：寫完 `v<n>.md` 之後、寫完 VERSION metadata 之後各一次。 |
| 修改 | `src/training_kb/publishing.py` | 切點 3、4：交易之前、交易之後而未 promote 之前（多篇整批時就在寫完 `pending-promote.json` 之後）；另加 `resume_publish`。 |
| 修改 | `src/training_kb/ingress.py` | 切點 5：`starter.start(...)` 之前。 |
| 建立 | `infra/scripts/check_asl.py` | 包裝 `assert_safe_asl`，另外核對兩條 retrier 與 `PipelineFailed` 終點。 |
| 測試 | `tests/unit/test_faults.py`、`tests/unit/test_check_asl.py` | 開關與 ASL 靜態檢查。 |
| 測試 | `tests/integration/test_recovery.py` | 主戰場：切點矩陣、重送、串行與真 AWS 驗收。 |
| 產出 | `docs/plan/report/recovery-<YYYYMMDD-HHMM>.md` | 可追溯的驗收紀錄與 execution ARN。 |

## 5. 固定介面

### Consumes

```text
TransientError / PermanentError / CoordinationError                    # Phase 02
Repository.get_tutorial / get_version / get_proc                       # Phase 06
Repository.put_object / get_object / object_exists / scan_entity       # Phase 07、08
OperationCoordinator.accept / load / record_model_output / record_version /
    record_proc_sample / complete / fail ; operation_ref(op_id, name)  # Phase 10
acquire_lease(scope, owner, *, ttl_seconds, now) / release_lease /
    next_sequence(scope)                                               # Phase 11
O3CutPoint 的五個名稱（只做對照，不改名）                               # Phase 12
allocate_version(tutorial_id, operation_id, operations, *, repository,
    reason, rules_applied) -> VersionPlan                              # Phase 20
create_version(...) / verify_version_complete(version_id, repository)   # Phase 23
PublishRequest / PublishResult / Publisher.prepare / inspect / commit ;
    site_key(version_id)（相對 key）; PUBLIC_SITE_PREFIX = "site/"      # Phase 24、22
site_diff_key(version_id)（相對 key，在 site.py）                        # Phase 57
promote_site_objects(prepared, *, repository) -> tuple[str, ...]        # Phase 25
RETRY / CATCH / FAIL_STATE_NAME / assert_safe_asl(definition)           # Phase 29
PipelineStarter.start(pipeline, execution_name, input) -> str ;
    on_new_success(proc, operation_id, operations, now)                 # Phase 32、35
```

### Produces

```python
FAULT_POINTS = ("s3_after_md", "ddb_after_version", "publish_before_transact",
                "publish_after_transact_before_site", "start_execution")

class InjectedFault(TransientError):
    point: str

def active_fault(env: Mapping[str, str] | None = None) -> str | None: ...
def maybe_fail(point: str, env: Mapping[str, str] | None = None) -> None: ...
def resume_publish(operation_id: str, *, operations, repository,
                   publisher, now: datetime) -> PublishResult: ...

LAMBDA_SERVICE_ERRORS: list[str]

def iter_task_states(states: Mapping[str, Any],
                     prefix: str = "") -> Iterator[tuple[str, dict]]: ...
def check_asl_document(doc: Mapping[str, Any], *,
                       fail_state: str = "PipelineFailed") -> list[str]: ...
def main(argv: list[str] | None = None) -> int: ...
```

`InjectedFault` 繼承 `TransientError`，注入的失敗才會走完 Retry 再進 Catch，把設計 §14.2 的整條失敗路徑走一次（00A 第 4.1 節同一句）。

## 6. 設計細節

`active_fault` 有兩道保險：`TKB_ENV` 是 `prod` 時一律回 `None`，不論 `TKB_FAULT` 設什麼；切點名稱不在 `FAULT_POINTS` 時立刻丟 `ValueError`，讓打錯字變成明確錯誤而不是安靜地不生效。`maybe_fail` 進入前也先檢查名稱，所以就算沒啟用，寫錯的切點名也會在第一次執行被抓到。

[Phase 12](./12-Phase12-O3發布切換整合驗證.md) spike 的切點與本 Phase 的注入開關是**兩套名稱**，兩邊都不改名，對照關係固定如下：

| Phase 59 `FAULT_POINTS`（注入） | Phase 12 `O3CutPoint`（觀察） | 對應說明 |
|---|---|---|
| `publish_before_transact` | `a1_before_transact` | 交易前中斷，全舊，私有 staging 不對外。 |
| `publish_after_transact_before_site` | `a2_after_transact_before_site` | 交易後未寫公開物件，就是 O3 缺口。 |
| Task 2 的多篇整批案例 | `a3_after_first_site_before_second` | A 新 B 舊，違反 F49。 |
| 不注入（先 DB 後 site、不做事後刪除） | `b1_after_site_before_transact`、`c1_after_delete_site` | 先寫 site 再交易一律禁止、刪除不消除先前曝光，兩者只在 Phase 12 觀察。 |
| `s3_after_md`、`ddb_after_version`、`start_execution` | 無對應 | 建版與接入層切點，Phase 12 的 spike 不涵蓋。 |

同一個 operation 重送的流程固定如下：

```text
同一事件第二次送達 -> 同一 canonical_id -> 同一 operation_id
      |
      v
OperationCoordinator.accept(...) 條件寫入 OPS#<id>
      |
      +-- "accepted"  -> 新事件，照正常流程
      +-- "duplicate" -> 讀既有 OperationRecord
             +-- status == "done" -> 取既有結果；不新增版本／回饋樣本／PROC 樣本
             +-- 其他狀態         -> 沿用 version_id 與 model_output_refs，
                                     只補齊缺的產物再發布
```

切點 4 是本 Phase 唯一需要補償的路徑。DynamoDB 交易無法連同 S3 的公開切換一起提交（設計 §8.3、§18 O3），交易已提交後條件 `current_version == supersedes` 已不成立，重送不能再跑一次條件交易。**本計畫選擇：** 重送先讀該版本的 `published_at`，有值就只補寫公開物件，清單以 [Phase 25](./25-Phase25-多篇教學整批發布.md) 寫在 `operations/<operation_id>/pending-promote.json` 的 `site_keys` 為準；連這份清單都不存在時，用 operation 紀錄的 `version_id` 與 `site_key(...)` 重算同一份。這讓讀者只會短暫看到舊版，不會看到半完成的新版，也不會卡在永遠無法發布的狀態；但這是補償不是原子性，所以在 Phase 12 的 O3 協定被接受之前，本 Phase 只能記錄「補償有效」，不能寫成「發布故障驗收通過」。多篇整批的不變量更嚴格：任何切點失敗後 A 與 B 必須同時是舊狀態或同時是新狀態，出現 A 新 B 舊就停止，不得描述成「整次沒有發布」。

## 7. TDD Tasks

### Task 1：`faults.py` 的五個切點與環境限制

- [ ] **Step 1：建立失敗測試**

```python
# tests/unit/test_faults.py
import pytest
from training_kb.errors import TransientError
from training_kb.faults import InjectedFault, active_fault, maybe_fail

def test_unknown_fault_point_fails_immediately():
    with pytest.raises(ValueError, match="未知的失敗切點"):
        maybe_fail("s3_after_mdx", {"TKB_FAULT": "s3_after_md"})

def test_prod_never_injects():
    env = {"TKB_ENV": "prod", "TKB_FAULT": "s3_after_md"}
    assert active_fault(env) is None
    maybe_fail("s3_after_md", env)

def test_active_point_raises_transient_injected_fault():
    env = {"TKB_ENV": "dev", "TKB_FAULT": "publish_before_transact"}
    with pytest.raises(InjectedFault) as caught:
        maybe_fail("publish_before_transact", env)
    assert isinstance(caught.value, TransientError)
    assert caught.value.point == "publish_before_transact"
    maybe_fail("s3_after_md", env)
```

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_faults.py -q
```

預期：FAIL，訊號包含 `No module named 'training_kb.faults'`。

- [ ] **Step 3：建立最小實作**

```python
# src/training_kb/faults.py
import os
from collections.abc import Mapping

from training_kb.errors import TransientError

FAULT_POINTS = ("s3_after_md", "ddb_after_version", "publish_before_transact",
                "publish_after_transact_before_site", "start_execution")

class InjectedFault(TransientError):
    def __init__(self, point: str) -> None:
        super().__init__(f"注入失敗切點：{point}")
        self.point = point

def _check_point(point: str) -> None:
    if point not in FAULT_POINTS:
        raise ValueError(f"未知的失敗切點：{point}；可用：{'、'.join(FAULT_POINTS)}")

def active_fault(env: Mapping[str, str] | None = None) -> str | None:
    source = os.environ if env is None else env
    if source.get("TKB_ENV", "dev").strip().lower() == "prod":
        return None
    point = source.get("TKB_FAULT", "").strip()
    if point:
        _check_point(point)
    return point or None

def maybe_fail(point: str, env: Mapping[str, str] | None = None) -> None:
    _check_point(point)
    if active_fault(env) == point:
        raise InjectedFault(point)
```

- [ ] **Step 4：把五個切點接進程式並跑綠燈**

`content.py` 在寫完 `v<n>.md` 之後、寫完 VERSION metadata 之後各插一次；`publishing.py` 的 `Publisher.commit` 在交易之前、以及交易之後而尚未 `promote_site_objects` 之前各插一次（多篇整批時後者就落在寫完 `pending-promote.json` 之後；單篇發布本來就不寫這份清單，見 §6）；`ingress.py` 在保存 TICKET／RELEASE 之後、`starter.start` 之前插一次。再加一個測試讀這三個檔的原始碼，斷言 `FAULT_POINTS` 的每個名稱都恰好出現一次 `maybe_fail(...)` 呼叫。執行 `uv run pytest tests/unit/test_faults.py -q`，預期整個檔案全綠。

- [ ] **Step 5：提交** — `git add src/training_kb/faults.py src/training_kb/content.py src/training_kb/publishing.py src/training_kb/ingress.py tests/unit/test_faults.py` 後 `git commit -m "feat(faults): 以 TKB_FAULT 在五個切點注入失敗"`。

### Task 2：切點矩陣、整批不切換與同 operation 重送

- [ ] **Step 1：建立失敗測試**

```python
# tests/integration/test_recovery.py
import pytest
from training_kb.errors import TransientError
from training_kb.faults import FAULT_POINTS

@pytest.mark.parametrize("point", FAULT_POINTS)
def test_no_public_change_after_injected_fault(point, world, monkeypatch):
    monkeypatch.setenv("TKB_ENV", "dev")
    monkeypatch.setenv("TKB_FAULT", point)
    with pytest.raises(TransientError):
        world.deliver_release("r_42")
    assert world.public_html("prepare-meeting@v1") == world.v1_html
    assert not world.object_exists(world.public_key("prepare-meeting@v2"))
    assert "v2.html" not in world.tutorial_index("prepare-meeting")
    if point != "publish_after_transact_before_site":
        assert world.tutorial().current_version == "prepare-meeting@v1"

def test_batch_publish_is_all_or_nothing(world, monkeypatch):
    monkeypatch.setenv("TKB_ENV", "dev")
    monkeypatch.setenv("TKB_FAULT", "publish_before_transact")
    with pytest.raises(TransientError):
        world.publish_batch(["prepare-meeting@v2", "share-summary@v2"])
    for version_id in ("prepare-meeting@v2", "share-summary@v2"):
        assert world.tutorial(version_id.split("@")[0]).current_version.endswith("@v1")
        assert not world.object_exists(world.public_key(version_id))

def test_resend_reuses_version_and_model_output(world, monkeypatch):
    monkeypatch.setenv("TKB_ENV", "dev")
    monkeypatch.setenv("TKB_FAULT", "publish_after_transact_before_site")
    with pytest.raises(TransientError):
        world.deliver_release("r_42")
    first = world.operation("op-release-r_42")
    monkeypatch.delenv("TKB_FAULT")
    world.resume("op-release-r_42")
    again = world.operation("op-release-r_42")
    assert again.version_id == first.version_id == "prepare-meeting@v2"
    assert again.model_output_refs == first.model_output_refs
    assert world.model_calls_during_resend == 0
    assert world.object_exists("site/tutorials/prepare-meeting/v2.html")

def test_same_event_resend_adds_no_samples(world):
    world.deliver_release("r_42")
    before = world.counters()
    world.deliver_release("r_42")
    assert world.counters() == before
```

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/integration/test_recovery.py -q
```

預期：FAIL，訊號包含 `fixture 'world' not found`；補上 fixture 後會變成 `cannot import name 'resume_publish'`。

- [ ] **Step 3：建立最小實作**

```python
# tests/integration/test_recovery.py（接在測試上方）
from training_kb.publishing import site_key
from training_kb.site import site_diff_key          # Phase 57

PUBLIC, SLUG = "site/", "prepare-meeting"

class World:
    """把 Phase 20→25 的真實路徑包成測試門面，不繞過 Publisher 另接發布路徑。"""

    def public_key(self, version_id: str) -> str:
        return PUBLIC + site_key(version_id)

    def public_html(self, version_id: str) -> str:
        return (self.repository.get_object(self.public_key(version_id)) or b"").decode()

    def tutorial_index(self, slug: str) -> str:
        body = self.repository.get_object(f"{PUBLIC}tutorials/{slug}/index.html")
        return (body or b"").decode()

    def counters(self) -> tuple[int, int, int]:
        return (len(self.repository.scan_entity("VERSION")),
                len(self.repository.scan_entity("FEEDBACK")),
                self.repository.get_proc(self.signature).success_count)
```

```python
# src/training_kb/publishing.py（在 Phase 24 的模組追加）
import json
from training_kb.errors import CoordinationError
from training_kb.keys import operation_ref

def resume_publish(operation_id, *, operations, repository, publisher, now):
    """同 operation 重送：沿用原版號；交易已提交時只補公開物件。"""
    record = operations.load(operation_id)
    if record is None or record.version_id is None:
        raise CoordinationError(f"沒有可沿用的操作紀錄：{operation_id}")
    request = PublishRequest(version_ids=(record.version_id,), operation_id=operation_id)
    prepared = publisher.prepare(request, now=now)
    if repository.get_version(record.version_id).published_at is None:
        return publisher.commit(prepared, now=now)
    body = repository.get_object(operation_ref(operation_id, "pending-promote"))
    expected = (list(json.loads(body)["site_keys"]) if body
                else [PUBLIC_SITE_PREFIX + site_key(record.version_id),
                      PUBLIC_SITE_PREFIX + site_diff_key(record.version_id)])   # 版本頁 + 差異檔
    if list(promote_site_objects(prepared, repository=repository)) != expected:
        raise CoordinationError(f"補寫的公開 key 與待補清單不一致：{operation_id}")
    return PublishResult(published=(record.version_id,), failed=None, reasons=())
```

`World` 的 `__init__` 收下 `repository`、`operations`、`publisher`、PROC `signature`，並把已發布 v1 的公開頁 bytes 存進 `v1_html`、`model_calls_during_resend` 起始為 0；`object_exists`／`tutorial`／`operation` 直接轉呼 `Repository.object_exists`、`Repository.get_tutorial`、`OperationCoordinator.load`。`deliver_release(release_id)` 是唯一的端到端驅動：走 Phase 32 的接受與啟動、在本機用 `run_sequence` 跑 release-update、再走 Phase 20→23→24 建版與發布，所以五個切點都在它的路徑上（`start_execution` 在最前面，失敗時連版本都還沒建）。`publish_batch` 走 Phase 25 的 `prepare`／`inspect`／`commit`，`resume` 呼叫 `resume_publish`。`world` fixture 用 moto 建好 `training_kb` 表與 bucket 並載入已發布的 v1。重送一律先讀 `OperationCoordinator.load`：有 `version_id` 就重用，有 `model_output_refs` 就從私有 S3 讀回，不再呼叫 `Writer`。`counters()` 的 `success_count` 只有在 [Phase 35](./35-Phase35-PROC成功失敗與退役生命週期.md) 的 `on_new_success` 拿到 `record_proc_sample(...)` 回 `True` 這份永久證據時才會加，所以同事件重送三種樣本都不變。

- [ ] **Step 4：補切點 4、串行與 closed execution 案例並跑綠燈**

切點 4 允許 `current_version` 已切換，但仍必須滿足「`site/tutorials/prepare-meeting/v2.html` 不存在、教學索引沒有 v2 連結」，測試對它單獨斷言並在報告標成 O3 缺口，不得改成寬鬆通過。同篇的 Release 與 Feedback 交錯送達時以 `acquire_lease` 串行，兩者依 `next_sequence` 取得的接受順序各產生一版，版號不重疊也不跳過；測試明確寫出「lease 不等於接受順序、TTL 不保證準時解鎖」。`start_execution` 切點清掉後重送，若 Step Functions 回 `ExecutionAlreadyExists`，必須先用 `describe_execution` 讀回原執行狀態並核對 operation 紀錄：`status == "done"` 才沿用既有結果，否則依 [Phase 32](./32-Phase32-事件接受去重與流程啟動.md) 回 `CoordinationError`，不可直接當成功，也不可換名重跑。執行 `uv run pytest tests/integration/test_recovery.py -q`，預期整個檔案全綠。

- [ ] **Step 5：提交** — `git add src/training_kb/publishing.py tests/integration/test_recovery.py` 後 `git commit -m "test(recovery): 切點注入與同 operation 重送"`。

### Task 3：ASL 靜態檢查與真實 AWS 驗收證據

- [ ] **Step 1：建立失敗測試**

```python
# tests/unit/test_check_asl.py
from infra.scripts.check_asl import check_asl_document
from training_kb.pipelines.asl import CATCH, RETRY

ARN = "arn:aws:lambda:ap-northeast-1:123456789012:function:training-kb-pipeline-task"

def _document() -> dict:
    inner = {"Inner": {"Type": "Task", "Resource": ARN, "End": True}}
    return {"StartAt": "Work", "States": {
        "PipelineFailed": {"Type": "Fail", "Error": "PipelineFailed"},
        "Work": {"Type": "Task", "Resource": ARN, "End": True, "Retry": [dict(RETRY[0])]},
        "Fan": {"Type": "Map", "Next": "Work",
                "ItemProcessor": {"StartAt": "Inner", "States": inner}}}}

def test_missing_catch_and_second_retrier_are_reported():
    problems = check_asl_document(_document())
    assert any("Work" in item and "Catch" in item for item in problems)
    assert any(item.startswith("Task Fan.ItemProcessor.Inner") for item in problems)
    assert any("Lambda.ServiceException" in item for item in problems)
    assert any(item.startswith("assert_safe_asl") for item in problems)

def test_complete_document_has_no_problems():
    doc = _document()
    del doc["States"]["Fan"]
    doc["States"]["Work"]["Retry"] = [dict(item) for item in RETRY]
    doc["States"]["Work"]["Catch"] = [dict(item) for item in CATCH]
    assert check_asl_document(doc) == []
```

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_check_asl.py -q
```

預期：FAIL，訊號包含 `No module named 'infra.scripts.check_asl'`。

- [ ] **Step 3：建立最小實作**

```python
# infra/scripts/check_asl.py
import json
import sys
from pathlib import Path

from training_kb.errors import PermanentError
from training_kb.pipelines.asl import CATCH, FAIL_STATE_NAME, RETRY, assert_safe_asl

ASL_ROOT = Path("infra/stepfunctions")
LAMBDA_SERVICE_ERRORS = ["Lambda.ServiceException", "Lambda.AWSLambdaException",
                         "Lambda.SdkClientException", "Lambda.TooManyRequestsException"]

def iter_task_states(states, prefix=""):
    for name in sorted(states):
        state, where = states[name], f"{prefix}{name}"
        if state.get("Type") == "Task":
            yield where, state
        for key in ("ItemProcessor", "Iterator"):
            if isinstance(state.get(key), dict):
                yield from iter_task_states(state[key].get("States", {}), f"{where}.{key}.")
        for index, branch in enumerate(state.get("Branches") or []):
            yield from iter_task_states(branch.get("States", {}), f"{where}.Branches[{index}].")

def check_asl_document(doc, *, fail_state=FAIL_STATE_NAME):
    problems, states = [], doc.get("States") or {}
    for where, state in iter_task_states(states):
        retries, catches = state.get("Retry") or [], state.get("Catch") or []
        if retries[: len(RETRY)] != [dict(item) for item in RETRY]:
            problems.append(f"Task {where} 的前 {len(RETRY)} 條 Retry 與 Phase 29 的 RETRY 不同")
        if not any(item.get("ErrorEquals") == LAMBDA_SERVICE_ERRORS for item in retries):
            problems.append(f"Task {where} 缺少涵蓋 Lambda.ServiceException 的 retrier")
        if catches != [dict(item) for item in CATCH] or catches[0].get("Next") != fail_state:
            problems.append(f"Task {where} 的 Catch 沒有把 States.ALL 導向 {fail_state}")
    if states.get(fail_state, {}).get("Type") != "Fail":
        problems.append(f"缺少 Type=Fail 的 {fail_state} 終點")
    try:
        assert_safe_asl(doc)
    except PermanentError as error:
        problems.append(f"assert_safe_asl：{error}")
    return problems

def main(argv=None):
    paths = [Path(item) for item in argv] if argv else sorted(ASL_ROOT.glob("*/v*.json"))
    found = {path: check_asl_document(json.loads(path.read_text())) for path in paths}
    for path, problems in found.items():
        print(f"[{'通過' if not problems else '不通過'}] {path}")
        print(*(f"  - {item}" for item in problems), sep="\n")
    return 1 if any(found.values()) else 0

if __name__ == "__main__":
    sys.exit(main())
```

`check_asl_document` 自己走完所有 Task（含 `Map` 的 `ItemProcessor`／`Iterator` 與 `Parallel` 的 `Branches`）收齊全部問題，再**包裝** Phase 29 的 `assert_safe_asl`：後者在第一個問題就丟 `PermanentError`，所以只把它的訊息當最後一筆追加，`StartAt`、`Choice` 的 `Default`、同層 `Fail` 這些結構規則不必重寫一次。`LAMBDA_SERVICE_ERRORS` 逐字對應裁決 D-53 的第二條 retrier；Phase 29 的 `RETRY` 依 D-53 已含兩條時本檢查等於只比對它，常數存在是為了讓「第二條不見了」有明確訊息。

- [ ] **Step 4：對三份 ASL 執行並準備真 AWS 驗收**

從 repo 根目錄執行 `uv run python -m infra.scripts.check_asl`，它會掃 `infra/stepfunctions/<pipeline>/v<n>.json` 三份定義並全部印 `[通過]`；真 AWS 案例以 `TKB_RUN_AWS_INTEGRATION=1 uv run pytest tests/integration/test_recovery.py -m aws -q` 單獨執行。真 AWS 案例標 `@pytest.mark.aws`（marker 由 Phase 01 在 `pyproject.toml` 註冊），Phase 01 的 conftest 在 `TKB_RUN_AWS_INTEGRATION` 未設時自動 skip，一般開發不必加 `-m` 參數。每跑一次就把證據寫進 `docs/plan/report/recovery-<YYYYMMDD-HHMM>.md`，固定欄位為：切點名稱、注入方式、`execution_arn`、`describe_execution` 的 `status`／`error`／`cause` 與讀取時間、注入後的 `current_version` 與 `site/` 清單、重送後的 `version_id` 與 `site/` 清單、模型呼叫數差值、結論（PASS／FAIL／O3 缺口）。沒有這份紀錄就不算完成。

- [ ] **Step 5：提交** — `git add infra/scripts/check_asl.py tests/unit/test_check_asl.py` 後 `git commit -m "feat(infra): 檢查 ASL 的兩條 Retry 與 Catch"`。

## 8. 驗收矩陣

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy | 無注入的建版與發布 | v2 發布成功，`site/tutorials/prepare-meeting/v2.html` 存在，`current_version` 指向 v2。 |
| Failure | 五個切點逐一注入 | 公開站仍讀到 v1；沒有 v2 公開物件；切點 1、2、3、5 的 `current_version` 不變。 |
| Failure | 多篇整批在任一切點失敗 | 兩篇同時維持舊狀態；不得出現 A 新 B 舊。 |
| Boundary | 切點 4 注入 | `current_version` 已切換但公開物件未寫；標為 O3 缺口，重送只依 `pending-promote.json` 補寫。 |
| Boundary | 同 operation 重送 | 同一版號、同一模型輸出 ref、重送期間模型呼叫數為 0。 |
| Boundary | 同一事件重送（同 `operation_id`） | 版本數、回饋樣本數、PROC `success_count` 三者都不變。 |
| Boundary | 同名 execution 已結束 | 先 `describe_execution` 並核對 operation 紀錄，`status == "done"` 才沿用，否則 `CoordinationError`。 |

人工驗收：在 Step Functions console 打開一個 FAILED 與一個重送後 SUCCEEDED 的執行，對照 `recovery-<YYYYMMDD-HHMM>.md` 的 ARN；同時用瀏覽器打開公開站（HTTP website endpoint）確認注入期間讀到的是舊版。不能只看測試顯示 PASS。

## 9. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| 重送後出現 v3 | 重送重新配置版號 | 停止；改為從 operation 紀錄讀回 `version_id`。 |
| 重送時模型被再呼叫一次 | 沒有重用 `model_output_refs` | 停止；儲存階段重試必須重用既有輸出。 |
| A 已公開、B 失敗卻宣稱整次未發布 | 在 Map 內逐篇 publish | 停止；改成全部 prepare／inspect 後整批 commit，保留 FAIL。 |
| 切點 4 被寫成「已通過」 | 把補償當成原子性 | 改寫成 O3 缺口與補償結果；Phase 12 未 PASS 前不得宣稱通過。 |
| 正式環境仍會注入失敗 | 沒設 `TKB_ENV=prod` 或忘了清 `TKB_FAULT` | 停止部署；部署清單必須包含這兩項檢查。 |
| `ExecutionAlreadyExists` 直接當成功 | 誤把冪等當結果 | 先 `describe_execution` 並核對 operation 紀錄再判定。 |
| `check_asl_document` 對正確的 ASL 也報錯 | Phase 29 的 `RETRY` 還只有一條 retrier | 回 Phase 29 補上裁決 D-53 的第二條，不在本 Phase 放寬檢查。 |

## 10. 來源與 Rule 對照

本 Phase 是驗收型，沒有 primary Rule；下列都是「相關」，直接斷言由括號內的 primary Phase 負責，本 Phase 只在失敗復原情境下再驗一次（[00B](./00B-需求覆蓋對照.md) 第 2、3.2 節）。

- [接入來源事件.feature](../../spec/features/接入來源事件.feature) Rule 30：「同一正規化事件重送時只處理一次」→ 相關（primary Phase 10）；Task 2 斷言重送後版本數、回饋樣本數與 PROC `success_count` 都不變。
- [建立教學版本.feature](../../spec/features/建立教學版本.feature) Rule 2：「任一 pipeline 修改既有教學時使用該篇的下一個版本號」→ 相關（primary Phase 20）；Task 2 斷言同 operation 重送沿用同一 `version_id`，並以 lease 串行同篇的 Release 與 Feedback。
- [執行教學流程.feature](../../spec/features/執行教學流程.feature)：Rule 2「教學 pipeline 依 Step Functions 預定義節點執行」、Rule 6「每個 Step Functions Task 設定 Retry」、Rule 7「每個 Step Functions Task 設定 Catch」、Rule 10「Step Functions 的 ASL 版本快照存於 `stepfunctions/<pipeline>/v<n>.json`」→ 四條都是相關（primary Phase 29）；Task 3 的 `check_asl_document` 只檢查既有三份 `infra/stepfunctions/<pipeline>/v<n>.json`，不新增節點也不改快照契約。
- [發布教學版本.feature](../../spec/features/發布教學版本.feature) Rule 4：「Tutorial 的 current_version 指向目前教學版本」、Rule 5：「已上架的版本具有 published_at」→ 相關（primary Phase 24）；Task 2 的切點矩陣直接觀察這兩個欄位。
- 設計 §8.3（發布與併發界線、多篇整批不得部分發布）、§14.1（S3／DynamoDB 部分寫入時保留不可公開的未完成版本）、§14.2（重試不是重新抽一次文字、`ExecutionAlreadyExists` 不等於成功）、§15（版本與發布、接入去重、呼叫與失敗三列驗收）、§16（S3「中途失敗仍讀舊版」、S8「一次儲存失敗復原」）、§18 O2／O3。
- [Step Functions StartExecution](https://docs.aws.amazon.com/step-functions/latest/apireference/API_StartExecution.html)：同名同 input 的冪等只涵蓋仍在執行的案例。
- [describe_execution（boto3）](https://docs.aws.amazon.com/boto3/latest/reference/services/stepfunctions/client/describe_execution.html)：回傳 `status`、`error`、`cause`，且是最終一致讀取，證據要記下讀取時間。
- [Step Functions 錯誤處理](https://docs.aws.amazon.com/step-functions/latest/dg/concepts-error-handling.html)：`States.ALL` 並非涵蓋所有終止錯誤。

## 11. 完成清單

- [ ] `FAULT_POINTS` 恰為五個名稱，打錯字立刻報錯，`TKB_ENV=prod` 一律不注入。
- [ ] 五個切點分別落在 `content.py`、`publishing.py`、`ingress.py` 的真實路徑上，且各被呼叫一次。
- [ ] 每個切點注入後公開站仍讀到舊版，`site/tutorials/<slug>/` 沒有新版本頁、索引也沒有新連結。
- [ ] 多篇整批失敗時兩篇同時維持舊狀態，沒有 partial publish。
- [ ] 同 operation 重送沿用原版號與原模型輸出，重送期間模型呼叫數為 0；切點 4 依 `pending-promote.json` 補寫，單篇發布沒有這份清單時改用 operation 紀錄的 `version_id` 與 `site_key(...)` 重算同一份。
- [ ] 同事件重送不新增版本、回饋樣本或 PROC 成功樣本；closed execution 先核對 `status == "done"` 再判定。
- [ ] `check_asl.py` 包裝 `assert_safe_asl`，對三份 ASL 全部 `[通過]`，刻意刪掉一個 Catch 或第二條 retrier 時會失敗。
- [ ] Phase 12 與本 Phase 的兩套切點名稱有對照表，兩邊都沒有改名。
- [ ] `recovery-<YYYYMMDD-HHMM>.md` 有 execution ARN 與前後狀態；未完成前不宣稱 publish 故障驗收已通過。
