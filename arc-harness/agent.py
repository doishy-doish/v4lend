import json
import random
import time


class ModuleStore:
    def __init__(self):
        self.modules = {}
        self.log = []

    def save_module(self, name, code, tests):
        try:
            ns = {}
            exec(compile(code, name, "exec"), ns)
        except Exception as e:
            self.log.append({"event": "compile_fail", "name": name, "error": str(e)[:200]})
            return False
        for t in tests:
            try:
                if not t(ns):
                    self.log.append({"event": "regression_fail", "name": name})
                    return False
            except Exception as e:
                self.log.append({"event": "test_error", "name": name, "error": str(e)[:200]})
                return False
        self.modules[name] = code
        self.log.append({"event": "saved", "name": name})
        return True

    def dump_log(self, path):
        with open(path, "w") as f:
            for row in self.log:
                f.write(json.dumps(row) + "\n")


class MyAgent:
    def __init__(self, store=None, seed=0):
        self.store = store or ModuleStore()
        self.rng = random.Random(seed)
        self.turns = []

    def choose_action(self, board, legal_actions):
        t0 = time.time()
        actions = list(legal_actions)
        action = self.rng.choice(actions)
        w = len(board[0]) if board else 0
        self.turns.append({"h": len(board), "w": w, "n_legal": len(actions), "action": action, "ms": int((time.time() - t0) * 1000)})
        return action

    def dump_turns(self, path):
        with open(path, "w") as f:
            for row in self.turns:
                f.write(json.dumps(row) + "\n")


def run_episode(agent, board, legal_actions, max_turns=10):
    for _ in range(max_turns):
        if agent.choose_action(board, legal_actions) not in legal_actions:
            return False
    return True


def write_actions_csv(turns, path):
    with open(path, "w") as f:
        f.write("game_id,turn,action\n")
        for i, t in enumerate(turns):
            f.write("%d,%d,%s\n" % (0, i, t["action"]))
