# arc-harness

CPU-only ARC-AGI-3 agent harness. Zero GPU, zero spend, all tests run on free CI.

## What is here

- agent.py: random baseline with module store, regression gate, CSV writer, corrupt-frame fallback
- perceive.py / synth.py: connected components, deltas, candidate rules, verifier
- tiers.py: pure-Python priority tiers, bbox segments, 5-tier click targets (Occam port)
- rank.py: action ranker, RHAE formula, dynamic give-up budget (Occam port)
- discover.py: probe, drop no-ops, dedupe equivalent effects, rank effective first
- world_model.py: dual competing world models, disagreement-driven exploration
- adequacy.py: ontology error, explained-transition ratio
- gate.py: actor-requested builder delegation, patience plus threshold
- compact.py: summarize-keeps-notes compaction, notes survive, fail actions logged
- search.py: D4 canonical hashing, rare-pixel heuristic, BFS lookahead, explore-exploit switch
- kaggle.py: 9-hour watchdog runner, offline guard, strict CSV validator, model-load fallback
- concurrency.py / model.py / model_probe.py: parallel episodes, lazy model stub, CPU timing probe

## Reproduce

```
cd arc-harness
pip install -r requirements.txt
python3 -m pytest -q
```

## License

MIT, see repo root LICENSE.
