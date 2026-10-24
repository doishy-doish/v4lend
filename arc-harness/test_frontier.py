from world_model import DualWorld
from perceive import objects
import adequacy
from gate import BuilderGate

GRID = [[2, 2, 0, 3], [2, 2, 0, 0]]


def test_low_error_when_explained():
    w = DualWorld()
    w.fit(objects(GRID))
    rules = w.simple.rules
    err = adequacy.ontology_error(rules, [(GRID, [[2, 2, 0, 7], [2, 2, 0, 0]])])
    assert err == 0.0


def test_high_error_when_novel():
    w = DualWorld()
    w.fit(objects([[3]]))
    err = adequacy.ontology_error(w.simple.rules, [(GRID, [[9]*4, [9]*4])])
    assert err == 1.0


def test_gate_requests_only_when_stuck():
    g = BuilderGate(threshold=0.5, patience=2)
    assert not g.observe(0.9, False)
    assert g.observe(0.9, False)
    assert g.request_builder() and g.requests == 1
    assert not g.observe(0.1, True)
