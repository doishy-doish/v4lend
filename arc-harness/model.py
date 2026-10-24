import os


def load_model():
    path = os.environ.get("MODEL_PATH", "")
    if not path:
        return None
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    tok = AutoTokenizer.from_pretrained(path, trust_remote_code=True)
    m = AutoModelForCausalLM.from_pretrained(path, torch_dtype="auto", trust_remote_code=True)
    return tok, m


def generate(tok_mod, prompt, max_new=64):
    if tok_mod is None:
        return "STUB_NO_MODEL"
    tok, m = tok_mod
    ids = tok(prompt, return_tensors="pt").input_ids
    out = m.generate(ids, max_new_tokens=max_new)
    return tok.decode(out[0], skip_special_tokens=True)
