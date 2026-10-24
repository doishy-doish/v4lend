from concurrent.futures import ThreadPoolExecutor
from agent import run_episode, MyAgent


def run_many(grids, max_turns=6, workers=4, seed=0):
    out = []

    def one(i):
        g = grids[i % len(grids)]
        a = MyAgent(seed=seed + i)
        ok = run_episode(a, g["grid"], g["legal"], max_turns)
        return {"ok": ok, "turns": len(a.turns), "log": a.turns}

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for r in ex.map(one, range(len(grids))):
            out.append(r)
    return out
