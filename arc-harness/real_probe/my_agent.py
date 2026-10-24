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

SK48_CURSOR_COLORS = (6, 14)
SK48_BLOCK_COLORS = (6, 8, 9, 14)
SK48_STRIP_Y = 44
SK48_BOARD_X = 16
SK48_ALIGN_TOL = 2
FLICKER_STEPS = 13
FLICKER_MIN = 10


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


def _canon_masked(grid, mask):
    if mask:
        grid = [[-1 if (y, x) in mask else v for x, v in enumerate(row)] for y, row in enumerate(grid)]
    return _canon(grid)


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


def _sk_cursor(grid):
    best = None
    try:
        for s in _segments(grid):
            if s["color"] not in SK48_CURSOR_COLORS or s["area"] < 4:
                continue
            y1, x1, y2, x2 = s["bbox"]
            if x2 >= SK48_BOARD_X or y1 >= SK48_STRIP_Y:
                continue
            if best is None or s["area"] > best["area"]:
                best = s
    except Exception:
        return None
    if best is None:
        return None
    y1, x1, y2, x2 = best["bbox"]
    return ((y1 + y2) // 2, (x1 + x2) // 2, best["color"])


def _sk_blocks(grid):
    out = {}
    try:
        for s in _segments(grid):
            if s["color"] not in SK48_BLOCK_COLORS or s["area"] < 9:
                continue
            y1, x1, y2, x2 = s["bbox"]
            if x1 <= SK48_BOARD_X or y2 >= SK48_STRIP_Y:
                continue
            if s["color"] not in out or s["area"] > out[s["color"]][2]:
                out[s["color"]] = ((y1 + y2) // 2, (x1 + x2) // 2, s["area"])
    except Exception:
        pass
    return out


def _sk_strip_order(grid):
    seq = []
    try:
        h = len(grid)
        w = len(grid[0]) if h else 0
        for y in range(SK48_STRIP_Y, h):
            row = grid[y]
            x = 0
            while x < w:
                c = row[x]
                x2 = x
                while x2 + 1 < w and row[x2 + 1] == c:
                    x2 += 1
                if c in SK48_BLOCK_COLORS and (x2 - x + 1) >= 3:
                    if not seq or seq[-1] != c:
                        seq.append(c)
                x = x2 + 1
    except Exception:
        pass
    return [c for c in seq if c in SK48_BLOCK_COLORS]


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
        try:
            self._game_id = kwargs.get("game_id", "")
        except Exception:
            self._game_id = ""
        self._sk_move = {}
        self._sk_prev_cy = None
        self._sk_target = None
        self._sk_clicks = 0
        self._flick_cnt = Counter()
        self._flick_n = 0
        self._prev_grid = None
        self._mask = None
        self._best_lc = 0
        self._wins = []
        self._m5phase = "learn"
        self._m5_left = 12
        self._sweep = []
        self._need_reset = False
        self._pending = None
        self._pre_h2 = None
        self._best_click = None
        self._best_score = -1
        self._combo_pairs = []
        self._combo_i = 0
        self._sk_move2 = {}
        self._sk_prev_c = None
        self._probe_disp = {}
        self._probe_pre = None
        self._probe_last = None
        self._probe_done = False
        self._probe_cnt = {}
        self._nav_scores = []
        self._csweep = None
        self._cbest = None
        self._cbest_score = -1
        self._cpending = None
        self._cpre = None
        self._nav_bg = 0
        self._nav_cursor = None
        self._nav_arrows = {}
        self._nav_interact = []
        self._nav_dead = set()
        self._nav_steps = {}

    def is_done(self, frames, latest_frame):
        return latest_frame.state is GameState.WIN

    def stats(self):
        return {"turns": self._turns, "repeats": self._repeats, "unique_frames": len(self._visited),
                "act_use": dict(self._act_use), "frame_keys": self._frame_keys, "debug": self._debug,
                "target_use": {"%d,%d" % k: v for k, v in self._target_use.items()}, "noop": dict(self._noop_count),
                "pairs_tried": len(self._pair_seen), "backtracks": self._backtracks,
                "effective": sorted(self._effective), "snaps": len(self._snaps),
                "sk_target": self._sk_target, "sk_clicks": self._sk_clicks,
                "sk_move": dict(self._sk_move), "wins": len(self._wins), "best_lc": self._best_lc,
                "m5phase": self._m5phase, "best_click": self._best_click,
                "nav_cursor": self._nav_cursor, "nav_arrows": dict(self._nav_arrows),
                "nav_interact": list(self._nav_interact), "cbest": self._cbest,
                "cbest_score": self._cbest_score, "nav_scores": self._nav_scores,
                "sk_move2": {k: [round(float(x), 2), round(float(y), 2)] for k, (x, y) in self._sk_move2.items()}}

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

    def _centroids(self, grid):
        acc = {}
        try:
            for y in range(len(grid)):
                row = grid[y]
                for x in range(len(row)):
                    c = row[x]
                    if c in acc:
                        s = acc[c]
                        s[0] += y
                        s[1] += x
                        s[2] += 1
                    else:
                        acc[c] = [y, x, 1]
        except Exception:
            return {}
        out = {}
        for c, s in acc.items():
            out[c] = (s[0] / s[2], s[1] / s[2], s[2])
        return out

    def _nav_pick(self, grid, h, simple, six, cands):
        names = sorted(set(str(a) for a in simple))
        byname = {}
        for a in simple:
            byname.setdefault(str(a), a)
        if self._m5phase == "learn":
            if not self._sweep and not self._probe_done:
                self._sweep = list(names)
                self._probe_done = True
                try:
                    cent0 = self._centroids(grid)
                    self._nav_bg = max(cent0.keys(), key=lambda c: cent0[c][2])
                except Exception:
                    self._nav_bg = 0
                    cent0 = {}
                self._probe_pre = cent0
                self._probe_disp = {}
                self._probe_last = None
            else:
                if self._probe_last is not None and self._probe_pre:
                    try:
                        cent1 = self._centroids(grid)
                        for c, v1 in cent1.items():
                            if c in self._probe_pre and v1[2] > 2:
                                v0 = self._probe_pre[c]
                                d = abs(v1[0] - v0[0]) + abs(v1[1] - v0[1])
                                if d > 0.05:
                                    ent = self._probe_disp.setdefault(c, {})
                                    ent[self._probe_last] = (v1[0] - v0[0], v1[1] - v0[1])
                                    try:
                                        self._probe_cnt[(c, self._probe_last)] = v1[2]
                                    except Exception:
                                        pass
                    except Exception:
                        pass
                    self._probe_last = None
                if not self._sweep:
                    self._m5phase = "nav"
                    try:
                        best_c, best_d = None, 0.01
                        _scored = []
                        for c, ent in self._probe_disp.items():
                            if c == self._nav_bg or c == 0:
                                continue
                            for _nm, _v in ent.items():
                                _cnt = self._probe_cnt.get((c, _nm), 50)
                                _s = (abs(_v[0]) + abs(_v[1])) / (1.0 + _cnt)
                                _scored.append((_s, c, _nm))
                                if _s > best_d:
                                    best_d, best_c = _s, c
                        _scored.sort(reverse=True)
                        self._nav_scores = [[round(float(s), 4), int(c), str(n)] for s, c, n in _scored[:5]]
                        self._nav_cursor = best_c
                        self._nav_arrows = {}
                        self._nav_steps = {}
                        if best_c is not None:
                            for nm, v in self._probe_disp.get(best_c, {}).items():
                                dy, dx = v
                                if abs(dy) >= abs(dx):
                                    dn = "up" if dy < 0 else "down"
                                else:
                                    dn = "left" if dx < 0 else "right"
                                if dn not in self._nav_arrows:
                                    self._nav_arrows[dn] = nm
                                    self._nav_steps[dn] = (float(dy), float(dx))
                        self._nav_interact = [n for n in names if n not in self._nav_arrows.values()]
                    except Exception:
                        self._nav_cursor = None
                    return self._simple_pick(simple, h)
                nm = self._sweep.pop(0)
                try:
                    self._probe_pre = self._centroids(grid)
                except Exception:
                    self._probe_pre = {}
                self._probe_last = nm
                if nm in byname:
                    self._act_use[nm] += 1
                    self._record_choice(h, (nm, -1, -1))
                    return byname[nm]
            return self._simple_pick(simple, h)
        if self._m5phase == "nav":
            if self._nav_cursor is None or len(self._nav_arrows) < 1:
                return None
            try:
                cent = self._centroids(grid)
            except Exception:
                return None
            if self._nav_cursor not in cent:
                return None
            cy, cx, _cc = cent[self._nav_cursor]
            cands_c = [(c, v) for c, v in cent.items() if c != self._nav_bg and c != 0 and c != self._nav_cursor and v[2] >= 4]
            if not cands_c:
                return None
            cands_c.sort(key=lambda t: t[1][2])
            order = [cands_c[0]] + [t for t in cands_c[1:] if t[0] not in getattr(self, "_nav_dead", set())]
            tc, tv = order[0][0], order[0][1]
            tgt = None
            bestd = None
            for yy in range(max(0, int(cy) - 3), min(len(grid), int(cy) + 4)):
                for xx in range(max(0, int(cx) - 3), min(len(grid[0]), int(cx) + 4)):
                    if grid[yy][xx] == tc:
                        d = abs(yy - cy) + abs(xx - cx)
                        if bestd is None or d < bestd:
                            bestd, tgt = d, (yy, xx)
            if tgt is None:
                cells = [(abs(v[0] - cy) + abs(v[1] - cx), c) for c, v in cands_c]
                cells.sort()
                tc = cells[0][1]
                tv = cent[tc]
                tgt = (int(tv[0]), int(tv[1]))
                bestd = cells[0][0]
            if bestd is not None and bestd < 1.6:
                for nm in sorted(self._nav_interact, key=lambda n: self._act_use[n]):
                    if h is not None and (h, nm, -1, -1) in self._pair_seen:
                        continue
                    if nm in byname:
                        if h is not None:
                            self._pair_seen.add((h, nm, -1, -1))
                        self._act_use[nm] += 1
                        self._sk_clicks += 1
                        self._record_choice(h, (nm, -1, -1))
                        return byname[nm]
                if six:
                    ty, tx = tgt
                    a = six[0]
                    try:
                        a.set_data({"x": tx, "y": ty})
                    except Exception:
                        a = None
                    if a is not None:
                        nm = str(a)
                        if h is None or (h, nm, tx, ty) not in self._pair_seen:
                            if h is not None:
                                self._pair_seen.add((h, nm, tx, ty))
                            self._act_use[nm] += 1
                            self._target_use[(ty, tx)] += 1
                            self._sk_clicks += 1
                            self._sk_target = tc
                            self._record_choice(h, (nm, tx, ty))
                            return a
                if not hasattr(self, "_nav_dead"):
                    self._nav_dead = set()
                self._nav_dead.add(tc)
                return self._simple_pick(simple, h)
            best_a, best_q = None, None
            for dn, nm in self._nav_arrows.items():
                if nm not in byname:
                    continue
                try:
                    dy, dx = self._nav_steps.get(dn, (0.0, 0.0))
                except Exception:
                    dy, dx = 0.0, 0.0
                if dy == 0.0 and dx == 0.0:
                    dy = -1.0 if dn == "up" else (1.0 if dn == "down" else 0.0)
                    dx = -1.0 if dn == "left" else (1.0 if dn == "right" else 0.0)
                q = abs((cy + dy) - tgt[0]) + abs((cx + dx) - tgt[1])
                if best_q is None or q < best_q - 0.01 or (abs(q - best_q) < 0.01 and self._act_use[nm] < self._act_use[best_a]):
                    best_q, best_a = q, nm
            if best_a is not None:
                self._act_use[best_a] += 1
                self._record_choice(h, (best_a, -1, -1))
                return byname[best_a]
            return None
        return None
    def _clickonly_pick(self, grid, h, six):
        if not six:
            return None
        if self._csweep is None:
            pts = []
            for gy in range(0, 64, 16):
                for gx in range(0, 64, 16):
                    pts.append((gx, gy))
            try:
                for t in _targets(grid)[:16]:
                    pts.append((t[1], t[0]))
            except Exception:
                pass
            seen = set()
            uniq = []
            for p in pts:
                if p not in seen:
                    seen.add(p)
                    uniq.append(p)
            self._csweep = uniq
            self._need_reset = True
        if self._cpending is not None:
            try:
                changed = (h != self._cpre)
            except Exception:
                changed = False
            score = (self._best_lc - self._cpending[0]) * 1000 + (1 if changed else 0)
            if score > self._cbest_score:
                self._cbest_score = score
                self._cbest = self._cpending[1]
            self._cpending = None
            self._need_reset = False
        if not self._csweep:
            if self._cbest is None:
                return None
            if self._need_reset:
                self._need_reset = False
                self._expect_reset = True
                return GameAction.RESET
            px, py = self._cbest
            a = six[0]
            try:
                a.set_data({"x": px, "y": py})
            except Exception:
                return None
            nm = str(a)
            self._act_use[nm] += 1
            self._sk_clicks += 1
            self._need_reset = True
            self._record_choice(h, (nm, px, py))
            return a
        if self._need_reset:
            self._need_reset = False
            self._expect_reset = True
            return GameAction.RESET
        px, py = self._csweep.pop(0)
        a = six[0]
        try:
            a.set_data({"x": px, "y": py})
        except Exception:
            self._need_reset = True
            return GameAction.RESET
        nm = str(a)
        if h is not None:
            self._pair_seen.add((h, nm, px, py))
        self._act_use[nm] += 1
        self._cpending = (self._best_lc, (px, py))
        self._cpre = h
        self._need_reset = True
        self._sk_clicks += 1
        self._record_choice(h, (nm, px, py))
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
        if grid is not None and self._mask is None and self._flick_n <= FLICKER_STEPS:
            if self._prev_grid is not None and len(self._prev_grid) == len(grid) and len(grid[0]) == len(self._prev_grid[0]):
                for y in range(len(grid)):
                    for x in range(len(grid[0])):
                        if grid[y][x] != self._prev_grid[y][x]:
                            self._flick_cnt[(y, x)] += 1
            self._flick_n += 1
            try:
                self._prev_grid = [list(row) for row in grid]
            except Exception:
                self._prev_grid = None
            if self._flick_n == FLICKER_STEPS + 1:
                self._mask = set([k for k, v in self._flick_cnt.items() if v >= FLICKER_MIN])
        if grid is not None and self._mask:
            try:
                h = _canon_masked(grid, self._mask)
            except Exception:
                pass
            novel = h is not None and h not in self._visited
        try:
            _lc = latest_frame.levels_completed
            if callable(_lc):
                _lc = _lc()
            _lc = int(_lc)
        except Exception:
            _lc = None
        if _lc is not None and _lc > self._best_lc:
            self._best_lc = _lc
            try:
                self._wins.append((_lc, list(self._prefix)))
            except Exception:
                pass
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
        if grid and (simple or six):
            try:
                if simple:
                    sk_hit = self._nav_pick(grid, h, simple, six, cands)
                else:
                    sk_hit = self._clickonly_pick(grid, h, six)
            except Exception:
                sk_hit = None
            if sk_hit is not None:
                return sk_hit
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
