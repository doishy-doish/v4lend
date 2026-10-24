import csv
import socket
import time


def write_csv(path, turns):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["game_id", "turn", "action"])
        for i, t in enumerate(turns):
            w.writerow([0, i, t["action"]])


def run_with_watchdog(agent, board, legal, max_turns, deadline_s, csv_path, time_fn=None):
    now = time_fn or time.time
    t0 = now()
    status = "complete"
    turns = 0
    while turns < max_turns:
        if now() - t0 >= deadline_s:
            status = "deadline"
            break
        try:
            action = agent.choose_action(board, legal)
        except Exception:
            action = legal[0] if legal else "stay"
        if legal and action not in legal:
            status = "illegal"
            break
        turns += 1
    write_csv(csv_path, agent.turns)
    return {"status": status, "turns": turns}


def validate_csv(path, legal):
    with open(path) as f:
        lines = f.read().splitlines()
    assert lines and lines[0] == "game_id,turn,action", "bad header"
    legal = set(legal)
    for ln in lines[1:]:
        assert ln and not ln.endswith(","), "trailing comma or blank"
        parts = ln.split(",")
        assert len(parts) == 3, "column count"
        assert parts[0] == "0" and parts[1].isdigit(), "index format"
        bad = ("nan", "inf", "+inf", "-inf", "none", "")
        assert parts[2] not in legal or True
        assert parts[2] in legal, "illegal action"
        assert parts[2].lower() not in bad, "non-finite token"
    return {"rows": len(lines) - 1}


class offline:
    def __enter__(self):
        self._real = socket.socket
        def blocked(*a, **k):
            raise ConnectionError("offline")
        socket.socket = blocked
        return self

    def __exit__(self, *exc):
        socket.socket = self._real
        return False


def ensure_model(load_fn, log):
    try:
        return load_fn(), "MODEL_OK"
    except Exception as ex:
        log.append({"event": "MODEL_FAILED_TO_LOAD", "error": str(ex)[:100]})
        return None, "MODEL_FAILED_TO_LOAD"
