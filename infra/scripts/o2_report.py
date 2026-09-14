"""O2 gate 的一次性驗證：把「操作紀錄與接受順序」的五個情境各對真實 DynamoDB 跑一次。

驗的是**協調協定**，不是任何 pipeline：`OperationCoordinator` 的永久去重（`accept`）、
接受順序（`accept_seq`）與租約（`acquire_lease`／`release_lease`）在重啟、重送、
lease 過期、交錯事件、closed execution 五種情況下，是不是都只長出一條版本鏈
（設計 §8.3、§14.1、§14.2、§18 O2）。

兩句必須一直成立，後面的 Phase 很容易誤用：

- **鎖不等於接受順序。** 誰先搶到 lease 只代表誰先送達 DynamoDB，不代表事件較早。
  順序一律讀 `accept_seq`：worker 拿到某篇教學的 lease 之後，在該篇待處理的操作裡挑
  `accept_seq` 最小的做，做完才換下一個。`interleaved` 案例刻意讓搶鎖順序與接受順序相反。
- **TTL 不是準時解鎖。** DynamoDB 的 TTL 是「typically within a few days after their
  expiration」，過期項目在刪除前仍讀得到。到期判斷一律自己比 `expires_at`，再用
  `expected_revision` 把租約搶下來；`ttl` 屬性只做長期清理。`lease_expiry` 案例把
  到期後仍讀得回來的那筆 item 直接記進觀察值。

兩個替身（本 Phase 自備，避免用到更後面 Phase 才有的東西）：

- **版號**：Phase 20 的 `allocate_version` 此時還不存在，`restart` 與 `interleaved`
  用「讀 `Tutorial.current_version` → 版號加一 → `record_version`」的替身，字串直接組成
  `<slug>@v<n>`。本 Phase 只證明「同一 operation 重送拿到同一個 `version_id`、兩個
  operation 不分叉」。
- **closed execution**：不在此實作 `PipelineStarter`（Phase 32 才接真正的 boto3 adapter），
  用最小 stub `ExecutionAlreadyExists` 證明協調紀錄足以判斷。

檔案分成六段：
1. 契約常數與五個案例
2. 兩個 dataclass
3. 真實後端器材（boto3、重建 `Repository`、版號替身、子程序）
4. 五個案例
5. 判定與報告
6. 隔離測試表、gate 證據與命令列
"""

import argparse
import json
import os
import signal
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from training_kb.clock import now_utc, to_iso
from training_kb.errors import CoordinationError
from training_kb.keys import tutorial_pk
from training_kb.models import Tutorial, TutorialStatus
from training_kb.operations import AcceptOperation, OperationCoordinator, OperationRecord
from training_kb.repository import Repository

# --- 1. 契約常數與五個案例 ---------------------------------------------------

REGION_ENV = "TKB_AWS_REGION"
TABLE_ENV = "TKB_TABLE_NAME"
BUCKET_ENV = "TKB_CONTENT_BUCKET"
RUN_ID_ENV = "TKB_O2_RUN_ID"
DEFAULT_REGION = "us-east-1"

# 設計 §14.3：連線 2 秒、讀取 30 秒；SDK 不重試，觀察值才不會被暗中補救。
SDK_CONFIG = Config(connect_timeout=2, read_timeout=30, retries={"total_max_attempts": 1})

# 隔離的測試單表只為這一次驗證存在，跑完一定刪掉；正式 `training_kb` 表完全不碰。
TEST_TABLE_PREFIX = "training_kb_o2_"
TTL_ATTRIBUTE = "ttl"

# gate 證據固定在私有前綴 `operations/o2/<run_id>.json`（00A §3.4）。
EVIDENCE_PREFIX = "operations/o2/"
REPORT_DIR = Path(__file__).resolve().parents[2] / "docs" / "plan" / "report"

LEASE_TTL_SECONDS = 30
CHILD_FLAG = "--child-restart"


@dataclass(frozen=True)
class O2Case:
    name: str
    fault_point: str
    expectation: str


@dataclass(frozen=True)
class O2CaseResult:
    case: O2Case
    observed: str
    verdict: Literal["PASS", "FAIL"]
    evidence_ref: str


O2_CASES: tuple[O2Case, ...] = (
    O2Case("restart", "after_record_version", "同 operation_id 與同 version_id"),
    O2Case("resend", "after_accept", "status=duplicate，OPS 只有一筆"),
    O2Case("lease_expiry", "owner_vanishes", "到期後可接手，順序仍照 accept_seq"),
    O2Case("interleaved", "release_and_feedback_same_slug", "兩版串行且無分叉"),
    O2Case("closed_execution", "already_exists_closed", "讀 ledger 原結果；無結果則明確失敗"),
)


class ExecutionAlreadyExists(Exception):
    """`PipelineStarter` 的最小 stub：同名執行已結束時 Step Functions 回的錯誤。

    真正的 boto3 adapter 是 Phase 32 的事。這裡只要「有人丟出這個例外」，就足以驗證
    「協調紀錄是否足以判斷該回原結果還是明確失敗」（設計 §14.2）。
    """


# --- 2. 真實後端器材 ---------------------------------------------------------

_RESOURCES: dict[str, Any] = {}


def case_region() -> str:
    return os.environ.get(REGION_ENV) or DEFAULT_REGION


def current_run_id() -> str:
    """證據 key 用的 run id。`run_o2_case` 的簽名固定（00A §6.4）不收 run id，
    所以由 `main` 先寫進環境變數；直接呼叫案例時退回一個穩定的 `adhoc` 值。"""
    return os.environ.get(RUN_ID_ENV) or "adhoc"


def evidence_key(run_id: str) -> str:
    return f"{EVIDENCE_PREFIX}{run_id}.json"


def dynamodb_resource(region: str) -> Any:
    key = f"dynamodb@{region}"
    if key not in _RESOURCES:
        _RESOURCES[key] = boto3.resource("dynamodb", region_name=region, config=SDK_CONFIG)
    return _RESOURCES[key]


def open_repository(table: str, region: str) -> Repository:
    """**全新**的 `Repository`：等同程序重啟後用同一張表重建，沒有任何殘留狀態。

    刻意每次都重新取 `Table` 物件，`restart` 與 `interleaved` 的「換一個執行者」才是真的
    換過，而不是共用同一份記憶體。
    """
    return Repository(dynamodb_resource(region).Table(table))


def open_coordinator(table: str, region: str) -> OperationCoordinator:
    return OperationCoordinator(open_repository(table, region))


def token() -> str:
    """每次執行都用新的 8 碼隨機字串，同一張表重跑多次不會互相干擾。"""
    return uuid4().hex[:8]


def seed_tutorial(repository: Repository, slug: str, *, version: int) -> None:
    """建立案例用的教學，`current_version` 直接設在 `<slug>@v<version>`。"""
    repository.put_meta(
        Tutorial(
            slug=slug,
            current_version=make_version(slug, version),
            topic=f"O2 case {slug}",
            feature_ids=[],
            status=TutorialStatus.ACTIVE,
        )
    )


def make_version(slug: str, number: int) -> str:
    """版號替身的字串形狀（00A §3.3 的 `<slug>@v<n>`）。Phase 20 才有真正的 `allocate_version`。"""
    return f"{slug}@v{number}"


def version_number(version_id: str | None) -> int:
    """`prepare-meeting@v3` -> 3；還沒有版本時回 0。"""
    if not version_id or "@v" not in version_id:
        return 0
    return int(version_id.rsplit("@v", 1)[1])


def allocate_stub(
    repository: Repository, operations: OperationCoordinator, *, slug: str, operation_id: str
) -> str:
    """版號替身：讀 `Tutorial.current_version` -> 版號加一 -> `record_version`。

    同一個 operation 重送時**不重新取號**：ledger 已經有 `version_id` 就直接沿用，
    這正是 `restart` 案例要證明的「重啟後不會出現第三個版號」。
    """
    record = operations.load(operation_id)
    if record is not None and record.version_id:
        return record.version_id
    tutorial = repository.get_tutorial(slug)
    if tutorial is None:
        raise CoordinationError(f"tutorial is missing: {slug}")
    version_id = make_version(slug, version_number(tutorial.current_version) + 1)
    operations.record_version(operation_id, version_id)
    return version_id


def publish_stub(repository: Repository, slug: str, version_id: str) -> None:
    """把 `Tutorial.current_version` 切到新版；用 `expected_revision` 條件寫入。

    **lease 不是正確性保證**，所以這一步仍然帶條件：時鐘偏移讓兩個 owner 同時以為自己
    持有租約時，還是只有一個切得動指標，另一個拿到 `CoordinationError`。
    """
    pk = tutorial_pk(slug)
    repository.update_meta(
        pk, {"current_version": version_id}, expected_revision=repository.revision_of(pk)
    )


def count_ops(repository: Repository, project_id: str) -> int:
    """這個案例自己的 `OPS#` item 數；同一張表上的其他案例不算進來。"""
    return len([row for row in repository.scan_entity("OPS")
                if str(row.get("project_id")) == project_id])


def sequence_counter(repository: Repository, project_id: str) -> int:
    item = repository.get_meta_item(f"SEQ#PROJECT#{project_id}")
    return 0 if item is None else int(str(item["counter"]))


def lease_item(repository: Repository, slug: str) -> Mapping[str, Any] | None:
    return repository.get_meta_item(f"LEASE#TUTORIAL#{slug}")


def pending_in_accept_order(
    repository: Repository, project_id: str
) -> list[tuple[int, str]]:
    """該專案還沒拿到版號的操作，依 `accept_seq` 由小到大。

    **這就是「順序讀 accept_seq，不讀誰先搶到鎖」的實作點。**
    """
    rows = [row for row in repository.scan_entity("OPS")
            if str(row.get("project_id")) == project_id and not row.get("version_id")]
    return sorted((int(str(row["accept_seq"])), str(row["operation_id"])) for row in rows)


def _summary(fields: Mapping[str, object]) -> str:
    """報告是 Markdown 表格，觀察值不能帶 `|`；固定組成 `key=value` 以空格分隔。"""
    return " ".join(f"{key}={str(value).replace('|', '/')}" for key, value in fields.items())


# --- 3. 案例：restart（真的 kill -9 一個子程序）------------------------------


def restart_child(table: str, region: str, slug: str, operation_id: str, project_id: str) -> None:
    """子程序：接受 -> 取版號 -> `record_version` -> **立刻 `SIGKILL` 自己**。

    `Tutorial.current_version` 刻意還沒切換，這就是崩潰視窗：`OPS#` 已有版號、指標還是舊的。
    """
    repository = open_repository(table, region)
    operations = OperationCoordinator(repository)
    operations.accept(
        AcceptOperation(operation_id, "release", operation_id, project_id, now_utc())
    )
    version_id = allocate_stub(
        repository, operations, slug=slug, operation_id=operation_id
    )
    print(version_id, flush=True)
    os.kill(os.getpid(), signal.SIGKILL)


def run_restart(case: O2Case, *, table: str, region: str) -> O2CaseResult:
    mark = token()
    slug, project_id = f"o2-restart-{mark}", f"o2-restart-{mark}"
    operation_id = f"op-release-r42-{mark}"
    repository = open_repository(table, region)
    seed_tutorial(repository, slug, version=1)

    child = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), CHILD_FLAG,
         table, region, slug, operation_id, project_id],
        capture_output=True, text=True, check=False,
    )
    child_version = child.stdout.strip().splitlines()[-1] if child.stdout.strip() else ""

    # 重啟：整個 Python 物件都丟掉，用同一張表重建 Repository 與 OperationCoordinator。
    restarted = open_repository(table, region)
    operations = OperationCoordinator(restarted)
    again = operations.accept(
        AcceptOperation(operation_id, "release", operation_id, project_id, now_utc())
    )
    version_id = allocate_stub(restarted, operations, slug=slug, operation_id=operation_id)
    publish_stub(restarted, slug, version_id)
    operations.complete(operation_id, now=now_utc())
    tutorial = restarted.get_tutorial(slug)

    observed = _summary({
        "killed": child.returncode,
        "child_version": child_version or "(none)",
        "resend_status": again.status,
        "version_id": version_id,
        "current_version": tutorial.current_version if tutorial else "(none)",
        "ops": count_ops(restarted, project_id),
        "accept_seq": again.record.accept_seq,
    })
    passed = (
        child.returncode == -signal.SIGKILL
        and child_version == version_id
        and again.status == "duplicate"
        and version_id == make_version(slug, 2)
        and tutorial is not None
        and tutorial.current_version == version_id
        and count_ops(restarted, project_id) == 1
    )
    return O2CaseResult(case, observed, "PASS" if passed else "FAIL",
                        evidence_key(current_run_id()))


# --- 4. 案例：resend、lease_expiry、interleaved、closed_execution -------------


def run_resend(case: O2Case, *, table: str, region: str) -> O2CaseResult:
    """同一筆事件送四次。只有第一次是 `accepted`，其餘一律 `duplicate`。

    第一次刻意在 `accept` 之後就停手（不建教學），第二次因此走 **D-45 的合法續跑**：
    `accept` 回 `duplicate` 但目標物件不存在，呼叫端沿用同一個 `operation_id` 補寫。
    補寫不會多出第二筆 `OPS#`、也不會換 `accept_seq`，所以它和重複處理分得開。
    """
    mark = token()
    slug, project_id = f"o2-resend-{mark}", f"o2-resend-{mark}"
    operation_id = f"op-ticket-t881-{mark}"
    request = AcceptOperation(operation_id, "ticket", operation_id, project_id, now_utc())

    repository = open_repository(table, region)
    operations = OperationCoordinator(repository)
    first = operations.accept(request)  # 接受之後就崩潰：教學還沒建立

    statuses: list[str] = [first.status]
    seqs: list[int | None] = [first.record.accept_seq]
    backfilled = 0
    versions: list[str] = []
    for _ in range(3):
        # 每一次重送都換一組全新的物件，模擬不同 worker／不同程序。
        repeat_repo = open_repository(table, region)
        repeat_ops = OperationCoordinator(repeat_repo)
        acceptance = repeat_ops.accept(request)
        statuses.append(acceptance.status)
        seqs.append(acceptance.record.accept_seq)
        if repeat_repo.get_tutorial(slug) is None:
            seed_tutorial(repeat_repo, slug, version=1)  # D-45 合法補寫
            backfilled += 1
        versions.append(allocate_stub(repeat_repo, repeat_ops, slug=slug,
                                      operation_id=operation_id))

    final = open_repository(table, region)
    observed = _summary({
        "statuses": ",".join(statuses),
        "duplicate": statuses.count("duplicate"),
        "accept_seq": ",".join(str(value) for value in seqs),
        "ops": count_ops(final, project_id),
        "backfilled": backfilled,
        "version_ids": ",".join(sorted(set(versions))),
        "seq_counter": sequence_counter(final, project_id),
    })
    passed = (
        statuses == ["accepted", "duplicate", "duplicate", "duplicate"]
        and len(set(seqs)) == 1
        and seqs[0] == 1
        and count_ops(final, project_id) == 1
        and backfilled == 1
        and set(versions) == {make_version(slug, 2)}
        and sequence_counter(final, project_id) == 4  # 重送燒掉三個號碼，允許缺口
    )
    return O2CaseResult(case, observed, "PASS" if passed else "FAIL",
                        evidence_key(current_run_id()))


def run_lease_expiry(case: O2Case, *, table: str, region: str) -> O2CaseResult:
    """持有者拿了租約就消失（永遠不呼叫 `release_lease`）。

    時間用可注入的 clock 往前撥，不真的睡 30 秒；到期之後另一個 worker 靠
    `expected_revision` 接手。接手的人仍然照 `accept_seq` 挑下一個要做的操作。
    """
    mark = token()
    slug, project_id = f"o2-lease-{mark}", f"o2-lease-{mark}"
    scope = f"TUTORIAL#{slug}"
    base = now_utc()

    repository = open_repository(table, region)
    seed_tutorial(repository, slug, version=1)
    vanished = OperationCoordinator(repository)
    taker = open_coordinator(table, region)

    held = vanished.acquire_lease(scope, "worker-a", ttl_seconds=LEASE_TTL_SECONDS, now=base)
    too_early = taker.acquire_lease(
        scope, "worker-b", ttl_seconds=LEASE_TTL_SECONDS,
        now=base + timedelta(seconds=LEASE_TTL_SECONDS - 1),
    )
    # worker-a 消失，沒有人呼叫 release_lease；租約只能靠到期換手。
    after_expiry = base + timedelta(seconds=LEASE_TTL_SECONDS + 1)
    stale = lease_item(repository, slug)  # TTL 不是準時解鎖：到期 item 仍讀得回來
    taken = taker.acquire_lease(scope, "worker-b", ttl_seconds=LEASE_TTL_SECONDS,
                               now=after_expiry)

    first = taker.accept(
        AcceptOperation(f"op-release-a-{mark}", "release", f"a-{mark}", project_id, base))
    second = taker.accept(
        AcceptOperation(f"op-feedback-b-{mark}", "feedback", f"b-{mark}", project_id, base))
    order = [operation_id for _, operation_id in pending_in_accept_order(repository, project_id)]
    taker.release_lease(scope, "worker-b")
    released = lease_item(repository, slug)

    observed = _summary({
        "held": held,
        "before_expiry": too_early,
        "after_expiry": taken,
        "readable_after_expiry": stale is not None,
        "stale_owner": (stale or {}).get("owner"),
        "ttl_attr_set": (stale or {}).get(TTL_ATTRIBUTE) is not None,
        "accept_seq": f"{first.record.accept_seq},{second.record.accept_seq}",
        "order": ",".join(order),
        "owner_after_release": (released or {}).get("owner") or "(empty)",
    })
    passed = (
        held is True
        and too_early is False
        and taken is True
        and stale is not None
        and str(stale.get("owner")) == "worker-a"
        and stale.get(TTL_ATTRIBUTE) is not None
        and order == [f"op-release-a-{mark}", f"op-feedback-b-{mark}"]
        and first.record.accept_seq is not None
        and second.record.accept_seq is not None
        and first.record.accept_seq < second.record.accept_seq
        and released is not None
        and str(released.get("owner") or "") == ""
    )
    return O2CaseResult(case, observed, "PASS" if passed else "FAIL",
                        evidence_key(current_run_id()))


def run_interleaved(case: O2Case, *, table: str, region: str) -> O2CaseResult:
    """Release 事件與 Feedback Review 的 REFINE 子 operation 同時搶同一篇教學。

    兩個 coordinator 交替呼叫，而且**搶鎖順序刻意與接受順序相反**：先接受的是 release，
    先拿到 lease 的卻是 feedback 的 worker。拿到 lease 的人仍然在待處理清單裡挑
    `accept_seq` 最小的做，所以 v3 一定是 release、v4 一定是 feedback，沒有分叉。
    """
    mark = token()
    slug, project_id = f"o2-inter-{mark}", f"o2-inter-{mark}"
    scope = f"TUTORIAL#{slug}"
    base = now_utc()

    seeder = open_repository(table, region)
    seed_tutorial(seeder, slug, version=2)

    worker_a, worker_b = open_repository(table, region), open_repository(table, region)
    ops_a, ops_b = OperationCoordinator(worker_a), OperationCoordinator(worker_b)

    release = ops_a.accept(
        AcceptOperation(f"op-release-r42-{mark}", "release", f"r42-{mark}", project_id, base))
    feedback = ops_b.accept(
        AcceptOperation(f"op-feedback-{mark}", "feedback", f"fp-{mark}", project_id, base))

    # 搶鎖順序與接受順序相反：B 先拿到鎖，但它要先做 accept_seq 較小的 release。
    b_first = ops_b.acquire_lease(scope, "worker-b", ttl_seconds=LEASE_TTL_SECONDS, now=base)
    a_blocked = ops_a.acquire_lease(scope, "worker-a", ttl_seconds=LEASE_TTL_SECONDS, now=base)

    assigned: list[tuple[str, str]] = []
    holder_repo, holder_ops, holder = worker_b, ops_b, "worker-b"
    while True:
        pending = pending_in_accept_order(holder_repo, project_id)
        if not pending:
            break
        _, operation_id = pending[0]
        version_id = allocate_stub(holder_repo, holder_ops, slug=slug,
                                   operation_id=operation_id)
        publish_stub(holder_repo, slug, version_id)
        holder_ops.complete(operation_id, now=now_utc())
        assigned.append((operation_id, version_id))
        holder_ops.release_lease(scope, holder)
        # 換手：另一個 worker 接著搶同一個 scope，交錯呼叫兩個 coordinator。
        holder_repo, holder_ops, holder = (
            (worker_a, ops_a, "worker-a") if holder == "worker-b" else (worker_b, ops_b, "worker-b")
        )
        holder_ops.acquire_lease(scope, holder, ttl_seconds=LEASE_TTL_SECONDS, now=now_utc())
    holder_ops.release_lease(scope, holder)

    final = open_repository(table, region)
    tutorial = final.get_tutorial(slug)
    versions = [version_id for _, version_id in assigned]
    observed = _summary({
        "accept_seq": f"{release.record.accept_seq},{feedback.record.accept_seq}",
        "lock_order_reversed": b_first is True and a_blocked is False,
        "assigned": ",".join(f"{name}>{version}" for name, version in assigned),
        "current_version": tutorial.current_version if tutorial else "(none)",
        "distinct_versions": len(set(versions)),
        "ops": count_ops(final, project_id),
    })
    passed = (
        b_first is True
        and a_blocked is False
        and release.record.accept_seq is not None
        and feedback.record.accept_seq is not None
        and release.record.accept_seq < feedback.record.accept_seq
        and assigned == [(f"op-release-r42-{mark}", make_version(slug, 3)),
                         (f"op-feedback-{mark}", make_version(slug, 4))]
        and tutorial is not None
        and tutorial.current_version == make_version(slug, 4)
        and count_ops(final, project_id) == 2
    )
    return O2CaseResult(case, observed, "PASS" if passed else "FAIL",
                        evidence_key(current_run_id()))


def resume_after_already_exists(
    operations: OperationCoordinator, operation_id: str
) -> OperationRecord:
    """同名執行已結束時的唯一正解：讀 ledger 的原結果。

    `ExecutionAlreadyExists` **不能**直接當成功（設計 §14.2）：同名冪等只在執行未結束時
    成立，已結束的執行不會再產生結果。ledger 沒有 `version_id` 就 `CoordinationError`，
    **不回成功、也不換一個名字重跑**（換名會產生第二條版本鏈）。
    """
    record = operations.load(operation_id)
    if record is None or not record.version_id:
        raise CoordinationError(
            f"closed execution without a recorded result: {operation_id}")
    return record


def run_closed_execution(case: O2Case, *, table: str, region: str) -> O2CaseResult:
    mark = token()
    slug, project_id = f"o2-closed-{mark}", f"o2-closed-{mark}"
    done_id, empty_id = f"op-release-done-{mark}", f"op-release-empty-{mark}"
    arn = f"arn:aws:states:{region}:123456789012:execution:o2:{done_id}"

    repository = open_repository(table, region)
    seed_tutorial(repository, slug, version=1)
    operations = OperationCoordinator(repository)
    operations.accept(
        AcceptOperation(done_id, "release", done_id, project_id, now_utc()))
    operations.record_execution(done_id, arn)
    finished = allocate_stub(repository, operations, slug=slug, operation_id=done_id)
    publish_stub(repository, slug, finished)
    operations.complete(done_id, now=now_utc())

    # 已結束的同名執行重送：stub 丟 ExecutionAlreadyExists，呼叫端只能讀 ledger。
    resumed_version, resumed_error = "", ""
    try:
        raise ExecutionAlreadyExists(done_id)
    except ExecutionAlreadyExists:
        restarted = open_coordinator(table, region)
        resumed_version = resume_after_already_exists(restarted, done_id).version_id or ""

    # 第二個 operation：接受了但 ledger 從來沒有結果 -> 必須明確失敗。
    operations.accept(
        AcceptOperation(empty_id, "release", empty_id, project_id, now_utc()))
    try:
        raise ExecutionAlreadyExists(empty_id)
    except ExecutionAlreadyExists:
        try:
            resume_after_already_exists(open_coordinator(table, region), empty_id)
            resumed_error = "(none)"
        except CoordinationError:
            resumed_error = "CoordinationError"

    final = open_repository(table, region)
    empty_record = OperationCoordinator(final).load(empty_id)
    tutorial = final.get_tutorial(slug)
    observed = _summary({
        "execution_arn": arn.rsplit(":", 1)[-1],
        "resumed_version": resumed_version or "(none)",
        "no_result": resumed_error,
        "empty_version_id": (empty_record.version_id if empty_record else None) or "(none)",
        "current_version": tutorial.current_version if tutorial else "(none)",
        "ops": count_ops(final, project_id),
    })
    passed = (
        resumed_version == finished == make_version(slug, 2)
        and resumed_error == "CoordinationError"
        and empty_record is not None
        and empty_record.version_id is None
        and tutorial is not None
        and tutorial.current_version == make_version(slug, 2)
        and count_ops(final, project_id) == 2
    )
    return O2CaseResult(case, observed, "PASS" if passed else "FAIL",
                        evidence_key(current_run_id()))


_RUNNERS = {
    "restart": run_restart,
    "resend": run_resend,
    "lease_expiry": run_lease_expiry,
    "interleaved": run_interleaved,
    "closed_execution": run_closed_execution,
}


def run_o2_case(case: O2Case, *, table: str, region: str) -> O2CaseResult:
    """跑一個案例並回四欄觀察值。判定失敗**不丟例外**：FAIL 也是 gate 的合法結論。

    只有真的跑不動（憑證、表不存在）才讓例外往上跑——那是「沒有證據」，不是 FAIL。
    """
    runner = _RUNNERS.get(case.name)
    if runner is None:
        raise KeyError(f"unknown O2 case: {case.name}")
    return runner(case, table=table, region=region)


# --- 5. 判定與報告 -----------------------------------------------------------

COLUMNS = "| 案例 | 注入點 | 期望 | 觀察 | 判定 | 證據 |\n|---|---|---|---|---|---|\n"

_NOTES = (
    "- **鎖不等於接受順序。** 誰先搶到 lease 只代表誰先送達 DynamoDB；順序一律讀 `accept_seq`"
    "（`interleaved` 案例的搶鎖順序刻意與接受順序相反）。\n"
    "- **TTL 不是準時解鎖。** 過期項目在刪除前仍讀得到（`lease_expiry` 的"
    " `readable_after_expiry`）；到期一律自己比 `expires_at`，再用 `expected_revision` 搶佔。\n"
    "- 版號由本 Phase 的替身產生（讀 `current_version` -> 加一 -> `record_version`），"
    "真正的 `allocate_version` 屬於 Phase 20；`closed execution` 用最小 stub，"
    "不實作 `PipelineStarter`（Phase 32）。\n"
    "- 重送會燒掉一個接受號碼：`accept_seq` 只保證單調遞增、可比較，允許缺口。\n"
)

_FAIL_TAIL = (
    "\n## 停止語句（O2 未通過）\n\n"
    "「O2 尚未 PASS，不得宣稱永久去重或 FIFO；建版與接受路徑停止。」\n\n"
    "阻擋：Phase 20、Phase 32、Phase 46、Phase 59 不得開始；"
    "00A 第 4.2 節的追驗 Phase 35、42 同樣不得宣稱重送不會重複累積樣本或重複匯入。\n"
)


def o2_verdict(results: Sequence[O2CaseResult]) -> Literal["PASS", "FAIL"]:
    """五案全 PASS 才 PASS；沒有結果也是 FAIL（空清單不代表通過）。"""
    if not results:
        return "FAIL"
    return "PASS" if all(row.verdict == "PASS" for row in results) else "FAIL"


def render_o2_report(
    results: Sequence[O2CaseResult], *, run_id: str, table: str, region: str
) -> str:
    """六欄固定格式；報告不得只寫「通過」，每一列都要有觀察值與證據路徑。"""
    rows = "".join(
        f"| {row.case.name} | {row.case.fault_point} | {row.case.expectation} |"
        f" {row.observed} | {row.verdict} | {row.evidence_ref} |\n"
        for row in results
    )
    verdict = o2_verdict(results)
    head = f"# O2 報告 {run_id}\n\nRegion：{region}｜表：{table}｜run id：{run_id}\n\n"
    body = f"{head}{COLUMNS}{rows}\n整體判定：{verdict}\n\n## 讀這份報告要記得\n\n{_NOTES}"
    return body + (_FAIL_TAIL if verdict == "FAIL" else "")


# --- 6. 隔離測試表、gate 證據與命令列 ----------------------------------------


def test_table_name(run_id: str) -> str:
    return f"{TEST_TABLE_PREFIX}{run_id}"


def create_test_table(run_id: str, region: str) -> str:
    """建立隔離的測試單表：PK／SK 與正式表相同、PAY_PER_REQUEST、`ttl` 開 TTL。

    開 TTL 不是為了靠它解鎖（正好相反）：`lease_expiry` 要證明**TTL 開著、item 到期
    也還讀得到**，所以這張表一定要真的設定過 `TimeToLiveSpecification`。
    """
    table = test_table_name(run_id)
    client = boto3.client("dynamodb", region_name=region, config=SDK_CONFIG)
    client.create_table(
        TableName=table,
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    client.get_waiter("table_exists").wait(TableName=table)
    client.update_time_to_live(
        TableName=table,
        TimeToLiveSpecification={"Enabled": True, "AttributeName": TTL_ATTRIBUTE},
    )
    return table


def delete_test_table(table: str, region: str) -> None:
    client = boto3.client("dynamodb", region_name=region, config=SDK_CONFIG)
    client.delete_table(TableName=table)
    client.get_waiter("table_not_exists").wait(TableName=table)


def table_exists(table: str, region: str) -> bool:
    client = boto3.client("dynamodb", region_name=region, config=SDK_CONFIG)
    try:
        client.describe_table(TableName=table)
    except ClientError as error:
        if error.response["Error"]["Code"] == "ResourceNotFoundException":
            return False
        raise
    return True


def evidence_payload(
    results: Sequence[O2CaseResult], *, run_id: str, table: str, region: str, started_at: str,
) -> dict[str, Any]:
    """原始觀察值；報告是給人看的摘要，這份 JSON 才是逐欄的證據（00A §3.4）。"""
    return {
        "run_id": run_id,
        "gate": "O2",
        "region": region,
        "table": table,
        "started_at": started_at,
        "finished_at": to_iso(now_utc()),
        "verdict": o2_verdict(results),
        "sequence_attempts": 8,
        "lease_ttl_seconds": LEASE_TTL_SECONDS,
        "cases": [
            {**asdict(row.case), "observed": row.observed, "verdict": row.verdict}
            for row in results
        ],
    }


def put_evidence(payload: Mapping[str, Any], *, bucket: str, run_id: str, region: str) -> str:
    """把證據寫進正式 bucket 的**私有**前綴 `operations/o2/<run_id>.json` 再讀回來核對。"""
    client = boto3.client("s3", region_name=region, config=SDK_CONFIG)
    key = evidence_key(run_id)
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode()
    client.put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/json")
    stored = client.get_object(Bucket=bucket, Key=key)["Body"].read()
    if stored != body:
        raise RuntimeError(f"證據寫入後讀回不一致：{key}")
    return f"s3://{bucket}/{key}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="O2 接受順序與重啟整合驗證（gate 用）")
    parser.add_argument("--region", default=None,
                        help=f"預設讀 {REGION_ENV}，再退到 {DEFAULT_REGION}")
    parser.add_argument("--run-id", default=None, help="報告檔名與表名的 run id，預設 UTC 時間戳")
    parser.add_argument("--bucket", default=None, help=f"證據 bucket，預設讀 {BUCKET_ENV}")
    parser.add_argument("--report-dir", default=None, help=f"報告輸出目錄，預設 {REPORT_DIR}")
    parser.add_argument("--provision", action="store_true",
                        help="只建立隔離測試表並印出環境變數，不跑案例")
    parser.add_argument("--teardown", action="store_true", help="只刪除隔離測試表")
    parser.add_argument("--keep", action="store_true", help="跑完不刪隔離表（預設會刪）")
    return parser


def _run_child(argv: Sequence[str]) -> int:
    """`--child-restart <table> <region> <slug> <operation_id> <project_id>`。

    這個分支永遠不會正常返回：它會在 `record_version` 之後把自己 `SIGKILL` 掉。
    """
    table, region, slug, operation_id, project_id = argv[1:6]
    restart_child(table, region, slug, operation_id, project_id)
    return 1  # pragma: no cover - SIGKILL 之後到不了這裡


def run_log(
    *, run_id: str, table: str, region: str, lifecycle: Mapping[str, str], evidence: str
) -> str:
    """報告尾巴的執行紀錄：隔離表的建立／刪除時間與確認輸出，加上逐字的重現指令。

    「跑完就刪」是本 gate 的規則，所以刪除時間與刪除後的 `table_exists` 一定要留在報告裡；
    沒有這兩行，讀報告的人無法確認測試資源沒有殘留。
    """
    steps = "\n".join(f"| {key} | {value} |" for key, value in lifecycle.items())
    return (
        "\n## 隔離測試表生命週期\n\n"
        f"表名：`{table}`（PK／SK 同正式表、PAY_PER_REQUEST、TTL 屬性 `ttl`）；"
        "正式 `training_kb` 表完全不碰，只有 gate 證據寫進正式 bucket 的私有 "
        f"`{EVIDENCE_PREFIX}` 前綴。\n\n"
        "| 步驟 | 時間／輸出 |\n|---|---|\n"
        f"{steps}\n| 證據物件 | {evidence or '(未上傳)'} |\n"
        "\n## 重現指令\n\n"
        "```bash\n"
        f"# 1. 建立隔離表（印出三個環境變數）\n"
        f"TKB_AWS_REGION={region} uv run python infra/scripts/o2_report.py \\\n"
        f"    --provision --region {region} --run-id {run_id}\n"
        f"# 2. 五個案例對真實表跑一次\n"
        f"TKB_RUN_AWS_INTEGRATION=1 TKB_AWS_REGION={region} TKB_TABLE_NAME={table} \\\n"
        f"TKB_O2_RUN_ID={run_id} uv run pytest tests/integration/test_o2_cases.py -q -m aws\n"
        f"# 3. 產報告與證據，跑完自動刪表\n"
        f"TKB_AWS_REGION={region} TKB_CONTENT_BUCKET=<正式 bucket> \\\n"
        f"uv run python infra/scripts/o2_report.py --region {region} --run-id {run_id}\n"
        f"# 4. 人工複核三種 item（需先用 --keep 保留表）\n"
        f"aws dynamodb get-item --region {region} --table-name {table} \\\n"
        "    --key '{\"PK\":{\"S\":\"OPS#<operation_id>\"},\"SK\":{\"S\":\"META\"}}'\n"
        "```\n"
    )


def main(argv: Sequence[str] | None = None) -> int:
    """全程跑完回 0（PASS）或 2（FAIL）；FAIL 是本 gate 允許的結論之一，不是腳本崩潰。"""
    raw = list(sys.argv[1:] if argv is None else argv)
    if raw and raw[0] == CHILD_FLAG:
        return _run_child(raw)

    args = build_parser().parse_args(raw)
    if args.region:
        os.environ[REGION_ENV] = str(args.region)
    region = case_region()
    started_at = to_iso(now_utc())
    run_id = str(args.run_id) if args.run_id else _stamp(started_at)
    os.environ[RUN_ID_ENV] = run_id
    table = test_table_name(run_id)

    if args.teardown:
        delete_test_table(table, region)
        print(f"已刪除隔離測試表（{to_iso(now_utc())}）：{table}")
        return 0

    lifecycle: dict[str, str] = {}
    if table_exists(table, region):
        lifecycle["沿用既有隔離表"] = f"{to_iso(now_utc())}（`--provision` 先建立的同一張）"
    else:
        create_test_table(run_id, region)
        lifecycle["建立"] = f"{to_iso(now_utc())}｜PAY_PER_REQUEST｜TTL 屬性 `{TTL_ATTRIBUTE}`"
        print(f"已建立隔離測試表（{to_iso(now_utc())}）：{table}（{region}）")
    if args.provision:
        print(f"{TABLE_ENV}={table}\n{REGION_ENV}={region}\n{RUN_ID_ENV}={run_id}")
        return 0

    results: list[O2CaseResult] = []
    evidence = ""
    try:
        results = [run_o2_case(case, table=table, region=region) for case in O2_CASES]
        lifecycle["五個案例跑完"] = to_iso(now_utc())
        bucket = args.bucket or os.environ.get(BUCKET_ENV)
        if bucket:
            payload = evidence_payload(results, run_id=run_id, table=table,
                                       region=region, started_at=started_at)
            evidence = put_evidence(payload, bucket=bucket, run_id=run_id, region=region)
            print(f"證據：{evidence}")
        else:
            print(f"未指定 {BUCKET_ENV}，跳過證據上傳（報告仍會寫出）")
    finally:
        if not args.keep:
            delete_test_table(table, region)
            lifecycle["刪除"] = to_iso(now_utc())
            lifecycle["刪除後確認"] = f"`table_exists` -> {table_exists(table, region)}"
            print(f"已刪除隔離測試表（{to_iso(now_utc())}）：{table}")
    report = render_o2_report(results, run_id=run_id, table=table, region=region) + run_log(
        run_id=run_id, table=table, region=region, lifecycle=lifecycle, evidence=evidence
    )
    report_dir = Path(args.report_dir) if args.report_dir else REPORT_DIR
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"o2-{run_id}.md"
    report_path.write_text(report, encoding="utf-8")
    print(report)
    print(f"報告：{report_path}")
    return 2 if o2_verdict(results) == "FAIL" else 0


def _stamp(started_at: str) -> str:
    return started_at.replace(":", "").replace("-", "").lower()


if __name__ == "__main__":  # pragma: no cover - 命令列進入點
    raise SystemExit(main())
