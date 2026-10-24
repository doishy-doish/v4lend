def candidates(objs):
    rules = []
    small = sorted([o for o in objs if o["size"] <= 4], key=lambda o: (o["size"], o["color"]))
    rest = sorted([o for o in objs if o["size"] > 4], key=lambda o: (o["size"], o["color"]))
    for o in small + rest:
        rules.append({"op": "click", "target": o["color"], "size": o["size"], "cells": o["cells"]})
        if len(rules) >= 4:
            break
    return rules


def verify(rule, change):
    if not change:
        return False
    changed = {(x, y) for x, y, _, _ in change}
    cells = set(rule["cells"])
    return len(changed & cells) > 0 or rule["size"] <= 2
