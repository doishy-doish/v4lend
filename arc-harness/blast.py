import time

from agent import MyAgent, run_episode
from compact import summarize
from concurrency import run_many
from gate import BuilderGate


def harness_search(configs):
    out = []
    for cfg in configs:
        t0 = time.time()
        agent = MyAgent(seed=cfg.get("seed", 1))
        ok = run_episode(agent, cfg["grid"], cfg["legal"], cfg["max_turns"])
        compacted, _ = summarize(agent.turns, keep=cfg["keep"])
        gate = BuilderGate(threshold=cfg["threshold"], patience=cfg["patience"])
        asked = False
        for _ in range(cfg["patience"]):
            if gate.observe(0.9, False):
                asked = True
                break
        if asked:
            gate.request_builder()
        out.append({
            "max_turns": cfg["max_turns"],
            "keep": cfg["keep"],
            "patience": cfg["patience"],
            "ok": ok,
            "turns": len(agent.turns),
            "kept": len([t for t in compacted if "note" not in t]),
            "builder_asked": asked,
            "builder_requests": gate.requests,
            "seconds": time.time() - t0,
        })
    return out


def compaction_blast(n=2000, keep=20):
    turns = [{"note": "retain-me"}]
    turns += [{"action": "a%d" % (i % 7), "fail": (i % 3 == 0)} for i in range(n)]
    t0 = time.time()
    out, notes = summarize(turns, keep=keep)
    dt = time.time() - t0
    return {
        "n": n,
        "kept_play": len([t for t in out if "note" not in t]),
        "note_kept": out[0] == {"note": "retain-me"},
        "notes": notes,
        "seconds": dt,
    }


def parallel_blast(n=16, workers=4, max_turns=4):
    grids = [{"grid": [[i % 2]], "legal": ["stay"]} for i in range(n)]
    t0 = time.time()
    res = run_many(grids, max_turns=max_turns, workers=workers, seed=11)
    dt = time.time() - t0
    return {
        "n": n,
        "workers": workers,
        "ok": all(r["ok"] for r in res),
        "turns_total": sum(r["turns"] for r in res),
        "unique_actions": sorted({t["action"] for r in res for t in r["log"]}),
        "seconds": dt,
    }
