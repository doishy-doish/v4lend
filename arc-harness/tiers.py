SALIENT = frozenset(range(6, 16))
EDGE_DIST = 3
BAR_ASPECT = 5
BAR_MIN_TWINS = 3
MIN_W = 2
MAX_W = 32


def segment(grid):
    h = len(grid)
    w = len(grid[0]) if h else 0
    seen = [[False] * w for _ in range(h)]
    segs = []
    for y in range(h):
        for x in range(w):
            if seen[y][x]:
                continue
            color = grid[y][x]
            stack = [(x, y)]
            seen[y][x] = True
            cells = []
            y1 = y2 = y
            x1 = x2 = x
            while stack:
                cx, cy = stack.pop()
                cells.append((cy, cx))
                y1 = min(y1, cy)
                y2 = max(y2, cy)
                x1 = min(x1, cx)
                x2 = max(x2, cx)
                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                    if 0 <= nx < w and 0 <= ny < h and not seen[ny][nx] and grid[ny][nx] == color:
                        seen[ny][nx] = True
                        stack.append((nx, ny))
            segs.append({"color": color, "bbox": (y1, x1, y2, x2), "area": len(cells)})
    return segs


def _center(s):
    y1, x1, y2, x2 = s["bbox"]
    return ((y1 + y2) // 2, (x1 + x2) // 2)


def _aspect(s):
    y1, x1, y2, x2 = s["bbox"]
    w = x2 - x1 + 1
    h = y2 - y1 + 1
    return max(w, h) / max(1, min(w, h))


def _medium(s):
    y1, x1, y2, x2 = s["bbox"]
    return MIN_W <= x2 - x1 + 1 <= MAX_W and MIN_W <= y2 - y1 + 1 <= MAX_W


def status_bars(segs, size=64):
    twins = {}
    for s in segs:
        k = (s["area"], s["color"])
        twins[k] = twins.get(k, 0) + 1
    out = set()
    for i, s in enumerate(segs):
        y1, x1, y2, x2 = s["bbox"]
        near = y1 < EDGE_DIST or y2 >= size - EDGE_DIST or x1 < EDGE_DIST or x2 >= size - EDGE_DIST
        if not near:
            continue
        if _aspect(s) >= BAR_ASPECT or twins.get((s["area"], s["color"]), 0) >= BAR_MIN_TWINS:
            out.add(i)
    return out


def classify(segs, status=None):
    status = status or set()
    tiers = {i: [] for i in range(5)}
    for i, s in enumerate(segs):
        if i in status:
            tiers[4].append(s)
        elif s["color"] in SALIENT and _medium(s):
            tiers[0].append(s)
        elif _medium(s):
            tiers[1].append(s)
        elif s["color"] in SALIENT:
            tiers[2].append(s)
        else:
            tiers[3].append(s)
    return tiers


def priority_targets(grid, max_targets=32):
    segs = segment(grid)
    tiers = classify(segs, status_bars(segs, len(grid)))
    out = []
    for t in range(5):
        for s in tiers[t]:
            if s["area"] < 2:
                continue
            out.append(_center(s))
            if len(out) >= max_targets:
                return out
    return out
