import os
from agent import ModuleStore, MyAgent, run_episode, write_actions_csv

SAMPLE_GRIDS = [
    {"grid": [[0, 1, 0], [1, 1, 1], [0, 1, 0]], "legal": ["up", "down", "left", "right"]},
    {"grid": [[2, 2], [2, 0]], "legal": ["up", "down"]},
    {"grid": [[3]], "legal": ["stay"]},
]


def test_save_accepts_good():
    s = ModuleStore()
    ok = s.save_module("m1", "def move(b):\n    return 1\n", [lambda ns: ns["move"](None) == 1])
    assert ok and "m1" in s.modules


def test_save_rejects_bad_code():
    s = ModuleStore()
    assert not s.save_module("bad", "def broken(:\n", [])
    assert "bad" not in s.modules


def test_save_rejects_regression():
    s = ModuleStore()
    assert s.save_module("m", "def f():\n    return 1\n", [lambda ns: ns["f"]() == 1])
    assert not s.save_module("m", "def f():\n    return 2\n", [lambda ns: ns["f"]() == 1])
    assert "return 1" in s.modules["m"]


def test_episodes_on_sample_grids():
    for g in SAMPLE_GRIDS:
        a = MyAgent(seed=7)
        assert run_episode(a, g["grid"], g["legal"], max_turns=6)
        assert len(a.turns) == 6


def test_logging_and_csv(tmp_path):
    a = MyAgent(seed=1)
    assert run_episode(a, [[0]], ["stay"], max_turns=3)
    tp = str(tmp_path / "turns.jsonl")
    cp = str(tmp_path / "actions.csv")
    a.dump_turns(tp)
    write_actions_csv(a.turns, cp)
    assert os.path.getsize(tp) > 0
    with open(cp) as f:
        lines = f.read().strip().split("\n")
    assert lines[0] == "game_id,turn,action" and len(lines) == 4
