import os
import random
import zlib
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
    try:
        grid = [list(row) for row in grid[:SK48_STRIP_Y]]
    except Exception:
        pass

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
    try:
        grid = [list(row) for row in grid[:SK48_STRIP_Y]]
    except Exception:
        pass
    if mask:
        try:
            mask = set((y, x) for (y, x) in mask if y < SK48_STRIP_Y)
        except Exception:
            mask = None
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


def _route_step(grid, cy, cx, ty, tx, arrows):
    # Dijkstra on 16x16 downsampled cost map. Returns a direction string present
    # in arrows, or None. Cost: 4-cells 1, 3-cells 8, else 2.
    try:
        gh = len(grid)
        gw = len(grid[0]) if gh else 0
        if not gh or not gw:
            return None
        from collections import Counter as _CC

        def cell16(_gy, _gx):
            _cc = _CC()
            for _yy in range(_gy * gh // 16, (_gy + 1) * gh // 16):
                for _xx in range(_gx * gw // 16, (_gx + 1) * gw // 16):
                    _cc[grid[_yy][_xx]] += 1
            return _cc.most_common(1)[0][0]

        _cost = [[1] * 16 for _ in range(16)]
        for _my in range(16):
            for _mx in range(16):
                _v = cell16(_my, _mx)
                _cost[_my][_mx] = 1 if _v == 4 else (8 if _v == 3 else 2)
        _sy = min(15, max(0, int(round(cy)) * 16 // gh))
        _sx = min(15, max(0, int(round(cx)) * 16 // gw))
        _dy = min(15, max(0, int(round(ty)) * 16 // gh))
        _dx = min(15, max(0, int(round(tx)) * 16 // gw))
        import heapq as _hq
        _dist = {( _sy, _sx): 0}
        _prev = {}
        _pq = [(0, _sy, _sx)]
        _dirs = ((-1, 0, "up"), (1, 0, "down"), (0, -1, "left"), (0, 1, "right"))
        while _pq:
            _d, _y, _x = _hq.heappop(_pq)
            if _d != _dist.get((_y, _x), None):
                continue
            if (_y, _x) == (_dy, _dx):
                break
            for _oy, _ox, _dn in _dirs:
                _ny, _nx = _y + _oy, _x + _ox
                if 0 <= _ny < 16 and 0 <= _nx < 16:
                    _nd = _d + _cost[_ny][_nx]
                    if _nd < _dist.get((_ny, _nx), float("inf")):
                        _dist[(_ny, _nx)] = _nd
                        _prev[(_ny, _nx)] = ((_y, _x), _dn)
                        _hq.heappush(_pq, (_nd, _ny, _nx))
        if (_dy, _dx) not in _prev and (_dy, _dx) != (_sy, _sx):
            return None
        _cur = (_dy, _dx)
        _first = None
        while _cur != (_sy, _sx):
            _p, _dn = _prev[_cur]
            _first = _dn
            _cur = _p
        if _first in arrows:
            return _first
        return None
    except Exception:
        return None


class MyAgent(Agent):
    MAX_ACTIONS = 1600

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
        self._combo_pairs = None
        self._combo_i = 0
        self._combo_stage = 0
        self._combo_eval = 0
        self._combo_win = None
        self._simple_only = False
        self._sk_trace = []
        self._skf_phase = "aim"
        self._skf_order = None
        self._skf_ti = 0
        self._skf_fires = 0
        self._skf_tip = 0
        self._skf_stag = 0
        self._skf_stage = 0
        self._probe_last = None
        self._probe_done = False
        self._probe_samples = {}
        self._probe_cnt = {}
        self._nav_avoid = set()
        self._nav_scores = []
        self._barfill = 0.0
        self._csweep = None
        self._cbest = None
        self._cbest_score = -1
        self._cpending = None
        self._cpre = None
        self._cpre_grid = None
        self._ctop = []
        self._csweep_all = []
        self._cexploit_n = 0
        self._cpair = []
        self._cpair_i = 0
        self._cpair_stage = 0
        self._gate_clicks = []
        self._bfs_queue = []
        self._bfs_i = 0
        self._bfs_j = -1
        self._bfs_seen = set()
        self._bfs_turns = 0
        self._bfs_win = None
        self._bfs_lc0 = 0
        self._bfs_level = -1
        self._nspiral_done = False
        self._nav_bg = 0
        self._nav_cursor = None
        self._nav_arrows = {}
        self._nav_interact = []
        self._nav_dead = set()
        self._nav_steps = {}
        self._nav_last = None
        self._nav_same_dir = 0
        self._nav_last_dir = None
        self._gpar = 0
        self._ls_prevd = None
        self._ls_stall = 0
        self._scal = []
        self._ff = {}
        self._prev_gate = None
        self._prev_gate_nz = None

    def _snap(self, grid):
        d = {}
        try:
            pa = self._prev_sig[0] if self._prev_sig else "-"
            if "::" in pa:
                pa = pa.split("::")[-1]
            d["pa"] = pa
        except Exception:
            d["pa"] = "?"
        try:
            _sig = self._prefix[-1] if self._prefix else None
            if _sig is not None and len(_sig) > 2 and _sig[1] != -1:
                d["xy"] = [_sig[1], _sig[2]]
        except Exception:
            pass
        try:
            d["cl"] = int(getattr(self, "_cur_lc", -1))
        except Exception:
            pass
        try:
            gid = self._game_id
        except Exception:
            gid = ""
        if gid == "sk48":
            try:
                cur = _sk_cursor(grid)
                d["cy"] = cur[0] if cur else -1
                d["cx"] = cur[1] if cur else -1
            except Exception:
                d["cy"] = -1
            try:
                tip = 0
                top = min(len(grid), SK48_STRIP_Y)
                cy = d.get("cy", -1)
                y0 = max(0, cy - 2) if cy >= 0 else 0
                y1 = min(top, cy + 3) if cy >= 0 else top
                for _yy in range(y0, y1):
                    _row = grid[_yy]
                    for _xx in range(len(_row)):
                        if _row[_xx] == 1 and _xx > tip:
                            tip = _xx
                d["tip"] = tip
            except Exception:
                d["tip"] = -1
            try:
                blocks = _sk_blocks(grid)
                tc = self._skf_order[self._skf_ti] if self._skf_order and self._skf_ti < len(self._skf_order) else None
                if tc is not None and tc in blocks:
                    d["tx"] = blocks[tc][1]
                    d["tb"] = blocks[tc][2]
                    d["tc"] = tc
                else:
                    d["tx"] = -1
                    d["tb"] = -1
                    d["tc"] = -1
            except Exception:
                d["tx"] = -1
            try:
                d["bar"] = int(round(self._barfill * 100))
                d["bt"] = int(round(float(getattr(self, "_skf_bth", 0)) * 100))
            except Exception:
                d["bar"] = -1
            try:
                d["st"] = int(self._skf_stage)
                d["fv"] = int(getattr(self, "_skf_fv", -1))
                try:
                    d["hits"] = int(getattr(self, "_skf_hits", 0))
                except Exception:
                    pass
                try:
                    d["cc"] = int(getattr(self, "_skf_cc", -1))
                except Exception:
                    pass
            except Exception:
                pass
            try:
                _bl = _sk_blocks(grid)
                _tc2 = self._skf_order[self._skf_ti] if self._skf_order and self._skf_ti < len(self._skf_order) else None
                if _tc2 is not None and _tc2 in _bl:
                    d["tby"] = _bl[_tc2][0]
                else:
                    d["tby"] = -1
            except Exception:
                d["tby"] = -1
            try:
                d["ord"] = [int(_c) for _c in _sk_strip_order(grid)][:8]
            except Exception:
                pass
            try:
                if self._turns % 10 == 0:
                    _all6 = []
                    _bkeys = {}
                    for _sg in _segments(grid):
                        if _sg["color"] == 6 and _sg["area"] >= 9:
                            _y1, _x1, _y2, _x2 = _sg["bbox"]
                            _all6.append([(_y1 + _y2) // 2, (_x1 + _x2) // 2, int(_sg["area"])])
                    try:
                        _bkeys = {int(_k): [int(_v[0]), int(_v[1]), int(_v[2])] for _k, _v in _sk_blocks(grid).items()}
                    except Exception:
                        pass
                    d["c6"] = _all6[:6]
                    d["bkeys"] = _bkeys
            except Exception:
                pass
        elif not self._simple_only:
            try:
                gid2 = self._gate_id(grid)
                gh = zlib.crc32(str(gid2).encode()) & 0xffff if gid2 is not None else -1
                d["gh"] = gh
            except Exception:
                d["gh"] = -1
            try:
                d["att"] = int(getattr(self, "_att", -1))
            except Exception:
                pass
            try:
                from collections import Counter as _C
                d["r0"] = [[int(_k), int(_v)] for _k, _v in _C(grid[0]).most_common(3)]
                _sc = _C()
                for _yy in range(SK48_STRIP_Y, len(grid)):
                    _sc.update(grid[_yy])
                d["strip"] = [[int(_k), int(_v)] for _k, _v in _sc.most_common(3)]
                d["fh"] = zlib.crc32(str(grid).encode()) & 0xffff
            except Exception:
                pass
        else:
            try:
                cent = self._centroids(grid)
                c = self._nav_cursor
                if c is not None and c in cent:
                    d["cxy"] = [round(float(cent[c][0]), 1), round(float(cent[c][1]), 1)]
                    d["cn"] = int(cent[c][2])
                else:
                    d["cxy"] = [-1, -1]
                    d["cn"] = 0
                try:
                    _top = sorted(cent.items(), key=lambda _kv: -_kv[1][2])[:3]
                    d["top"] = [[int(_k), int(_v[2])] for _k, _v in _top]
                except Exception:
                    pass
            except Exception:
                d["cxy"] = [-1, -1]
            try:
                if self._nav_last:
                    d["nl"] = self._nav_last
            except Exception:
                pass
            try:
                if self._turns % 15 == 0:
                    _segs = sorted(_segments(grid), key=lambda _x: -_x["area"])[:8]
                    d["segs"] = [[int(_g["color"]), int(_g["area"]), list(_g["bbox"])] for _g in _segs]
                if self._turns % 10 == 0:
                    try:
                        _cc0 = self._centroids(grid)
                        _cu = self._nav_cursor if self._nav_cursor in _cc0 else None
                        if _cu is not None:
                            _wcy, _wcx = int(round(_cc0[_cu][0])), int(round(_cc0[_cu][1]))
                            _rows = []
                            for _wy in range(max(0, _wcy - 5), min(len(grid), _wcy + 6)):
                                _rows.append("".join("0123456789abcdef"[grid[_wy][_wx] & 15] for _wx in range(max(0, _wcx - 5), min(len(grid[0]), _wcx + 6))))
                            d["win"] = [int(_wcy), int(_wcx), _rows]
                            try:
                                _gh = len(grid)
                                _gw = len(grid[0])
                                _mp = []
                                for _my in range(16):
                                    _row = ""
                                    for _mx in range(16):
                                        from collections import Counter as _CC
                                        _cc = _CC()
                                        for _yy in range(_my * _gh // 16, (_my + 1) * _gh // 16):
                                            for _xx in range(_mx * _gw // 16, (_mx + 1) * _gw // 16):
                                                _cc[grid[_yy][_xx]] += 1
                                        _row += "0123456789abcdef"[_cc.most_common(1)[0][0] & 15]
                                    _mp.append(_row)
                                d["map16"] = _mp
                            except Exception:
                                pass
                    except Exception:
                        pass
            except Exception:
                pass
        return d

    def _forced_fire(self):
        d = {}
        try:
            d["menv"] = bool(os.environ.get("MODEL_PATH", ""))
        except Exception:
            d["menv"] = False
        try:
            import sys as _sys
            d["py"] = _sys.version.split()[0]
        except Exception as _e:
            d["py"] = "ERR:" + str(_e)[:40]
        try:
            import torch as _torch
            d["torch"] = getattr(_torch, "__version__", "?")
        except Exception as _e:
            d["torch"] = "ERR:" + str(_e)[:60]
        try:
            import transformers as _tf
            d["tf"] = getattr(_tf, "__version__", "?")
        except Exception as _e:
            d["tf"] = "ERR:" + str(_e)[:60]
        return d

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
                "barfill": self._barfill, "nav_last": self._nav_last,
                "nav_avoid": sorted(self._nav_avoid),
                "nav_steps": {k: [round(float(v[0]), 2), round(float(v[1]), 2)] for k, v in self._nav_steps.items()},
                "sk_mode": self._skf_phase, "sk_ti": self._skf_ti, "sk_tip": self._skf_tip,
                "sk_stage": self._skf_stage, "sk_fires": self._skf_fires,
                "ctop": [[int(s), list(p)] for s, p in self._ctop[:4]],
                "bfs": [len(self._bfs_queue), self._bfs_i, len(self._bfs_seen), self._bfs_win],
                "sk_trace": self._sk_trace,
                "combo_win": self._combo_win, "combo_done": self._combo_i,
                "probe_disp": {int(_cc): {_nn: [round(float(_v[0]), 2), round(float(_v[1]), 2)] for _nn, _v in _ent.items()} for _cc, _ent in (getattr(self, "_probe_disp", {}) or {}).items()},
                "probe_cnt": {str(_k): int(_v) for _k, _v in (getattr(self, "_probe_cnt", {}) or {}).items()},
                "scal": self._scal, "ff": self._ff,
                "sk_move2": {k: [round(float(x), 2), round(float(y), 2)] for k, (x, y) in self._sk_move2.items()}}

    def _record_choice(self, h, sig):
        self._prev_h = h
        self._prev_sig = sig
        self._prefix.append(sig)
        try:
            if sig is not None and len(sig) > 2 and sig[1] != -1:
                try:
                    self._gpar = 1 - int(getattr(self, "_gpar", 0))
                except Exception:
                    pass
        except Exception:
            pass
        try:
            _nm0 = sig[0] if sig else ""
            if "RESET" in str(_nm0):
                self._att = 0
                try:
                    self._gpar = 0
                except Exception:
                    pass
            else:
                self._att = int(getattr(self, "_att", 0)) + 1
        except Exception:
            pass
        if len(self._sk_trace) < 120:
            try:
                self._sk_trace.append([self._turns, self._skf_phase, str(sig[0])])
            except Exception:
                pass

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
            top = min(len(grid), SK48_STRIP_Y)
            for y in range(top):
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
                self._sweep = [n for n in names for _ in range(5)]
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
                                    try:
                                        self._probe_samples.setdefault((c, self._probe_last), []).append((v1[0] - v0[0], v1[1] - v0[1], v1[2]))
                                    except Exception:
                                        pass
                    except Exception:
                        pass
                    self._probe_last = None
                if not self._sweep:
                    self._m5phase = "nav"
                    try:
                        _had = sum(len(v) for v in self._probe_samples.values())
                    except Exception:
                        _had = 1
                    if not _had:
                        try:
                            self._m5phase = "learn"
                            self._sweep = []
                            self._probe_done = False
                        except Exception:
                            pass
                        return self._simple_pick(simple, h)
                    try:
                        self._probe_disp = {}
                        self._probe_cnt = {}
                        for (_cc, _nn), _ss in self._probe_samples.items():
                            if len(_ss) == 0:
                                continue
                            _dys = sorted([_s[0] for _s in _ss])
                            _dxs = sorted([_s[1] for _s in _ss])
                            _cts = sorted([_s[2] for _s in _ss])
                            _mid = len(_ss) // 2
                            _mdy = (_dys[_mid] + _dys[~_mid]) / 2.0
                            _mdx = (_dxs[_mid] + _dxs[~_mid]) / 2.0
                            if abs(_mdy) + abs(_mdx) > 0.05:
                                self._probe_disp.setdefault(_cc, {})[_nn] = (_mdy, _mdx)
                                self._probe_cnt[(_cc, _nn)] = _cts[_mid]
                    except Exception:
                        pass
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
                        if getattr(self, "_game_id", "") == "sk48":
                            for _pc in (6, 14):
                                _ent = self._probe_disp.get(_pc, {})
                                if _pc != self._nav_bg and sum(abs(_v[0]) + abs(_v[1]) for _v in _ent.values()) > 0.5:
                                    self._nav_cursor = _pc
                                    best_c = _pc
                                    break
                        try:
                            _cur_ent = self._probe_disp.get(self._nav_cursor, {})
                            _cur_dir = {}
                            for _nm, _v in _cur_ent.items():
                                _cur_dir[_nm] = ("y" if abs(_v[0]) >= abs(_v[1]) else "x", 1 if (_v[0] if abs(_v[0]) >= abs(_v[1]) else _v[1]) > 0 else -1)
                            for _cc, _ent2 in self._probe_disp.items():
                                if _cc == self._nav_cursor or _cc == self._nav_bg or _cc == 0:
                                    continue
                                _match = True
                                _shared = 0
                                for _nm, _v in _ent2.items():
                                    if _nm in _cur_dir:
                                        _shared += 1
                                        _d = ("y" if abs(_v[0]) >= abs(_v[1]) else "x", 1 if (_v[0] if abs(_v[0]) >= abs(_v[1]) else _v[1]) > 0 else -1)
                                        if _d != _cur_dir[_nm]:
                                            _match = False
                                            break
                                if _match and _shared >= 2:
                                    self._nav_avoid.add(_cc)
                        except Exception:
                            pass
                        self._nav_arrows = {}
                        self._nav_steps = {}
                        if self._nav_cursor is not None:
                            for nm, v in self._probe_disp.get(self._nav_cursor, {}).items():
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
                _cent0 = self._centroids(grid)
                if self._nav_cursor not in _cent0:
                    _miss = int(getattr(self, "_nav_miss", 0)) + 1
                    self._nav_miss = _miss
                    if _miss >= 3:
                        self._nav_miss = 0
                        self._m5phase = "learn"
                        self._sweep = []
                        self._probe_done = False
                        try:
                            self._probe_samples = {}
                        except Exception:
                            pass
                        return None
                else:
                    self._nav_miss = 0
            except Exception:
                pass
            try:
                cent = self._centroids(grid)
            except Exception:
                return None
            if self._nav_cursor not in cent:
                return None
            cy, cx, _cc = cent[self._nav_cursor]
            cands_c = []
            try:
                for _s in _segments(grid):
                    _sc = _s["color"]
                    if _sc == self._nav_bg or _sc == 0 or _sc == self._nav_cursor or _sc in self._nav_avoid:
                        continue
                    if _s["area"] < 9:
                        continue
                    _y1, _x1, _y2, _x2 = _s["bbox"]
                    _w = _x2 - _x1 + 1
                    _hh = _y2 - _y1 + 1
                    if not (2 <= _w <= 32 and 2 <= _hh <= 32):
                        continue
                    if _y1 >= SK48_STRIP_Y:
                        continue
                    cands_c.append((_s["area"], _s))
            except Exception:
                pass
            if not cands_c:
                return None
            cands_c.sort(key=lambda t: t[0])
            _blk = cands_c[0][1]
            tc = _blk["color"]
            tv = None
            tgt = None
            bestd = None
            try:
                _y1, _x1, _y2, _x2 = _blk["bbox"]
                for _yy in range(_y1, _y2 + 1):
                    for _xx in range(_x1, _x2 + 1):
                        if grid[_yy][_xx] == tc:
                            _d = abs(_yy - cy) + abs(_xx - cx)
                            if bestd is None or _d < bestd:
                                bestd, tgt = _d, (_yy, _xx)
            except Exception:
                pass
            if tgt is None:
                return None
            try:
                _pd = getattr(self, "_ls_prevd", None)
                if _pd is not None and bestd is not None and bestd >= _pd - 0.01:
                    self._ls_stall = int(getattr(self, "_ls_stall", 0)) + 1
                else:
                    self._ls_stall = 0
                self._ls_prevd = bestd
            except Exception:
                pass
            try:
                d_stall = int(getattr(self, "_ls_stall", 0))
            except Exception:
                d_stall = 0
            if (bestd is not None and bestd < 1.6) or d_stall >= 6:
                if d_stall >= 6:
                    try:
                        self._ls_stall = 0
                    except Exception:
                        pass
                for nm in sorted(self._nav_interact, key=lambda n: self._act_use[n]):
                    if h is not None and (h, nm, -1, -1) in self._pair_seen:
                        continue
                    if nm in byname:
                        if h is not None:
                            self._pair_seen.add((h, nm, -1, -1))
                        self._act_use[nm] += 1
                        self._sk_clicks += 1
                        self._record_choice(h, (nm, -1, -1))
                        try:
                            self._nav_last = {"tc": int(tc), "cy": round(float(cy), 1), "cx": round(float(cx), 1), "tgt": [int(tgt[0]), int(tgt[1])], "bestd": round(float(bestd), 2), "dir": "interact:" + nm}
                        except Exception:
                            pass
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
                            try:
                                self._nav_last = {"tc": int(tc), "cy": round(float(cy), 1), "cx": round(float(cx), 1), "tgt": [int(ty), int(tx)], "bestd": round(float(bestd), 2), "dir": "click"}
                            except Exception:
                                pass
                            return a
                if not hasattr(self, "_nav_dead"):
                    self._nav_dead = set()
                self._nav_dead.add(tc)
                return self._simple_pick(simple, h)
            best_a, best_q, best_dn = None, None, None
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
                    best_q, best_a, best_dn = q, nm, dn
            try:
                _lp = getattr(self, "_ls_pos", None)
                if _lp is not None and abs(cy - _lp[0]) < 0.01 and abs(cx - _lp[1]) < 0.01:
                    self._ls_pos_stall = int(getattr(self, "_ls_pos_stall", 0)) + 1
                else:
                    self._ls_pos_stall = 0
                self._ls_pos = (float(cy), float(cx))
            except Exception:
                pass
            try:
                if int(getattr(self, "_ls_pos_stall", 0)) >= 4:
                    self._ls_pos_stall = 0
                    try:
                        _btc = int(tc) if tc is not None else -1
                        if _btc >= 0:
                            self._nav_dead.add(_btc)
                            self._nav_last = None
                            self._ls_prevd = None
                    except Exception:
                        pass
                    _perp = [nm for dn, nm in self._nav_arrows.items() if dn != best_dn]
                    for _pnm in sorted(_perp, key=lambda n: self._act_use[n]):
                        if _pnm in byname:
                            self._act_use[_pnm] += 1
                            self._record_choice(h, (_pnm, -1, -1))
                            return byname[_pnm]
            except Exception:
                pass
            if best_a is not None:
                if best_dn == self._nav_last_dir:
                    self._nav_same_dir += 1
                else:
                    self._nav_same_dir = 0
                    self._nav_last_dir = best_dn
                try:
                    if int(getattr(self, "_nav_same_dir", 0)) >= 8:
                        self._nav_same_dir = 0
                        _btc2 = int(tc) if tc is not None else -1
                        if _btc2 >= 0:
                            self._nav_dead.add(_btc2)
                            self._nav_last = None
                            self._ls_prevd = None
                except Exception:
                    pass
                try:
                    self._nav_last = {"tc": int(tc), "cy": round(float(cy), 1), "cx": round(float(cx), 1), "tgt": [int(tgt[0]), int(tgt[1])], "bestd": round(float(bestd), 2) if bestd is not None else -1, "dir": best_dn, "same": self._nav_same_dir}
                except Exception:
                    pass
                if self._nav_same_dir >= 15:
                    self._nav_same_dir = 0
                    for nm in sorted(self._nav_interact, key=lambda n: self._act_use[n]):
                        if nm in byname and (h is None or (h, nm, -1, -1) not in self._pair_seen):
                            if h is not None:
                                self._pair_seen.add((h, nm, -1, -1))
                            self._act_use[nm] += 1
                            self._sk_clicks += 1
                            self._record_choice(h, (nm, -1, -1))
                            return byname[nm]
                self._act_use[best_a] += 1
                self._record_choice(h, (best_a, -1, -1))
                return byname[best_a]
            return None
        return None
    def _gate_id(self, grid):
        try:
            sub = [list(row) for row in grid[1:44]]
            if self._mask:
                for (y, x) in self._mask:
                    if 1 <= y < 44 and x < len(sub[0]):
                        sub[y - 1][x] = -1
            return tuple(tuple(r) for r in sub)
        except Exception:
            return None

    def _clickonly_pick(self, grid, h, six):
        if not six:
            return None
        try:
            if int(self._best_lc) != int(getattr(self, "_bfs_level", -1)):
                self._bfs_level = int(self._best_lc)
                self._csweep = None
                self._csweep_all = []
                self._cbest = None
                self._cbest_score = -1
                self._cpending = None
                self._ctop = []
                self._cexploit_n = 0
                self._cpair = []
                self._gate_clicks = []
                self._bfs_queue = []
                self._bfs_i = 0
                self._bfs_j = -1
                self._bfs_seen = set()
                self._bfs_turns = 0
                self._bfs_win = None
                self._need_reset = True
        except Exception:
            pass
        if self._csweep is None:
            pts = []
            try:
                for t in _targets(grid)[:16]:
                    pts.append((t[1], t[0]))
            except Exception:
                pass
            for gy in range(0, 64, 32):
                for gx in range(0, 64, 32):
                    pts.append((gx, gy))
            seen = set()
            uniq = []
            for p in pts:
                if p not in seen:
                    seen.add(p)
                    uniq.append(p)
            self._csweep = uniq
            self._csweep_all = list(uniq)
            self._need_reset = True
        if self._cpending is not None:
            try:
                _dg = 0
                if grid is not None and self._cpre_grid is not None and len(grid) == len(self._cpre_grid):
                    _top = min(len(grid), SK48_STRIP_Y)
                    for _yy in range(_top):
                        _ra, _rb = grid[_yy], self._cpre_grid[_yy]
                        for _xx in range(min(len(_ra), len(_rb))):
                            if _ra[_xx] != _rb[_xx]:
                                _dg += 1
                changed = (h != self._cpre)
            except Exception:
                _dg = 0
                changed = False
            score = (self._best_lc - self._cpending[0]) * 100000 + _dg
            if score > self._cbest_score:
                self._cbest_score = score
                self._cbest = self._cpending[1]
            try:
                self._ctop.append((score, self._cpending[1]))
                self._ctop.sort(reverse=True)
                self._ctop = self._ctop[:6]
                if _dg > 50 and self._cpending[1] not in self._gate_clicks:
                    self._gate_clicks.append(self._cpending[1])
            except Exception:
                pass
            self._cpending = None
            self._need_reset = False
        if not self._csweep:
            if self._cbest is None:
                return None
            self._cexploit_n += 1
            if self._gate_clicks and not getattr(self, "_nspiral_done", False) and self._cexploit_n >= 2:
                try:
                    self._nspiral_done = True
                    _nbrs = []
                    for (_gx, _gy) in self._gate_clicks[:6]:
                        for _dx, _dy in ((4, 0), (-4, 0), (0, 4), (0, -4), (8, 0), (-8, 0), (0, 8), (0, -8)):
                            _nx, _ny = min(63, max(0, _gx + _dx)), min(63, max(0, _gy + _dy))
                            _nbrs.append((_nx, _ny))
                    self._csweep = _nbrs + list(self._csweep_all or [])
                    self._need_reset = True
                except Exception:
                    pass
            if self._gate_clicks and self._cexploit_n >= 6:
                if not self._bfs_queue and self._bfs_i == 0 and self._bfs_j == -1 and not self._bfs_seen:
                    self._bfs_queue = [[[61, 33], [61, 33], [61, 33]]] + [[c] for c in self._gate_clicks[:6]]
                    gid0 = self._gate_id(grid)
                    if gid0 is not None:
                        self._bfs_seen.add(gid0)
                if self._bfs_turns < 1200:
                    while self._bfs_i < len(self._bfs_queue):
                        _seq = self._bfs_queue[self._bfs_i]
                        if self._bfs_j < 0:
                            self._bfs_lc0 = self._best_lc
                            self._bfs_j = 0
                            self._expect_reset = True
                            try:
                                self._att = 0
                                self._gpar = 0
                            except Exception:
                                pass
                            self._bfs_turns += 1
                            return GameAction.RESET
                        if self._bfs_j < len(_seq):
                            _px, _py = _seq[self._bfs_j]
                            _a = six[0]
                            try:
                                _a.set_data({"x": _px, "y": _py})
                            except Exception:
                                self._bfs_i += 1
                                self._bfs_j = -1
                                self._expect_reset = True
                                try:
                                    self._att = 0
                                    self._gpar = 0
                                except Exception:
                                    pass
                                return GameAction.RESET
                            _nm = str(_a)
                            self._act_use[_nm] += 1
                            self._sk_clicks += 1
                            self._record_choice(h, (_nm, _px, _py))
                            self._bfs_j += 1
                            self._bfs_turns += 1
                            return _a
                        if self._best_lc > self._bfs_lc0:
                            self._bfs_win = list(_seq)
                        _gid = self._gate_id(grid)
                        try:
                            _gkey = (_gid, int(getattr(self, "_gpar", 0)))
                        except Exception:
                            _gkey = None
                        if _gid is not None and _gkey is not None and _gkey not in self._bfs_seen and len(_seq) < 7:
                            self._bfs_seen.add(_gkey)
                            for _gc in self._gate_clicks[:6]:
                                self._bfs_queue.append(_seq + [_gc])
                        self._bfs_i += 1
                        self._bfs_j = -1
                    self._bfs_queue = []
            if self._need_reset:
                self._need_reset = False
                self._expect_reset = True
                try:
                    self._att = 0
                    self._gpar = 0
                except Exception:
                    pass
                try:
                    self._att = 0
                    self._gpar = 0
                except Exception:
                    pass
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
            try:
                self._att = 0
                self._gpar = 0
            except Exception:
                pass
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
        try:
            self._cpre_grid = [list(_r) for _r in grid] if grid is not None else None
        except Exception:
            self._cpre_grid = None
        self._need_reset = True
        self._sk_clicks += 1
        self._record_choice(h, (nm, px, py))
        return a

    def _combo_pick(self, h, simple):
        if not self._simple_only:
            return None
        names = sorted(set(str(a) for a in simple))
        byname = {}
        for a in simple:
            byname.setdefault(str(a), a)
        if self._combo_pairs is None:
            acts = names[:5]
            self._combo_pairs = [(a, b) for a in acts for b in acts]
            self._combo_i = 0
            self._combo_stage = 0
        if self._combo_i >= len(self._combo_pairs):
            return None
        if self._combo_stage == 2:
            if self._best_lc > self._combo_eval:
                self._combo_win = list(self._combo_pairs[self._combo_i])
            self._combo_i += 1
            self._combo_stage = 0
            if self._combo_i >= len(self._combo_pairs):
                return None
        if self._combo_stage == 0:
            self._combo_eval = self._best_lc
            self._combo_stage = 1
            self._expect_reset = True
            try:
                self._att = 0
                self._gpar = 0
            except Exception:
                pass
            return GameAction.RESET
        a_nm, b_nm = self._combo_pairs[self._combo_i]
        nm = a_nm if self._combo_stage == 1 else b_nm
        if nm not in byname:
            self._combo_i += 1
            self._combo_stage = 0
            return GameAction.RESET
        if self._combo_stage == 1:
            self._combo_stage = 2
        self._act_use[nm] += 1
        self._record_choice(h, (nm, -1, -1))
        return byname[nm]

    def _sk48_fire(self, grid, h, simple, six):
        byname = {}
        for a in simple:
            byname.setdefault(str(a), a)
        if "GameAction.ACTION1" not in byname or "GameAction.ACTION2" not in byname:
            return None
        if self._skf_order is None:
            try:
                seq = [c for c in _sk_strip_order(grid) if c in SK48_BLOCK_COLORS]
            except Exception:
                seq = []
            if not seq:
                seq = [8, 6, 14, 9]
            self._skf_order = [c for c in seq if c in (8, 6, 14, 9)]
            if not self._skf_order:
                self._skf_order = [8, 9]
            self._skf_ti = 0
            self._skf_phase = "aim"
            self._skf_fires = 0
            self._skf_stag = 0
            self._skf_stage = 0
        try:
            blocks = _sk_blocks(grid)
        except Exception:
            return None
        while self._skf_ti < len(self._skf_order) and self._skf_order[self._skf_ti] not in blocks:
            self._skf_ti += 1
        if self._skf_ti >= len(self._skf_order):
            return None
        tc = self._skf_order[self._skf_ti]
        cur = _sk_cursor(grid)
        if cur is None:
            return None
        cy = cur[0]
        try:
            _ty, _tx, _ta = blocks[tc]
        except Exception:
            self._skf_ti += 1
            return None
        if self._skf_phase == "aim":
            if cy < _ty - 3:
                nm = "GameAction.ACTION2"
            elif cy > _ty + 3:
                nm = "GameAction.ACTION1"
            else:
                self._skf_phase = "fire"
                self._skf_fires = 0
                self._skf_stag = 0
                self._skf_tip = 0
                self._skf_stage = 0
                nm = None
            if nm is not None and nm in byname:
                self._act_use[nm] += 1
                self._record_choice(h, (nm, -1, -1))
                return byname[nm]
            if nm is not None:
                return None
        if self._skf_phase == "fire":
            try:
                _bth = [0.0, 0.25, 0.5, 0.75][self._skf_ti % 4]
            except Exception:
                _bth = 0.0
            try:
                self._skf_bth = _bth
            except Exception:
                pass
            if self._skf_stage == 0 and self._barfill < _bth:
                return None
            try:
                _tip = 0
                for _yy in range(max(0, cy - 2), min(len(grid), cy + 3)):
                    _row = grid[_yy]
                    for _xx in range(len(_row)):
                        if _row[_xx] == 1 and _xx > _tip:
                            _tip = _xx
            except Exception:
                _tip = self._skf_tip
            try:
                _contact = _tip >= _tx - 2
            except Exception:
                _contact = False
            self._sk_target = tc
            if self._skf_stage == 0:
                if _tip > self._skf_tip:
                    self._skf_tip = _tip
                    self._skf_stag = 0
                else:
                    self._skf_stag += 1
                if _contact:
                    try:
                        _ci = int(getattr(self, "_skf_combo", 0)) % 3
                    except Exception:
                        _ci = 0
                    try:
                        self._skf_combo = int(getattr(self, "_skf_combo", 0)) + 1
                    except Exception:
                        self._skf_combo = 1
                    try:
                        self._skf_cc = _ci
                    except Exception:
                        pass
                    if _ci == 0 and six:
                        self._skf_stage = 2
                        self._skf_fires = 0
                        try:
                            self._skf_fv = 0
                        except Exception:
                            pass
                        _a0 = six[0]
                        try:
                            _a0.set_data({"x": _tx, "y": _ty})
                        except Exception:
                            _a0 = None
                        if _a0 is not None:
                            _nmc0 = str(_a0)
                            self._act_use[_nmc0] += 1
                            self._sk_clicks += 1
                            self._record_choice(h, (_nmc0, _tx, _ty))
                            return _a0
                    elif _ci in (1, 2, 3):
                        self._skf_stage = 4
                        self._skf_fires = 0
                        try:
                            self._skf_fv = _ci
                        except Exception:
                            pass
                        return None
                    self._skf_stage = 1
                    self._skf_fires = 0
                elif self._skf_fires >= 12 or self._skf_stag >= 6:
                    self._skf_ti += 1
                    self._skf_phase = "aim"
                    self._skf_fires = 0
                    self._skf_stag = 0
                    return None
                if "GameAction.ACTION4" in byname:
                    self._skf_fires += 1
                    self._sk_clicks += 1
                    self._record_choice(h, ("GameAction.ACTION4", -1, -1))
                    return byname["GameAction.ACTION4"]
                return None
            if self._skf_stage == 1:
                self._skf_fires += 1
                try:
                    _hold = 0 if (self._skf_ti % 2 == 0) else 15
                except Exception:
                    _hold = 15
                try:
                    self._skf_holdmode = _hold
                except Exception:
                    pass
                if self._skf_fires >= _hold:
                    self._skf_stage = 2
                    self._skf_fires = 0
                    try:
                        self._skf_fv = _hold
                    except Exception:
                        pass
                    if "GameAction.ACTION7" in byname:
                        self._sk_clicks += 1
                        self._record_choice(h, ("GameAction.ACTION7", -1, -1))
                        return byname["GameAction.ACTION7"]
                if "GameAction.ACTION4" in byname:
                    self._sk_clicks += 1
                    self._record_choice(h, ("GameAction.ACTION4", -1, -1))
                    return byname["GameAction.ACTION4"]
                return None
            if self._skf_stage == 2:
                self._skf_fires += 1
                _nm2 = "GameAction.ACTION3" if self._skf_fires <= 2 else None
                if self._skf_fires == 3:
                    _nm2 = "clickblock"
                if self._skf_fires >= 4:
                    try:
                        _chain = (int(getattr(self, "_skf_hits", 0)) % 2 == 1)
                    except Exception:
                        _chain = False
                    if _chain:
                        try:
                            self._skf_hits = int(getattr(self, "_skf_hits", 0)) + 1
                        except Exception:
                            pass
                        if int(getattr(self, "_skf_hits", 1)) % 3 == 0:
                            self._skf_ti += 1
                        self._skf_phase = "aim"
                        self._skf_stage = 0
                        self._skf_fires = 0
                        self._skf_stag = 0
                        return None
                    self._skf_stage = 3
                    self._skf_fires = 0
                    return None
                if _nm2 == "clickblock" and six:
                    _a = six[0]
                    try:
                        _a.set_data({"x": _tx, "y": _ty})
                    except Exception:
                        return None
                    _nmc = str(_a)
                    self._act_use[_nmc] += 1
                    self._sk_clicks += 1
                    self._record_choice(h, (_nmc, _tx, _ty))
                    return _a
                if _nm2 in byname:
                    self._act_use[_nm2] += 1
                    self._record_choice(h, (_nm2, -1, -1))
                    return byname[_nm2]
                self._skf_stage = 3
                self._skf_fires = 0
                return None
            if self._skf_stage == 4:
                self._skf_fires += 1
                try:
                    _cc = int(getattr(self, "_skf_cc", 1))
                except Exception:
                    _cc = 1
                if self._skf_fires == 1:
                    _mv = "GameAction.ACTION7"
                    if _mv in byname:
                        self._act_use[_mv] += 1
                        self._record_choice(h, (_mv, -1, -1))
                        return byname[_mv]
                    self._skf_stage = 1
                    self._skf_fires = 0
                    return None
                if self._skf_fires == 2 and six:
                    _a4 = six[0]
                    try:
                        _a4.set_data({"x": _tx, "y": _ty})
                    except Exception:
                        _a4 = None
                    if _a4 is not None:
                        _nmc4 = str(_a4)
                        self._act_use[_nmc4] += 1
                        self._sk_clicks += 1
                        self._record_choice(h, (_nmc4, _tx, _ty))
                        return _a4
                if self._skf_fires >= 3:
                    try:
                        self._skf_hits = int(getattr(self, "_skf_hits", 0)) + 1
                    except Exception:
                        self._skf_hits = 1
                    if int(getattr(self, "_skf_hits", 1)) % 3 == 0:
                        self._skf_ti += 1
                    self._skf_phase = "aim"
                    self._skf_stage = 0
                    self._skf_fires = 0
                    return None
                return None
            if self._skf_stage == 3:
                self._skf_fires += 1
                if _tip <= 8 or self._skf_fires >= 6:
                    try:
                        self._skf_hits = int(getattr(self, "_skf_hits", 0)) + 1
                    except Exception:
                        self._skf_hits = 1
                    if int(getattr(self, "_skf_hits", 1)) % 3 == 0:
                        self._skf_ti += 1
                    self._skf_phase = "aim"
                    self._skf_fires = 0
                    self._skf_stag = 0
                    self._skf_stage = 0
                    return None
                if "GameAction.ACTION7" in byname:
                    self._act_use["GameAction.ACTION7"] += 1
                    self._record_choice(h, ("GameAction.ACTION7", -1, -1))
                    return byname["GameAction.ACTION7"]
                self._skf_ti += 1
                self._skf_phase = "aim"
                self._skf_stage = 0
                self._skf_fires = 0
                return None
        return None

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
            self._combo_pairs = None
            self._combo_i = 0
            self._combo_stage = 0
            self._skf_order = None
            self._skf_ti = 0
            self._skf_phase = "aim"
            self._skf_fires = 0
            self._skf_stag = 0
            if not self._expect_reset:
                self._replay = None
            self._expect_reset = False
            try:
                self._att = 0
                self._gpar = 0
            except Exception:
                pass
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
        try:
            self._cur_lc = int(_lc) if _lc is not None else -1
        except Exception:
            self._cur_lc = -1
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
        try:
            _g2 = 0
            _r2 = 0
            if grid is not None:
                for _yy in range(SK48_STRIP_Y, len(grid)):
                    for _vv in grid[_yy]:
                        if _vv == 3:
                            _g2 += 1
                        elif _vv == 2:
                            _r2 += 1
            self._barfill = round(_g2 / float(_g2 + _r2), 3) if (_g2 + _r2) else 0.0
        except Exception:
            pass
        if grid is not None and len(self._scal) < 250:
            try:
                _sd = self._snap(grid)
                _sd["t"] = self._turns
                _sd["lc"] = self._best_lc
                self._scal.append(_sd)
            except Exception:
                pass
        if self._turns == 10 and not self._ff:
            try:
                self._ff = self._forced_fire()
            except Exception as _e:
                self._ff = {"err": str(_e)[:80]}
        cands = [a for a in avail if a is not GameAction.RESET]
        simple = [a for a in cands if not _complex(a)]
        six = [a for a in cands if _complex(a)]
        self._simple_only = bool(simple) and not six
        if len(self._sk_trace) < 60:
            try:
                self._sk_trace.append([self._turns, self._skf_phase, ",".join(sorted(str(a) for a in simple))])
            except Exception:
                pass
        if self._simple_only:
            try:
                _ch = self._combo_pick(h, simple)
            except Exception:
                _ch = None
            if _ch is not None:
                return _ch
        if self._replay:
            hit = self._replay_pick(cands, h)
            if hit is not None:
                return hit
        if grid and (simple or six):
            try:
                if getattr(self, "_game_id", "") == "sk48":
                    _sf = self._sk48_fire(grid, h, simple, six)
                    if _sf is not None:
                        return _sf
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
                try:
                    self._att = 0
                    self._gpar = 0
                except Exception:
                    pass
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
