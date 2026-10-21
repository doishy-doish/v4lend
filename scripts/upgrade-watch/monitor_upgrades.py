#!/usr/bin/env python3
"""Proxy upgrade diff monitor. Stdlib only. $0: public RPC + DefiLlama, no API keys.

Pipeline: eth_getLogs for Upgraded(address) over watched proxies -> on change,
fetch old/new implementation bytecode -> emit JSON finding -> invariant fuzzer
takes it from there (diff-only scope, never whole-protocol fuzz).

Usage:
  RPC_URL=https://ethereum-rpc.publicnode.com python3 scripts/monitor_upgrades.py
  RPC_URL=... python3 scripts/monitor_upgrades.py --lookback 5000 --state scratch/upgrade-state.json --out findings

Exit code 2 when a new upgrade is found (Actions job can gate on it).

Test notes 2026-10-20: 4-proxy sweep over 2000 blocks clean, zero upgrades.
EIP-1967 slot reads return zero on Lido/Sky/Spark entries and on USDC/USDT
(non-1967 or admin-gated proxies); eth_call implementation() reverts on
transparent proxies for non-admin callers. So first-run state is a cold
baseline (oldImpl None, coldBaseline true); old source resolves at the
Sourcify stage, not here. Only Aave V3 Pool verified EIP-1967 so far.
"""
import argparse
import json
import os
import sys
import time
import urllib.request

UPGRADED_TOPIC = "0xbc7cd75a20ee27fd9adebab32041f755214d8526a507d8a33950f42aa1c70d1b"

CHAIN_RPCS = {
    "ethereum": ["https://ethereum-rpc.publicnode.com", "https://eth.llamarpc.com",
                 "https://ethereum.publicnode.com", "https://rpc.ankr.com/eth"],
    "optimism": ["https://mainnet.optimism.io", "https://optimism.llamarpc.com",
                 "https://optimism.publicnode.com"],
}

WATCHED = [
    ("OptimismPortalProxy", "ethereum", "https://ethereum-rpc.publicnode.com",
     "0xbEb5Fc579115071764c7423A4f12eDde41f106Ed"),
    ("L1StandardBridgeProxy", "ethereum", "https://ethereum-rpc.publicnode.com",
     "0x99C9fc46f92E8a1c0deC1b1747d010903E884bE1"),
    ("SystemConfigProxy", "ethereum", "https://ethereum-rpc.publicnode.com",
     "0x229047fed2591dbec1eF1118d64F7aF3dB9EB290"),
    ("AaveV3Pool-OP", "optimism", "https://mainnet.optimism.io",
     "0x794a61358D6845594F94dc1DB02A252b5b4814aD"),
    ("AaveV3Pool-ETH", "ethereum", "https://ethereum-rpc.publicnode.com",
     "0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2"),
]


def rpc(url, method, params):
    last = None
    for attempt in (1, 2):
        body = json.dumps({"jsonrpc": "2.0", "id": attempt, "method": method, "params": params}).encode()
        req = urllib.request.Request(url, data=body, headers={"content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                out = json.load(r)
        except Exception as e:
            last = e
            time.sleep(5)
            continue
        if out.get("error"):
            last = RuntimeError(out["error"])
            time.sleep(5)
            continue
        return out["result"]
    raise RuntimeError("rpc failed %s %s: %r" % (url, method, last))


def rpc_any(chain, first, method, params):
    urls = [first] + [u for u in CHAIN_RPCS.get(chain, []) if u != first]
    last = None
    for u in urls:
        try:
            out = rpc(u, method, params)
            time.sleep(1)
            return out
        except Exception as e:
            last = e
    raise RuntimeError("all endpoints failed for %s %s: %r" % (chain, method, last))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lookback", type=int, default=1000)
    ap.add_argument("--lookback-op", type=int, default=None,
                    help="lookback for optimism (2s blocks); defaults to --lookback")
    ap.add_argument("--state", default="scratch/upgrade-state.json")
    ap.add_argument("--out", default="findings")
    args = ap.parse_args()

    chains = {}
    for name, chain, rpc, proxy in WATCHED:
        chains.setdefault(chain, {"rpc": rpc, "latest": None})
    for chain, info in chains.items():
        first = next(r for n, c, r, p in WATCHED if c == chain)
        info["latest"] = int(rpc_any(chain, first, "eth_blockNumber", []), 16)
    latest = max(i["latest"] for i in chains.values())
    try:
        with open(args.state) as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = {}

    os.makedirs(args.out, exist_ok=True)
    for name, chain, rpc_url, proxy in WATCHED:
        rk = proxy.lower() + "@" + chain
        if rk not in state:
            state[rk] = {"impl": None, "block": chains[chain]["latest"], "baseline": "cold"}
    new_hits = []
    for name, chain, rpc_url, proxy in WATCHED:
        rk = proxy.lower() + "@" + chain
        latest_c = chains[chain]["latest"]
        lb = args.lookback_op if (chain == "optimism" and args.lookback_op) else args.lookback
        frm = hex(max(0, latest_c - lb))
        logs = rpc_any(chain, rpc_url, "eth_getLogs", [{
            "fromBlock": frm, "toBlock": "latest",
            "address": proxy, "topics": [UPGRADED_TOPIC],
        }])
        for lg in logs:
            new_impl = "0x" + lg["topics"][1][-40:]
            blk = int(lg["blockNumber"], 16)
            prev = state.get(rk)
            if prev and prev.get("impl") and prev["impl"].lower() == new_impl.lower():
                continue
            old_code = rpc_any(chain, rpc_url, "eth_getCode", [prev["impl"], hex(blk - 1)]) if prev and prev.get("impl") else "0x"
            new_code = rpc_any(chain, rpc_url, "eth_getCode", [new_impl, "latest"])
            hit = {"protocol": name, "chain": chain, "proxy": proxy, "block": blk,
                   "tx": lg["transactionHash"], "oldImpl": prev.get("impl") if prev else None,
                   "newImpl": new_impl, "oldLen": len(old_code), "newLen": len(new_code),
                   "coldBaseline": bool(prev and not prev.get("impl"))}
            fn = os.path.join(args.out, "upgrade-%s-%s-%d.json" % (chain, proxy[-6:], blk))
            with open(fn, "w") as f:
                json.dump(hit, f, indent=2)
            new_hits.append(hit)
            state[rk] = {"impl": new_impl, "block": blk}
    with open(args.state, "w") as f:
        json.dump(state, f, indent=2)
    print(json.dumps({"latest": latest, "newUpgrades": len(new_hits), "hits": new_hits}, indent=2))
    return 2 if new_hits else 0


if __name__ == "__main__":
    sys.exit(main())
