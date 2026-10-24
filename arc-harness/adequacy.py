def adequacy(rules, transitions):
    if not transitions:
        return 1.0
    explained = 0
    for before, after in transitions:
        changed = {(x, y) for x, y, _, _ in __import__("perceive").delta(before, after)}
        hit = any(set(r["cells"]) & changed for r in rules)
        explained += 1 if hit else 0
    return explained / len(transitions)


def ontology_error(rules, transitions):
    return 1.0 - adequacy(rules, transitions)
