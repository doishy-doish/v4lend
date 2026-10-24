import json
import os
import resource
import sys
import time

from agent import MyAgent, run_episode
from compact import summarize
from gate import BuilderGate

METRICS = {}


def rss_kb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss


def test_dependency_freeze():
    os.environ.pop("MODEL_PATH", None)
    bad = [m for m in sys.modules if m == "torch" or m.startswith("torch.")]
    assert not bad
    import model
    assert model.load_model() is None
    assert os.path.exists("requirements.txt")
    assert "pytest" in open("requirements.txt").read()
    METRICS["env"] = {"torch_loaded": False, "model_stub": True}


def test_hallucination_trap():
    a = MyAgent(seed=4)
    assert run_episode(a, [[]], ["stay"], max_turns=5)
    assert run_episode(a, None, ["stay"], max_turns=5)
    assert run_episode(a, [[0]], [], max_turns=5)
    METRICS["trap"] = {"corrupt_frames_survived": 3}


def test_full_200_burn():
    grid = [[0, 1, 0], [1, 1, 1], [0, 1, 0]]
    legal = ["up", "down", "left", "right"]
    a = MyAgent(seed=6)
    t0 = time.time()
    ok = run_episode(a, grid, legal, max_turns=200)
    dt = time.time() - t0
    assert ok and len(a.turns) == 200
    compacted, _ = summarize(a.turns, keep=20)
    kept = len([t for t in compacted if "note" not in t])
    assert kept == 25
    gate = BuilderGate(threshold=0.5, patience=3)
    reqs = 0
    for _ in range(200):
        if gate.observe(0.9, False):
            gate.request_builder()
            reqs += 1
    assert reqs <= 200 // 3 + 1
    METRICS["burn"] = {"turns": 200, "kept": kept, "builder_reqs": reqs, "seconds": dt}


def test_state_bloat():
    before = rss_kb()
    total = 0
    for i in range(20):
        a = MyAgent(seed=100 + i)
        assert run_episode(a, [[i % 2]], ["stay"], max_turns=10)
        total += len(a.turns)
    growth_kb = rss_kb() - before
    assert total == 200 and growth_kb < 50 * 1024
    METRICS["bloat"] = {"games": 20, "turns": total, "rss_growth_kb": growth_kb}


def test_write_preflight_metrics():
    with open("preflight-metrics.json", "w") as f:
        json.dump(METRICS, f, indent=2)
    assert set(METRICS) == {"env", "trap", "burn", "bloat"}
    print("PREFLIGHT_OK " + json.dumps(METRICS))
