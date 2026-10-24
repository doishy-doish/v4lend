import json
import time

from blast import harness_search, compaction_blast, parallel_blast

GRIDS = [
    {"grid": [[0, 1, 0], [1, 1, 1], [0, 1, 0]], "legal": ["up", "down", "left", "right"]},
    {"grid": [[2, 2], [2, 0]], "legal": ["up", "down"]},
]


def test_blast_radius_all():
    t0 = time.time()
    configs = []
    for gd in GRIDS:
        for max_turns in (2, 4):
            for keep in (4, 8):
                for patience in (1, 2):
                    configs.append({
                        "grid": gd["grid"], "legal": gd["legal"],
                        "max_turns": max_turns, "keep": keep,
                        "threshold": 0.5, "patience": patience, "seed": 3,
                    })
    hs = harness_search(configs)
    assert len(hs) == 16 and all(h["ok"] for h in hs)
    assert all(h["turns"] <= 4 for h in hs)
    assert all(h["builder_asked"] and h["builder_requests"] == 1 for h in hs)
    cb = compaction_blast()
    assert cb["kept_play"] == 25 and cb["note_kept"]
    assert cb["notes"]["n_dropped"] == 1975 and cb["notes"]["n_fails"] == 658
    pb = parallel_blast()
    assert pb["ok"] and pb["turns_total"] == 64
    assert pb["unique_actions"] == ["stay"]
    metrics = {
        "harness_search": hs,
        "compaction": cb,
        "parallel": pb,
        "seconds_total": time.time() - t0,
    }
    with open("blast-metrics.json", "w") as f:
        json.dump(metrics, f, indent=2)
    assert metrics["seconds_total"] < 30
    print("BLAST_OK configs=16 compacted=25 parallel_turns=64")
