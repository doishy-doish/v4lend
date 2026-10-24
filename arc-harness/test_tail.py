import time

import adequacy
from agent import MyAgent, ModuleStore, run_episode, write_actions_csv
from compact import summarize
from concurrency import run_many
from perceive import objects
from world_model import DualWorld


def test_seed_determinism():
    board = [[0] * 3 for _ in range(3)]
    legal = ["up", "down", "left", "right"]
    a1, a2 = MyAgent(seed=9), MyAgent(seed=9)
    s1 = [a1.choose_action(board, legal) for _ in range(6)]
    s2 = [a2.choose_action(board, legal) for _ in range(6)]
    assert s1 == s2 and all(x in legal for x in s1)


def test_summarize_edges():
    assert summarize([], keep=5) == ([], None)
    notes = [{"note": "a"}, {"note": "b"}]
    assert summarize(notes, keep=5) == (notes, None)
    short = [{"action": "x%d" % i} for i in range(3)]
    assert summarize(short, keep=10) == (short, None)
    mixed = [{"action": "solo"}, {"note": "n"}]
    assert summarize(mixed, keep=5) == (mixed, None)


def test_ontology_error_steers_to_both_models():
    grid = [[2, 2, 0, 3], [2, 2, 0, 0]]
    after = [row[:] for row in grid]
    after[0][2] = 9
    after[1][3] = 9
    w = DualWorld()
    w.fit(objects(grid))
    err = adequacy.ontology_error(w.simple.rules, [(grid, after)])
    assert err == 1.0
    assert not w.agree() and len(w.explore_order()) == 2


def test_workers_scale_bounded():
    grids = [{"grid": [[i % 2]], "legal": ["stay"]} for i in range(32)]
    t0 = time.time()
    res = run_many(grids, max_turns=2, workers=4, seed=5)
    dt = time.time() - t0
    assert len(res) == 32 and all(r["ok"] for r in res)
    assert sum(r["turns"] for r in res) == 64 and dt < 15


def test_csv_schema(tmp_path):
    a = MyAgent(seed=2)
    assert run_episode(a, [[0]], ["stay"], max_turns=3)
    cp = str(tmp_path / "actions.csv")
    write_actions_csv(a.turns, cp)
    rows = open(cp).read().strip().split("\n")
    assert rows[0] == "game_id,turn,action" and len(rows) == 4
    assert [r.split(",")[1] for r in rows[1:]] == ["0", "1", "2"]


def test_module_store_logs():
    s = ModuleStore()
    assert not s.save_module("bad", "def broken(:\n", [])
    assert s.log and s.log[-1]["event"] == "compile_fail"
    assert s.save_module("m", "def f():\n    return 1\n", [lambda ns: ns["f"]() == 1])
    assert not s.save_module("m", "def f():\n    return 2\n", [lambda ns: ns["f"]() == 1])
    assert s.log[-1]["event"] == "regression_fail" and "return 1" in s.modules["m"]
