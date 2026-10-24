from tiers import segment, classify, status_bars, priority_targets
from rank import ActionRanker, compute_rhae, giveup_budget, should_give_up
from discover import discover

PLUS = [[0, 1, 0], [1, 1, 1], [0, 1, 0]]


def test_segment_plus():
    segs = segment(PLUS)
    plus = [s for s in segs if s["color"] == 1]
    assert len(plus) == 1 and plus[0]["area"] == 5
    assert plus[0]["bbox"] == (0, 0, 2, 2)
    tiers = classify(segs, status_bars(segs, 3))
    assert plus[0] in tiers[1]


def test_salient_tier_zero():
    segs = segment([[0, 7, 0], [7, 7, 7], [0, 7, 0]])
    plus = [s for s in segs if s["color"] == 7]
    tiers = classify(segs, status_bars(segs, 3))
    assert plus[0] in tiers[0]
    assert priority_targets([[0, 7, 0], [7, 7, 7], [0, 7, 0]])[0] == (1, 1)


def test_status_bar_last():
    grid = [[5] * 8 for _ in range(2)] + [[0] * 8 for _ in range(6)]
    segs = segment(grid)
    bars = status_bars(segs, 8)
    assert len(bars) == 1
    tiers = classify(segs, bars)
    assert segs[list(bars)[0]] in tiers[4]


def test_ranker_effective_first():
    r = ActionRanker()
    r.record("a", False)
    r.record("b", True)
    assert r.rank(["a", "b"]) == ["b", "a"]


def test_rhae_and_giveup():
    assert compute_rhae(100, 25) == 0.0625
    assert compute_rhae(0, 25) == 0.0
    assert compute_rhae(10, 25) == 1.0
    b = giveup_budget(20)
    assert b >= 34 and should_give_up(b, 20) and not should_give_up(b - 1, 20)


def test_discover_dedupes_and_ranks():
    def probe(a):
        return {"up": {(0, 0)}, "down": {(0, 0)}, "left": set(), "right": {(1, 1)}}[a]
    rep = discover(["up", "down", "left", "right"], probe)
    assert rep["n_unique"] == 2 and rep["n_noop"] == 1 and rep["dup_groups"] == 1
    assert set(rep["order"]) == {"up", "right"}
