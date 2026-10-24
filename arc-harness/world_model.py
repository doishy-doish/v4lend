from synth import candidates, verify


class WorldModel:
    def __init__(self, rank):
        self.rank = rank
        self.rules = []

    def fit(self, objs):
        self.rules = self.rank(candidates(objs))
        return self.rules

    def top(self):
        return self.rules[0] if self.rules else None


def simple_rank(rules):
    return sorted(rules, key=lambda r: (r["size"], r["target"]))


def full_rank(rules):
    return sorted(rules, key=lambda r: (r["target"], r["size"]))


class DualWorld:
    def __init__(self):
        self.simple = WorldModel(simple_rank)
        self.full = WorldModel(full_rank)
        self.explorations = 0

    def fit(self, objs):
        self.simple.fit(objs)
        self.full.fit(objs)

    def agree(self):
        a = self.simple.top()
        b = self.full.top()
        if a is None or b is None:
            return True
        return (a["target"], a["size"]) == (b["target"], b["size"])

    def explore_order(self):
        a = self.simple.top()
        b = self.full.top()
        out = []
        for r in (a, b):
            if r is not None and all((r["target"], r["size"]) != (o["target"], o["size"]) for o in out):
                out.append(r)
        if len(out) > 1:
            self.explorations += 1
        return out

    def confirm(self, rule, change):
        return verify(rule, change)
