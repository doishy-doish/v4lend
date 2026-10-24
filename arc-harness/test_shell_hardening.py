import json
import time

from agent import MyAgent, run_episode
from tiers import segment, priority_targets
from search import canonical_hash


def test_disk_io_200_turns(tmp_path):
    a = MyAgent(seed=8)
    assert run_episode(a, [[0]], ["stay"], max_turns=200)
    log = tmp_path / "turns.jsonl"
    t0 = time.time()
    worst = 0.0
    with open(str(log), "w") as f:
        for t in a.turns:
            s = time.time()
            f.write(json.dumps(t) + "\n")
            dt = time.time() - s
            worst = max(worst, dt)
    total = time.time() - t0
    assert total < 10.0 and worst < 0.05
    assert sum(1 for _ in open(str(log))) == 200


def test_monster_grid_500(tmp_path):
    grid = [[((x // 50) + (y // 50)) % 10 for x in range(500)] for y in range(500)]
    t0 = time.time()
    segs = segment(grid)
    t_seg = time.time() - t0
    assert len(segs) == 100
    t0 = time.time()
    targets = priority_targets([row[:64] for row in grid[:64]])
    t_tar = time.time() - t0
    t0 = time.time()
    h = canonical_hash([row[:32] for row in grid[:32]])
    t_hash = time.time() - t0
    assert t_seg < 20.0 and t_tar < 10.0 and t_hash < 10.0
    assert targets and h
