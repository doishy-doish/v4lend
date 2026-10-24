def summarize(turns, keep=20):
    notes_rows = [t for t in turns if "note" in t]
    play = [t for t in turns if "note" not in t]
    if len(play) <= keep:
        return turns, None
    head = play[:5]
    tail = play[-keep:]
    dropped = play[5:len(play)-keep]
    fails = [t for t in dropped if t.get("fail")]
    notes = {"n_dropped": len(dropped), "n_fails": len(fails),
             "fail_actions": sorted({t["action"] for t in fails if "action" in t})}
    return notes_rows + head + tail, notes
