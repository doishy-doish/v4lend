import random
from collections import Counter

from arcengine import FrameData, GameAction, GameState
from agents.agent import Agent

SALIENT = set(range(6, 16))


def _grid(latest_frame):
    try:
        g = latest_frame.frame() if callable(getattr(latest_frame, "frame", None)) else latest_frame.frame
    except Exception:
        return None
    try:
        if hasattr(g, "tolist"):
            g = g.tolist()
        g = [list(map(int, row)) for row in g]
        if not g or not g[0]:
            return None
        return g
    except Exception:
        return None


def _segments(grid):
    h = len(grid)
    w = len(grid[0]) if h else 0
    seen = [[False] * w for _ in range(h)]
    segs = []
    for y in range(h):
        for x in range(w):
            if seen[y][x]:
                continue
            c = grid[y][x]
            stack = [(x, y)]
            seen[y][x] = True
            y1 = y2 = y
            x1 = x2 = x
            area = 0
            while stack:
                cx, cy = stack.pop()
                area += 1
                y1 = min(y1, cy)
                y2 = max(y2, cy)
                x1 = min(x1, cx)
                x2 = max(x2, cx)
                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                    if 0 <= nx < w and 0 <= ny < h and not seen[ny][nx] and grid[ny][nx] == c:
                        seen[ny][nx] = True
                        stack.append((nx, ny))
            segs.append({"color": c, "bbox": (y1, x1, y2, x2), "area": area})
    return segs


def _targets(grid):
    def key(s):
        y1, x1, y2, x2 = s["bbox"]
        w = x2 - x1 + 1
        hh = y2 - y1 + 1
        med = 2 <= w <= 32 and 2 <= hh <= 32
        sal = s["color"] in SALIENT
        return (0 if (sal and med) else 1 if med else 2 if sal else 3, -s["area"])
    segs = sorted(_segments(grid), key=key)
    out = []
    for s in segs:
        if s["area"] < 2:
            continue
        y1, x1, y2, x2 = s["bbox"]
        out.append(((y1 + y2) // 2, (x1 + x2) // 2))
        if len(out) >= 32:
            break
    return out


def _canon(grid):
    def rot(g):
        return [list(r) for r in zip(*g[::-1])]
    def flip(g):
        return [row[::-1] for row in g]
    best = None
    g = grid
    for _ in range(4):
        for t in (g, flip(g)):
            k = tuple(tuple(r) for r in t)
            if best is None or k < best:
                best = k
        g = rot(g)
    return best


def _coerce(a):
    if isinstance(a, GameAction):
        return a
    try:
        return GameAction(a)
    except Exception:
        return None


def _complex(a):
    try:
        return bool(a.is_complex())
    except Exception:
        return False


class MyAgent(Agent):
    MAX_ACTIONS = 200

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._frame_keys = None
        self._visited = Counter()
        self._act_use = Counter()
        self._repeats = 0
        self._turns = 0
        self._debug = {}

    def is_done(self, frames, latest_frame):
        return latest_frame.state is GameState.WIN

    def stats(self):
        return {"turns": self._turns, "repeats": self._repeats, "unique_frames": len(self._visited), "act_use": dict(self._act_use), "frame_keys": self._frame_keys, "debug": self._debug}

    def choose_action(self, frames, latest_frame):
        if self._frame_keys is None:
            self._frame_keys = sorted([x for x in dir(latest_frame) if not x.startswith("_")])
        if latest_frame.state in (GameState.NOT_PLAYED, GameState.GAME_OVER):
            return GameAction.RESET
        try:
            raw = list(latest_frame.available_actions) if latest_frame.available_actions is not None else [a for a in GameAction if a is not GameAction.RESET]
            avail = [c for c in (_coerce(a) for a in raw) if c is not None]
        except Exception:
            avail = [a for a in GameAction if a is not GameAction.RESET]
        grid = _grid(latest_frame)
        if not self._debug:
            try:
                raw_dbg = list(latest_frame.available_actions) if latest_frame.available_actions is not None else None
            except Exception as ex:
                raw_dbg = "ERR:" + str(ex)[:80]
            try:
                fobj = latest_frame.frame() if callable(getattr(latest_frame, "frame", None)) else latest_frame.frame
                ftype = type(fobj).__name__
                fshape = getattr(fobj, "shape", None)
                fshape = str(fshape) if fshape is not None else (str(len(fobj)) + "x" + str(len(fobj[0])) if fobj else None)
            except Exception as ex:
                ftype = "ERR:" + str(ex)[:80]
                fshape = None
            self._debug = {"avail": str(raw_dbg)[:300], "frame_type": ftype, "frame_shape": fshape}
        h = None
        try:
            h = _canon(grid) if grid else None
        except Exception:
            h = None
        if h is not None:
            if h in self._visited:
                self._repeats += 1
            self._visited[h] += 1
        self._turns += 1
        cands = [a for a in avail if a is not GameAction.RESET]
        if grid:
            six = [a for a in cands if _complex(a)]
            try:
                tg = _targets(grid)
            except Exception:
                tg = []
            if six and tg:
                y, x = tg[0]
                a = six[0]
                try:
                    a.set_data({"x": x, "y": y})
                    self._act_use["ACTION6"] += 1
                    return a
                except Exception:
                    pass
        simple = [a for a in cands if not _complex(a)] or cands
        if not simple:
            return GameAction.RESET
        best = min([str(a) for a in simple], key=lambda s: self._act_use[s])
        pick = [a for a in simple if str(a) == best]
        a = random.choice(pick)
        self._act_use[str(a)] += 1
        return a
