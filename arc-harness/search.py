from collections import deque


def _rot(grid):
    return [list(r) for r in zip(*grid[::-1])]


def _flip(grid):
    return [row[::-1] for row in grid]


def transforms(grid):
    out = []
    seen = set()
    g = grid
    for _ in range(4):
        for t in (g, _flip(g)):
            k = tuple(tuple(r) for r in t)
            if k not in seen:
                seen.add(k)
                out.append(t)
        g = _rot(g)
    return out


def canonical_hash(grid):
    return min(tuple(tuple(r) for r in t) for t in transforms(grid))


def score_grid(grid):
    rare = sum(1 for row in grid for v in row if v >= 6)
    colors = len({v for row in grid for v in row})
    return -(rare * 20 + colors)


def _key(s):
    if isinstance(s, (int, str, tuple)):
        return s
    return tuple(map(tuple, s))


def bfs_plan(successors, start, is_goal, max_depth=10):
    dq = deque([(start, [])])
    seen = {_key(start)}
    while dq:
        s, p = dq.popleft()
        if is_goal(s):
            return p
        if len(p) >= max_depth:
            continue
        for a, ns in successors(s):
            k = _key(ns)
            if k not in seen:
                seen.add(k)
                dq.append((ns, p + [a]))
    return None


def choose_strategy(seen, goal_known):
    return "EXPLOIT" if (seen and goal_known) else "EXPLORE"


def disagreement(a, b):
    return a != b
