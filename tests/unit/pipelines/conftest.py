"""三條 pipeline 單元測試共用的 `Deps`／state fixture（00A §3.2 由 Phase 38 建立）。

這裡的 writer 替身刻意**不叫 `fake_writer`**：`tests/unit/conftest.py` 已經有一個形狀完全
不同的 `fake_writer`（Phase 15 的 `RecordingWriter`），近端 conftest 用同一個名字會**無聲地**
把它蓋掉，讓同目錄其他 Phase 的測試拿到形狀不對的替身。本 Phase 只需要一個會數 `embed`
次數的替身，所以另取名 `embedding_writer` 並存。

三個 `Ticket` 工廠用 pytest 官方的「factory as fixture」寫法提供：conftest.py 的模組層級
函式不會自動出現在測試模組的命名空間裡，工廠必須是 fixture 才取用得到。
"""

from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from training_kb.config import Settings
from training_kb.errors import CoordinationError
from training_kb.keys import ticket_pk
from training_kb.models import Ticket

FIXED_TS = datetime(2026, 9, 14, 3, 0, 0, tzinfo=UTC)
"""工廠造出的 `Ticket.ts`：UTC 整秒（`models.py` 會拒絕帶微秒的 datetime）。"""

FIXED_NOW = datetime(2026, 9, 14, 12, 0, 0, tzinfo=UTC)
"""`fake_clock` 固定回這個 aware UTC 時間，讓所有斷言可重現。"""

DEFAULT_EMBEDDING = [0.1] * 1024
"""`embedding_writer.embedding` 的預設值；1024 是 Titan 的維度契約（P16）。"""


class FakeOperations:
    """只記錄呼叫的假 `OperationCoordinator`。

    Phase 38 的業務函式不呼叫它，這個替身只為了「建得出 `Deps`」而存在。
    """

    def __init__(self) -> None:
        self.failures: list[tuple[str, str, bool]] = []

    def fail(self, operation_id: str, error: str, retryable: bool, *, now: datetime) -> None:
        self.failures.append((operation_id, error, retryable))


class EmbeddingWriter:
    """只實作 `Writer.embed` 的替身：數呼叫次數，設了 `error` 就改丟該例外。

    `embed_calls` 在丟例外**之前**就加一，因為「模型被呼叫過」是事實，失敗案例要
    斷言得到「叫了一次但沒有寫回」。
    """

    def __init__(self) -> None:
        self.embedding: list[float] = list(DEFAULT_EMBEDDING)
        self.error: Exception | None = None
        self.embed_calls = 0
        self.calls: list[dict[str, str]] = []

    def embed(self, text: str, *, operation_id: str, node: str) -> list[float]:
        self.embed_calls += 1
        self.calls.append({"text": text, "operation_id": operation_id, "node": node})
        if self.error is not None:
            raise self.error
        return list(self.embedding)


class FakeRepository:
    """用一個 dict 當表的假 `Repository`；三個方法的行為與 Phase 06／08 的真實版本對齊。

    `put_meta(create_only=True)` 撞鍵時照真實版本丟 `CoordinationError`，所以「回填向量
    必須用 `create_only=False`」這條規則不必另外開測試鉤子就擋得住。
    `list_tickets` 也照真實版本濾 `project_id` 並依 `id` 升序，掃描順序不會恰好等於
    測試指派的順序，同分排序的斷言才有意義。
    """

    def __init__(self) -> None:
        self.items: dict[str, Ticket] = {}
        self.tickets: list[Ticket] = []

    # --- 真實 Repository 也有的三個方法 ---

    def get_meta(self, pk: str, model: type[Ticket], *, consistent: bool = True) -> Ticket | None:
        return self.items.get(pk)

    def put_meta(self, entity: Ticket, *, create_only: bool = True) -> None:
        pk = ticket_pk(entity.id)
        if create_only and pk in self.items:
            raise CoordinationError(f"metadata already exists or changed since read: {pk}")
        self.items[pk] = entity

    def list_tickets(self, project_id: str) -> list[Ticket]:
        rows = [row for row in self.tickets if row.project_id == project_id]
        return sorted(rows, key=lambda row: row.id)

    # --- 三個測試鉤子 ---

    def save_ticket(self, ticket: Ticket) -> Ticket:
        """先把一筆 TICKET 放進表裡（模擬接入層已建立），回傳同一筆。"""
        self.items[ticket_pk(ticket.id)] = ticket
        return ticket

    def loaded(self, pk: str) -> Ticket:
        """讀回已存模型；鍵一律由 `ticket_pk` 產生，測試不手寫 `"TICKET#t_881"`。"""
        return self.items[pk]


@pytest.fixture
def fake_operations() -> FakeOperations:
    return FakeOperations()


@pytest.fixture
def fake_clock() -> Callable[[], datetime]:
    return lambda: FIXED_NOW


@pytest.fixture
def embedding_writer() -> EmbeddingWriter:
    return EmbeddingWriter()


@pytest.fixture
def fake_repo() -> FakeRepository:
    return FakeRepository()


@pytest.fixture
def settings() -> Settings:
    return Settings(table_name="training_kb", content_bucket="tkb", project_id="demo")


def _ticket(ticket_id: str, *, cluster_id: str | None = None,
            embedding: list[float] | None = None) -> Ticket:
    return Ticket(id=ticket_id, source="github_issue", text=f"{ticket_id} 的原始提問",
                  author="reporter", ts=FIXED_TS, project_id="demo",
                  cluster_id=cluster_id, embedding=embedding)


@pytest.fixture
def ticket_without_embedding() -> Callable[[str], Ticket]:
    """缺向量也還沒歸群的工單。"""
    return lambda ticket_id: _ticket(ticket_id)


@pytest.fixture
def clustered() -> Callable[[str, str, list[float]], Ticket]:
    """已歸群且有向量的工單，用來組出群中心。"""
    return lambda ticket_id, cluster_id, vector: _ticket(
        ticket_id, cluster_id=cluster_id, embedding=vector)


@pytest.fixture
def unclustered() -> Callable[[str, list[float]], Ticket]:
    """有向量但還沒歸群的工單，也就是 `assign_cluster` 的輸入。"""
    return lambda ticket_id, vector: _ticket(ticket_id, embedding=vector)
