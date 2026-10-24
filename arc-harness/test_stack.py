from perceive import objects, delta
from synth import candidates, verify

GRID = [[0, 1, 0], [1, 1, 1], [0, 1, 0]]


def test_plus_is_one_object():
    objs = objects(GRID)
    assert len(objs) == 1 and objs[0]["color"] == 1 and objs[0]["size"] == 5


def test_delta_spots_change():
    b = [row[:] for row in GRID]
    b[0][0] = 7
    d = delta(GRID, b)
    assert d == [(0, 0, 0, 7)]


def test_candidates_rank_small_first():
    objs = objects([[2, 2, 0, 3], [2, 2, 0, 0]])
    rules = candidates(objs)
    assert rules and rules[0]["target"] == 3 and rules[0]["size"] == 1


def test_verify_hits_changed_cells():
    rule = {"op": "click", "target": 1, "size": 1, "cells": [(0, 0)]}
    assert verify(rule, [(0, 0, 0, 7)])
    assert not verify({"op": "click", "target": 9, "size": 9, "cells": [(2, 2)]}, [(0, 0, 0, 7)])
