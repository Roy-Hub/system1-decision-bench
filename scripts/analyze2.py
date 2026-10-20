#!/usr/bin/env python3
"""Round-2 analysis: per-dataset + pooled tables, stability spread,
paired bootstrap 95% CI on the Quyet Tiny-vs-Small accuracy gap.

Usage: python analyze2.py
Reads results2/*.json, writes results2/summary.json + prints tables.
"""
import json, os, random, collections

WS = os.environ.get("S1_BENCH_WS") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS = ["quyet", "quyet-small", "von", "laya"]
DS = ["round1", "dataset2", "external"]

def load():
    out = {}
    for m in MODELS:
        p = f"{WS}/results2/{m}.json"
        if os.path.exists(p):
            out[m] = json.load(open(p))
    return out

def gold_pred_items(res, dname):
    return {i["id"]: (i["gold"], i["pred"]) for i in res["datasets"][dname]["per_item"]}

def bootstrap_gap(a, b, ids, n_boot=10000, seed=7):
    """Paired bootstrap CI on accuracy(a) - accuracy(b) over shared ids."""
    rng = random.Random(seed)
    ok_a = [1 if a[i][0] == a[i][1] else 0 for i in ids]
    ok_b = [1 if b[i][0] == b[i][1] else 0 for i in ids]
    n = len(ids)
    gaps = []
    for _ in range(n_boot):
        idx = [rng.randrange(n) for _ in range(n)]
        ga = sum(ok_a[j] for j in idx)/n
        gb = sum(ok_b[j] for j in idx)/n
        gaps.append(ga - gb)
    gaps.sort()
    lo = gaps[int(0.025*n_boot)]*100
    hi = gaps[int(0.975*n_boot)-1]*100
    obs = (sum(ok_a)-sum(ok_b))/n*100
    # two-sided bootstrap p for gap==0
    ge0 = sum(1 for g in gaps if g >= 0)/n_boot
    p = 2*min(ge0, 1-ge0); p = min(1.0, p)
    return {"obs_gap_pp": round(obs, 2), "ci95_pp": [round(lo, 2), round(hi, 2)], "p_two_sided": round(p, 4)}

def main():
    R = load()
    summary = {"models": {}, "tiny_vs_small": {}}
    for m in MODELS:
        if m not in R: continue
        row = {}
        for d in DS:
            dd = R[m]["datasets"][d]
            row[d] = {k: dd[k] for k in ("n","acc_pct","acc_rev_pct","flip_rate_pct","repeat_accs","lat_p50_ms","lat_p95_ms")}
            row[d]["per_class"] = {k: v["acc_pct"] for k, v in dd["per_class"].items()}
        row["pooled"] = R[m]["pooled"]
        row["ram_mb"] = R[m].get("ram_mb_now")
        row["gate_06"] = {d: next(g for g in R[m]["datasets"][d]["gate"] if g["threshold"] == 0.6) for d in DS}
        summary["models"][m] = row
    if "quyet" in R and "quyet-small" in R:
        for d in DS + ["pooled"]:
            if d == "pooled":
                ids = sorted(set(gold_pred_items(R["quyet"], "round1")) |
                             set(gold_pred_items(R["quyet"], "dataset2")) |
                             set(gold_pred_items(R["quyet"], "external")))
                # build merged dicts
                a, b = {}, {}
                for dd in DS:
                    a.update(gold_pred_items(R["quyet"], dd))
                    b.update(gold_pred_items(R["quyet-small"], dd))
            else:
                a = gold_pred_items(R["quyet"], d)
                b = gold_pred_items(R["quyet-small"], d)
                ids = sorted(a)
            summary["tiny_vs_small"][d] = bootstrap_gap(a, b, ids)
    json.dump(summary, open(f"{WS}/results2/summary.json", "w"), indent=1)

    # print tables
    print("== per-dataset accuracy (acc | rev | flip | repeats) ==")
    hdr = f"{'model':12s}" + "".join(f"{d:>34s}" for d in DS) + f"{'pooled':>10s}"
    print(hdr)
    for m in MODELS:
        if m not in summary["models"]: continue
        line = f"{m:12s}"
        for d in DS:
            r = summary["models"][m][d]
            line += f"{r['acc_pct']:>10.1f} |{r['acc_rev_pct']:>4.1f} |{r['flip_rate_pct']:>4.1f} |{str(r['repeat_accs']):>12s}"
        line += f"{summary['models'][m]['pooled']['acc_pct']:>10.1f}"
        print(line)
    print("\n== Tiny vs Small paired bootstrap (pp) ==")
    for d, v in summary["tiny_vs_small"].items():
        sig = "SIGNIFICANT" if v["ci95_pp"][0] > 0 or v["ci95_pp"][1] < 0 else "not significant"
        print(f"{d:10s} gap={v['obs_gap_pp']:+6.2f} CI95=[{v['ci95_pp'][0]:+.2f},{v['ci95_pp'][1]:+.2f}] p={v['p_two_sided']:.4f} {sig}")
    print("\nwrote results2/summary.json")

if __name__ == "__main__":
    main()
