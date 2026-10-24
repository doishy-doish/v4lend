from perceive import objects, delta
from world_model import DualWorld, simple_rank, full_rank

GRID = [[2, 2, 0, 3], [2, 2, 0, 0]]


def test_dual_agrees_on_single():
    w = DualWorld()
    w.fit(objects([[3]]))
    assert w.agree()
    assert len(w.explore_order()) == 1


def test_dual_disagrees_then_explores():
    w = DualWorld()
    w.fit(objects(GRID))
    assert not w.agree()
    order = w.explore_order()
    assert len(order) == 2
    assert w.explorations == 1


def test_confirm_keeps_verifying_rule():
    w = DualWorld()
    w.fit(objects(GRID))
    change = [(3, 0, 0, 7)]
    tested = [w.confirm(r, change) for r in w.explore_order()]
    assert any(tested)
