import socket

import pytest

import kaggle
from agent import MyAgent, run_episode


def test_watchdog_writes_csv_on_deadline(tmp_path):
    a = MyAgent(seed=1)
    t = [0.0]
    def now():
        t[0] += 10.0
        return t[0]
    cp = str(tmp_path / "submission.csv")
    rep = kaggle.run_with_watchdog(a, [[0]], ["stay"], 200, 25, cp, time_fn=now)
    assert rep["status"] == "deadline" and rep["turns"] == 2
    assert kaggle.validate_csv(cp, ["stay"])["rows"] == 2


def test_airplane_mode(tmp_path):
    a = MyAgent(seed=1)
    with kaggle.offline():
        with pytest.raises(ConnectionError):
            socket.socket()
        assert run_episode(a, [[0]], ["stay"], max_turns=3)
        cp = str(tmp_path / "submission.csv")
        kaggle.write_csv(cp, a.turns)
    assert kaggle.validate_csv(cp, ["stay"])["rows"] == 3


def test_csv_schema_hard_lock(tmp_path):
    good = tmp_path / "good.csv"
    good.write_text("game_id,turn,action\n0,0,stay\n0,1,stay\n")
    assert kaggle.validate_csv(str(good), ["stay"])["rows"] == 2
    bad = tmp_path / "bad.csv"
    bad.write_text("game_id,turn,action,idx\n0,0,stay,0\n0,1,NaN,1\n")
    with pytest.raises(AssertionError):
        kaggle.validate_csv(str(bad), ["stay"])


def test_model_load_fallback(tmp_path):
    log = []
    def oom():
        raise MemoryError("Killed")
    m, status = kaggle.ensure_model(oom, log)
    assert m is None and status == "MODEL_FAILED_TO_LOAD"
    assert log and log[0]["event"] == "MODEL_FAILED_TO_LOAD"
    cp = str(tmp_path / "submission.csv")
    kaggle.write_csv(cp, [{"action": "stay"}])
    assert kaggle.validate_csv(cp, ["stay"])["rows"] == 1
