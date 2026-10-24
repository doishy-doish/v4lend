import os
from concurrency import run_many
import model


def test_many_concurrent():
    grids = [{"grid": [[i]], "legal": ["stay"]} for i in range(8)]
    res = run_many(grids, max_turns=4, workers=4)
    assert len(res) == 8 and all(r["ok"] for r in res)


def test_model_stub_without_load():
    os.environ.pop("MODEL_PATH", None)
    assert model.load_model() is None
    assert model.generate(None, "hello") == "STUB_NO_MODEL"
