class ActionRanker:
    def __init__(self):
        self._effective = set()
        self.buffer = []

    def reset(self):
        self._effective = set()
        self.buffer = []

    def record(self, action, changed):
        self.buffer.append((action, changed))
        if changed:
            self._effective.add(action)

    def rank(self, actions):
        eff = [a for a in actions if a in self._effective]
        rest = [a for a in actions if a not in self._effective]
        return eff + rest


def compute_rhae(ai_actions, human_baseline):
    if ai_actions == 0:
        return 0.0
    return min(1.0, human_baseline / ai_actions) ** 2


def giveup_budget(baseline, n_actions=4):
    floor = n_actions + 30
    mult = max(5.0, n_actions / max(baseline, 1) + 3.0)
    return max(int(baseline * mult), floor)


def should_give_up(taken, baseline, n_available=4):
    return taken >= giveup_budget(baseline, n_available)
