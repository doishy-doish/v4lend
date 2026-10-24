from rank import ActionRanker


def discover(legal_actions, probe):
    ranker = ActionRanker()
    seen = {}
    noop = []
    for a in legal_actions:
        try:
            cells = frozenset(probe(a))
        except Exception:
            cells = frozenset()
        changed = len(cells) > 0
        ranker.record(a, changed)
        if not changed:
            noop.append(a)
        elif cells in seen:
            seen[cells].append(a)
        else:
            seen[cells] = [a]
    unique = [v[0] for v in seen.values()]
    order = ranker.rank(unique)
    return {"order": order, "n_unique": len(unique), "n_noop": len(noop),
            "dup_groups": sum(len(v) - 1 for v in seen.values()), "ranker": ranker}
