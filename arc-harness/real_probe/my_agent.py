import random
from collections import Counter

from arcengine import FrameData, GameAction, GameState

try:
    from agents.agent import Agent
except Exception:
    Agent = object

SALIENT = set(range(6, 16))

STALL_FORCE_SIMPLE = 8
STALL_ROTATE = 3
BACKTRACK_STALL = 12
MAX_BACKTRACKS = 3
MAX_REPLAY = 60
BACKTRACK_BEFORE_TURN = 150


def _grid(latest_frame):
    try:
        g = latest_frame.frame() if callable(getattr(latest_frame, "frame", None)) else latest_frame.frame
    except Exception:
        return None
    try:
        if hasattr(g, "tolist"):
            g = g.tolist()
        if g and isinstance(g, list) and g and isinstance(g[0], list) and g[0] and isinstance(g[0][0], list):
            g = g[0]
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
        if len(out) >= 64:
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
        byval = {m.value: m for m in GameAction}
    except Exception:
        byval = {}
    if a in byval:
        return byval[a]
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
        try:
            super().__init__(*args, **kwargs)
        except Exception:
            pass
        self._frame_keys = None
        self._visited = Counter()
        self._act_use = Counter()
        self._repeats = 0
        self._turns = 0
        self._debug = {}
        self._pair_seen = set()
        self._target_use = Counter()
        self._noop_count = Counter()
        self._simple_idx = 0
        self._last_h = None
        self._stall = 0
        self._prev_h = None
        self._prev_sig = None
        self._since_novel = 0
        self._effective = set()
        self._prefix = []
        self._snaps = []
        self._replay = None
        self._backtracks = 0
        self._expect_reset = False

    def is_done(self, frames, latest_frame):
        return latest_frame.state is GameState.WIN

    def stats(self):
        return {"turns": self._turns, "repeats": self._repeats, "unique_frames": len(self._visited),
                "act_use": dict(self._act_use), "frame_keys": self._frame_keys, "debug": self._debug,
                "target_use": {"%d,%d" % k: v for k, v in self._target_use.items()}, "noop": dict(self._noop_count),
                "pairs_tried": len(self._pair_seen), "backtracks": self._backtracks,
                "effective": sorted(self._effective), "snaps": len(self._snaps)}

    def _record_choice(self, h, sig):
        self._prev_h = h
        self._prev_sig = sig
        self._prefix.append(sig)

    def _simple_pick(self, simple, h):
        if not simple:
            return GameAction.RESET
        byname = {}
        for a in simple:
            byname.setdefault(str(a), a)
        eff = sorted([n for n in byname if n in self._effective])
        rest = sorted([n for n in byname if n not in self._effective])
        order = eff + rest or sorted(byname)
        name = order[self._simple_idx % len(order)]
        self._simple_idx += 1
        a = byname[name]
        self._act_use[name] += 1
        self._record_choice(h, (name, -1, -1))
        return a

    def _replay_pick(self, cands, h):
        while self._replay:
            nm, x, y = self._replay[0]
            hit = None
            for a in cands:
                if str(a) != nm:
                    continue
                if x == -1 and not _complex(a):
                    hit = a
                    break
                if x != -1 and _complex(a):
                    try:
                        a.set_data({"x": x, "y": y})
                    except Exception:
                        continue
                    hit = a
                    break
            if hit is None:
                self._replay = None
                return None
            self._replay.pop(0)
            self._act_use[nm] += 1
            if x != -1:
                self._target_use[(y, x)] += 1
                if h is not None:
                    self._pair_seen.add((h, nm, x, y))
            self._record_choice(h, (nm, x, y))
            return hit
        self._replay = None
        return None

    def choose_action(self, frames, latest_frame):
        if self._frame_keys is None:
            try:
                self._frame_keys = sorted([x for x in dir(latest_frame) if not x.startswith("_")])
            except Exception:
                self._frame_keys = []
        if latest_frame.state in (GameState.NOT_PLAYED, GameState.GAME_OVER):
            self._prefix = []
            self._last_h = None
            self._stall = 0
            self._since_novel = 0
            if not self._expect_reset:
                self._replay = None
            self._expect_reset = False
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
        novel = h is not None and h not in self._visited
        if h is not None:
            if not novel:
                self._repeats += 1
                self._since_novel += 1
            else:
                self._since_novel = 0
            self._visited[h] += 1
        if novel:
            if self._prev_sig is not None:
                self._effective.add(self._prev_sig[0])
            if len(self._prefix) <= MAX_REPLAY:
                self._snaps.append((list(self._prefix), h))
                self._snaps.sort(key=lambda s: len(s[0]))
                self._snaps = self._snaps[:5]
        if self._prev_sig is not None and self._prev_h is not None and h is not None:
            if h == self._prev_h:
                self._noop_count[self._prev_sig[0]] += 1
        if h is not None:
            if h == self._last_h:
                self._stall += 1
            else:
                self._stall = 0
            self._last_h = h
        self._turns += 1
        cands = [a for a in avail if a is not GameAction.RESET]
        simple = [a for a in cands if not _complex(a)]
        six = [a for a in cands if _complex(a)]
        if self._replay:
            hit = self._replay_pick(cands, h)
            if hit is not None:
                return hit
        if ((self._stall >= BACKTRACK_STALL or self._since_novel >= 25) and self._backtracks < MAX_BACKTRACKS
                and self._turns <= BACKTRACK_BEFORE_TURN and self._snaps):
            self._replay = list(self._snaps[0][0])
            if self._replay:
                self._backtracks += 1
                self._prefix = []
                self._last_h = None
                self._stall = 0
                self._since_novel = 0
                self._expect_reset = True
                return GameAction.RESET
            self._replay = None
        if self._stall >= STALL_FORCE_SIMPLE and simple:
            return self._simple_pick(simple, h)
        if grid and six:
            try:
                tg = _targets(grid)
            except Exception:
                tg = []
            if tg:
                if self._stall >= STALL_ROTATE:
                    tg = tg[1:] + tg[:1]
                scored = []
                for (y, x) in tg:
                    tu = self._target_use[(y, x)]
                    for a in six:
                        nm = str(a)
                        if h is not None and (h, nm, x, y) in self._pair_seen:
                            continue
                        eff = 0 if nm in self._effective else 1
                        scored.append((eff, tu + self._noop_count.get(nm, 0) * 10, self._act_use[nm], (y, x), a))
                if scored:
                    scored.sort(key=lambda t: (t[0], t[1], t[2]))
                    _, _, _, (y, x), a = scored[0]
                    try:
                        a.set_data({"x": x, "y": y})
                        nm = str(a)
                        if h is not None:
                            self._pair_seen.add((h, nm, x, y))
                        self._act_use[nm] += 1
                        self._target_use[(y, x)] += 1
                        self._record_choice(h, (nm, x, y))
                        return a
                    except Exception:
                        pass
        if simple:
            return self._simple_pick(simple, h)
        if cands:
            a = cands[0]
            self._act_use[str(a)] += 1
            self._record_choice(h, (str(a), -1, -1))
            return a
        return GameAction.RESET
