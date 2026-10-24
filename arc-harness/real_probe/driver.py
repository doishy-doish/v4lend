import argparse
import importlib.util
import json
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

p = argparse.ArgumentParser()
p.add_argument("--game", default="ls20")
p.add_argument("--max-steps", type=int, default=200)
args = p.parse_args()
arc = arc_agi.Arcade(operation_mode=OperationMode.NORMAL)
env = arc.make(args.game)
if env is None:
    print(json.dumps({"game": args.game, "error": "no_env"}))
    raise SystemExit(0)
agent = mod.MyAgent(card_id="probe", game_id=args.game, agent_name="probe", ROOT_URL="http://localhost", record=False, arc_env=env, tags=["probe"])
agent.MAX_ACTIONS = min(agent.MAX_ACTIONS, args.max_steps)
t0 = time.time()
agent.main()
dt = time.time() - t0
final = agent.frames[-1]
out = {"game": args.game, "state": str(final.state), "levels": final.levels_completed, "actions": agent.action_counter, "wall_s": round(dt, 1), "frame_keys": agent._frame_keys, "states": dict(Counter(agent._states_seen))}
print("PROBE_RESULT " + json.dumps(out))
with open("probe-results.json", "w") as f:
    json.dump(out, f)
