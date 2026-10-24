def objects(grid):
    h = len(grid)
    w = len(grid[0]) if h else 0
    seen = [[False]*w for _ in range(h)]
    outs = []
    for y in range(h):
        for x in range(w):
            v = grid[y][x]
            if v == 0 or seen[y][x]:
                continue
            stack = [(x, y)]
            cells = []
            seen[y][x] = True
            while stack:
                cx, cy = stack.pop()
                cells.append((cx, cy))
                for nx, ny in ((cx+1, cy), (cx-1, cy), (cx, cy+1), (cx, cy-1)):
                    if 0 <= nx < w and 0 <= ny < h and not seen[ny][nx] and grid[ny][nx] == v:
                        seen[ny][nx] = True
                        stack.append((nx, ny))
            outs.append({"color": v, "cells": cells, "size": len(cells)})
    return outs


def delta(a, b):
    out = []
    for y in range(min(len(a), len(b))):
        for x in range(min(len(a[y]), len(b[y]))):
            if a[y][x] != b[y][x]:
                out.append((x, y, a[y][x], b[y][x]))
    return out
