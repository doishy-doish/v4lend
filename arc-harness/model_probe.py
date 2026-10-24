import json
import time
import urllib.request

REPO = "unsloth/Qwen3.5-4B-GGUF"
FILE = "Qwen3.5-4B-Q4_K_M.gguf"
URL = "https://huggingface.co/" + REPO + "/resolve/main/" + FILE

m = {}
t0 = time.time()
urllib.request.urlretrieve(URL, "/tmp/model.gguf")
m["download_s"] = round(time.time() - t0, 1)

from llama_cpp import Llama
t0 = time.time()
llm = Llama(model_path="/tmp/model.gguf", n_ctx=512, n_threads=4, verbose=False)
m["load_s"] = round(time.time() - t0, 1)

t0 = time.time()
out = llm("def add(a, b):", max_tokens=64)
dt = time.time() - t0
ntok = out["usage"]["completion_tokens"]
m["gen_tokens"] = ntok
m["gen_s"] = round(dt, 1)
m["tok_per_s"] = round(ntok / max(dt, 1e-6), 1)
m["sample"] = out["choices"][0]["text"][:200]

with open("model-probe-metrics.json", "w") as f:
    json.dump(m, f, indent=2)
print("PROBE_OK " + json.dumps(m))
