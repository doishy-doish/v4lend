import argparse
import importlib.util
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VENDOR = ROOT / "vendor" / "ARC-AGI-3-Agents"
import types
pkg = types.ModuleType("agents")
pkg.__path__ = [str(VENDOR / "agents")]
sys.modules["agents"] = pkg
for _name in ("recorder", "tracing", "agent"):
    _spec = importlib.util.spec_from_file_location("agents." + _name, VENDOR / "agents" / (_name + ".py"))
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules["agents." + _name] = _mod
    _spec.loader.exec_module(_mod)

import arc_agi
from arc_agi import OperationMode

spec = importlib.util.spec_from_file_location("probe_agent", ROOT / "arc-harness" / "real_probe" / "my_agent.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

GBNF = 'root ::= (action | click | "RESET")\naction ::= "ACTION" [1-7]\nclick ::= "CLICK " num " " num\nnum ::= [0-9]+'

SYS = "ARC game player. Reply with exactly one: ACTIONn, CLICK x y, or RESET."


def build_prompt(agent, grid, game, lc, simple, six):
    try:
        s = agent._snap(grid)
    except Exception:
        s = {}
    names = sorted(str(a) for a in simple) + ["CLICK-XY" if six else ""]
    body = {"game": game, "level": lc, "legal": [n for n in names if n], "snap": s}
    return SYS + "\n" + json.dumps(body)[:900]


class ModelAgent(mod.MyAgent):
    def _advisor(self, h, grid, simple, six, cands):
        L = self._llm
        L["asks"] += 1
        try:
            T0 = 0.9 * (0.9 ** (int(getattr(self, "_turns", 0)) // 12)) if L["anneal"] else 0.2
        except Exception:
            T0 = 0.2
        temp = max(0.1, min(1.0, T0))
        prompt = build_prompt(self, grid, getattr(self, "_game_id", "?"), self._best_lc, simple, six)
        texts = []
        try:
            for _ in range(max(1, L["bestof"])):
                kw = {"max_tokens": 16, "temperature": temp}
                if L["grammar"]:
                    try:
                        o = self._llm_obj(prompt, grammar=GBNF, **kw)
                        L["grammar_ok"] = True
                    except Exception:
                        L["grammar_ok"] = False
                        o = self._llm_obj(prompt, **kw)
                else:
                    o = self._llm_obj(prompt, **kw)
                texts.append(o["choices"][0]["text"])
                L["toks"] += o.get("usage", {}).get("total_tokens", 0)
        except Exception as e:
            L["err"] = str(e)[:80]
            return None
        seen = getattr(self, "_pair_seen", set())
        for t in texts:
            a = self._coerce_text(t, h, simple, six, cands, seen)
            if a is not None:
                return a
        L["fallbacks"] += 1
        return None

    def _coerce_text(self, t, h, simple, six, cands, seen):
        t = (t or "").upper()
        m = re.search(r"ACTION\s*([1-7])", t)
        if m:
            nm = "GameAction.ACTION" + m.group(1)
            for a in cands:
                if str(a) == nm:
                    try:
                        self._act_use[nm] += 1
                        self._record_choice(h, (nm, -1, -1))
                    except Exception:
                        pass
                    return a
        m = re.search(r"CLICK\s+(\d{1,2})\s+(\d{1,2})", t)
        if m and six:
            x, y = min(63, int(m.group(1))), min(63, int(m.group(2)))
            if h is None or (h, "CLICK", x, y) not in seen:
                a = six[0]
                try:
                    a.set_data({"x": x, "y": y})
                except Exception:
                    return None
                try:
                    nm = str(a)
                    self._act_use[nm] += 1
                    self._sk_clicks += 1
                    self._record_choice(h, (nm, x, y))
                except Exception:
                    pass
                return a
        if "RESET" in t:
            try:
                self._record_choice(h, ("GameAction.RESET", -1, -1))
            except Exception:
                pass
            return mod.GameAction.RESET
        return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--game", default="vc33")
    p.add_argument("--max-steps", type=int, default=30)
    p.add_argument("--model", default="model.gguf")
    p.add_argument("--bestof", type=int, default=1)
    p.add_argument("--grammar", default="on")
    p.add_argument("--anneal", default="on")
    args = p.parse_args()
    from llama_cpp import Llama
    t0 = time.time()
    llm = Llama(model_path=args.model, n_ctx=1024, verbose=False)
    load_s = round(time.time() - t0, 1)
    arc = arc_agi.Arcade(operation_mode=OperationMode.NORMAL)
    env = arc.make(args.game)
    if env is None:
        print(json.dumps({"game": args.game, "error": "no_env"}))
        raise SystemExit(0)
    agent = ModelAgent(card_id="probe", game_id=args.game, agent_name="probe", ROOT_URL="http://localhost", record=False, arc_env=env, tags=["probe"])
    agent.MAX_ACTIONS = min(agent.MAX_ACTIONS, args.max_steps)
    agent._llm_obj = llm
    agent._llm = {"asks": 0, "fallbacks": 0, "toks": 0, "grammar": args.grammar == "on", "grammar_ok": None, "anneal": args.anneal == "on", "bestof": max(1, int(args.bestof)), "err": None}
    t1 = time.time()
    agent.main()
    dt = round(time.time() - t1, 1)
    L = agent._llm
    L["load_s"] = load_s
    L["wall_s"] = dt
    L["tok_per_s"] = round(L["toks"] / max(dt, 0.01), 2)
    final = agent.frames[-1]
    out = {"game": args.game, "state": str(final.state), "levels": final.levels_completed, "actions": agent.action_counter, "wall_s": dt, "frame_keys": agent._frame_keys, "harness": agent.stats(), "llm": L}
    print("MODEL_RESULT " + json.dumps({k: out[k] for k in ("game", "levels", "actions", "wall_s", "llm")}))
    with open("probe-results.json", "w") as f:
        json.dump({k: v for k, v in out.items() if k != "shots"}, f)
    with open("model-stats.json", "w") as f:
        json.dump(out, f)


main()
