"""Phase 38 Task 3：以群中心歸群、固定 0.85 邊界、同分取最小 `cluster_id`。

單元測試用五維向量就夠驗證比較與排序；1024 維契約由 Phase 16 負責，這裡綠燈**不代表**
Titan 或分群已在真實模型上驗證（O5 未通過）。併發下新群 ID 不撞號屬於 O2，也未驗收。
"""

import pytest

from training_kb.errors import PermanentError
from training_kb.pipelines.ticket import (
    CLUSTER_COSINE_THRESHOLD,
    assign_cluster,
    new_cluster_id,
)
from training_kb.vectors import cosine
from training_kb.writing.client import TITAN_DIMENSIONS

# 四個種子刻意用整數構成，讓 cosine 精確：dot = 17、|AXIS| = 1、|ON| = 20、17 / 20 = 0.85。
# `Ticket.embedding`（P04）只收「1024 個有限數值」，所以種子要補零到 TITAN_DIMENSIONS 才
# 放得進模型；補零不動 dot 也不動任何一條 norm，上面那個算式原封不動成立。
SEED_AXIS = [1.0, 0.0, 0.0, 0.0, 0.0]
SEED_ON = [17.0, 7.0, 6.0, 5.0, 1.0]
SEED_BELOW = [16.99, 7.0, 6.0, 5.0, 1.0]        # 約 0.84986，穩定落在門檻下方
SEED_ORTHOGONAL = [0.0, 1.0, 0.0, 0.0, 0.0]
SEED_DOUBLE = [33.0, 14.0, 12.0, 10.0, 2.0]     # 與 SEED_AXIS 平均後正好是 SEED_ON
SEED_SAME_DIRECTION = [3.0, 0.0, 0.0, 0.0, 0.0]


def vector(seed: list[float]) -> list[float]:
    """把五維種子補零成 `Ticket.embedding` 收得下的 1024 維向量。"""
    return seed + [0.0] * (TITAN_DIMENSIONS - len(seed))


AXIS = vector(SEED_AXIS)
ON = vector(SEED_ON)
BELOW = vector(SEED_BELOW)
ORTHOGONAL = vector(SEED_ORTHOGONAL)


def test_threshold_is_an_alias_of_the_config_field():
    """模組裡沒有第二份 0.85：常數就是 `Thresholds.cosine_match`（00A §5.4、D-35）。"""
    from training_kb.config import Thresholds

    assert CLUSTER_COSINE_THRESHOLD == Thresholds().cosine_match


def test_reference_vectors_sit_on_both_sides_of_the_threshold():
    assert cosine(SEED_AXIS, SEED_ON) == 0.85       # 五維的精確算式：17 / 20
    assert cosine(AXIS, ON) == 0.85                 # 補零到 1024 維後完全一樣
    assert cosine(AXIS, BELOW) < 0.85
    assert len(AXIS) == TITAN_DIMENSIONS


@pytest.mark.parametrize(("vector", "expected"), [(ON, "c12"), (BELOW, "c14")])
def test_assign_cluster_threshold_is_inclusive(fake_repo, clustered, unclustered,
                                               vector, expected):
    fake_repo.tickets = [clustered("t_100", "c12", vector), clustered("t_101", "c13", ORTHOGONAL)]
    assert assign_cluster(unclustered("t_881", AXIS), repository=fake_repo) == expected


def test_assign_cluster_breaks_ties_by_cluster_id(fake_repo, clustered, unclustered):
    fake_repo.tickets = [clustered("t_100", "c12", AXIS), clustered("t_101", "c07", AXIS)]
    assert assign_cluster(unclustered("t_882", AXIS), repository=fake_repo) == "c07"


def test_single_member_group_still_goes_through_the_centroid(fake_repo, clustered, unclustered):
    """群裡只有一筆也要走 `centroid`，不是拿「第一筆」當代表（F10）。

    c12 有兩筆、平均後正好落在門檻上；c13 只有一筆但完全同向（1.0），所以最高分是 c13。
    用「第一筆當代表」的寫法會讓 c12 也拿到 1.0 而搶走答案。
    """
    fake_repo.tickets = [clustered("t_100", "c12", AXIS),
                         clustered("t_101", "c12", vector(SEED_DOUBLE)),
                         clustered("t_102", "c13", vector(SEED_SAME_DIRECTION))]
    assert assign_cluster(unclustered("t_881", AXIS), repository=fake_repo) == "c13"


def test_member_without_embedding_is_skipped_but_the_group_survives(
        fake_repo, clustered, unclustered):
    """成員缺 `embedding` 只略過那一筆，不整群作廢。"""
    fake_repo.tickets = [clustered("t_100", "c12", None), clustered("t_101", "c12", ON)]
    assert assign_cluster(unclustered("t_881", AXIS), repository=fake_repo) == "c12"


def test_group_with_no_usable_vector_still_reserves_its_number(fake_repo, clustered, unclustered):
    """整群都沒有向量時比不了，但編號已經用掉了：新群不得再叫 c12。"""
    fake_repo.tickets = [clustered("t_100", "c12", None)]
    assert assign_cluster(unclustered("t_881", AXIS), repository=fake_repo) == "c13"


def test_first_cluster_is_c1_when_nothing_exists(fake_repo, unclustered):
    fake_repo.tickets = []
    assert assign_cluster(unclustered("t_881", AXIS), repository=fake_repo) == "c1"


def test_existing_cluster_id_is_returned_unchanged(fake_repo, clustered):
    """重送沿用既有歸群（設計 §14.2）：連資料庫都不必掃。"""
    fake_repo.tickets = [clustered("t_100", "c12", AXIS)]
    assert assign_cluster(clustered("t_881", "c99", ORTHOGONAL), repository=fake_repo) == "c99"


def test_ticket_does_not_match_its_own_vector(fake_repo, clustered):
    """同一筆已經在表裡時不能拿自己當群中心；它自己的群仍算既有編號。"""
    ticket = clustered("t_881", "c12", AXIS)
    fake_repo.tickets = [ticket]
    unassigned = ticket.model_copy(update={"cluster_id": None})
    assert assign_cluster(unassigned, repository=fake_repo) == "c13"


def test_assign_cluster_requires_a_stored_embedding(fake_repo, ticket_without_embedding):
    with pytest.raises(PermanentError, match="embedding"):
        assign_cluster(ticket_without_embedding("t_881"), repository=fake_repo)


def test_assign_cluster_never_calls_the_model(fake_repo, clustered, unclustered,
                                              embedding_writer):
    """歸群完全是程式行為：整個 Task 3 沒有任何案例呼叫 `writer.embed`。"""
    fake_repo.tickets = [clustered("t_100", "c12", ON)]
    assign_cluster(unclustered("t_881", AXIS), repository=fake_repo)
    assert embedding_writer.embed_calls == 0


def test_only_the_same_project_is_scanned(fake_repo, clustered, unclustered):
    """`list_tickets(project_id)` 是唯一入口：別的專案的群不會被借用。"""
    other = clustered("t_100", "c12", AXIS).model_copy(update={"project_id": "other"})
    fake_repo.tickets = [other]
    assert assign_cluster(unclustered("t_881", AXIS), repository=fake_repo) == "c1"


@pytest.mark.parametrize(("existing", "expected"), [
    ((), "c1"),
    (("c1",), "c2"),
    (("c1", "c9", "c3"), "c10"),
    (("c12", "gap", "cluster"), "c13"),     # 只認得 c<數字>，其他字串不影響編號
])
def test_new_cluster_id_takes_the_largest_number_plus_one(existing, expected):
    assert new_cluster_id(existing) == expected


def test_new_cluster_id_never_returns_an_existing_id():
    existing = ["c1", "c01", "c10", "c2", "gap"]
    assert new_cluster_id(existing) not in set(existing)
