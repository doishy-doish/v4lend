from compact import summarize


def test_short_history_untouched():
    turns = [{"action": "up"}, {"note": "wall at left"}]
    out, notes = summarize(turns, keep=20)
    assert out == turns and notes is None


def test_compact_keeps_notes_and_summary():
    turns = [{"note": "keep me"}]
    turns += [{"action": "a%d" % i, "fail": (i % 2 == 0)} for i in range(30)]
    out, notes = summarize(turns, keep=10)
    assert out[0] == {"note": "keep me"}
    assert notes["n_dropped"] == 15
    assert notes["n_fails"] == 8
    assert len([t for t in out if "note" not in t]) == 15
