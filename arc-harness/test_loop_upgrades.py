from gate import BuilderGate
from search import canonical_hash, score_grid, bfs_plan, choose_strategy, disagreement


def _rot90(grid):
    return [list(r) for r in zip(*grid[::-1])]


def test_canonical_hash_rotation_invariant():
    grid = [[1, 0, 2], [0, 7, 0], [3, 0, 4]]
    assert canonical_hash(grid) == canonical_hash(_rot90(grid))
    assert canonical_hash(grid) != canonical_hash([[9, 9], [9, 9]])


def test_score_grid_prefers_cleaner():
    messy = [[7, 8, 9], [0, 0, 0]]
    clean = [[1, 1, 0], [1, 1, 0]]
    assert score_grid(clean) > score_grid(messy)


def test_bfs_plan_finds_chain():
    plan = bfs_plan(lambda x: [(1, x + 1)], 0, lambda x: x == 5, max_depth=10)
    assert plan == [1, 1, 1, 1, 1]
    assert bfs_plan(lambda x: [(1, x + 1)], 0, lambda x: x == 99, max_depth=5) is None


def test_strategy_switch():
    assert choose_strategy(True, True) == "EXPLOIT"
    assert choose_strategy(False, False) == "EXPLORE"
    assert choose_strategy(True, False) == "EXPLORE"


def test_disagreement_fires_builder():
    assert disagreement([[1]], [[2]])
    assert not disagreement([[1]], [[1]])
    gate = BuilderGate(threshold=0.5, patience=2)
    assert not gate.observe(0.9, False)
    assert gate.observe(0.9, False)
    assert gate.request_builder() and gate.requests == 1
