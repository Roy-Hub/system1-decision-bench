#!/usr/bin/env python3
"""Round-2 benchmark: 4 CPU decision models x 3 datasets + stability checks.

Datasets:
  round1    - golden set from round 1 (dataset/)
  dataset2  - round-2 golden set (dataset2/)
  external  - jev-bench banking77 test split (dataset_external/), 1000 rows

Checks:
  - accuracy, order-flip fragility, latency p50/p95, RAM, confidence gate
  - 3x shuffled-order repeats per model per dataset (accuracy spread)
  - bootstrap 95% CI on the Tiny-vs-Small gap (computed in analyze2.py)

Usage: python bench2.py [quyet|quyet-small|von|laya|all]
Run from the repo root, or set S1_BENCH_WS to the repo root.
"""
import csv, json, os, sys, time, statistics, resource, subprocess, random

os.environ.setdefault("OMP_NUM_THREADS", "8")
WS = os.environ.get("S1_BENCH_WS") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CRIT_AB = {"blocked": "A bot challenge or block interstitial is shown; the human page content is not visible.",
           "clean": "Normal page content rendered; no challenge or block overlay."}
INSTR = "Is the page blocked by a bot challenge or block interstitial?"

def gold_to_choice(label):
    if label == "clean": return "clean"
    if label in ("blank",): return None
    return "blocked"

def load_datasets():
    ds = {}
    for name in ("round1", "dataset2"):
        base = f"{WS}/dataset" if name == "round1" else f"{WS}/dataset2"
        rows = []
        for r in csv.DictReader(open(f"{base}/text_states.csv")):
            g = gold_to_choice(r["label"])
            if g is None: continue
            rows.append({"id": r["id"], "lane": "text", "cls": r["label"], "state": r["state"],
                         "gold": g, "crit": CRIT_AB, "instr": INSTR})
        for r in json.load(open(f"{base}/image_evidence.json")):
            g = gold_to_choice(r["label"])
            if g is None or not r.get("ocr"): continue
            rows.append({"id": r["id"], "lane": "image", "cls": r["label"], "state": r["ocr"],
                         "gold": g, "crit": CRIT_AB, "instr": INSTR})
        ds[name] = rows
    ext = []
    for line in open(f"{WS}/dataset_external/banking77_sub10_test.jsonl"):
        r = json.loads(line)
        q = json.loads(r["question"])
        ext.append({"id": r["id"], "lane": "text", "cls": r["label"], "state": r["state"],
                    "gold": r["label"], "crit": q["criteria"], "instr": q["instructions"]})
    ds["external"] = ext
    return ds

def run_pass(decide_fn, rows, reverse=False):
    """One pass over rows. Returns per-item records + latencies."""
    out, lat = [], []
    for r in rows:
        crit = r["crit"]
        if reverse:
            crit = dict(reversed(list(r["crit"].items())))
        t0 = time.perf_counter()
        c1, conf1 = decide_fn(r["state"], crit, r["instr"])
        dt = (time.perf_counter()-t0)*1000
        lat.append(dt)
        out.append({"id": r["id"], "lane": r["lane"], "cls": r["cls"], "gold": r["gold"],
                    "pred": c1, "conf": conf1})
    return out, lat

def acc(items):
    c = sum(1 for i in items if i["pred"] == i["gold"])
    return c, len(items)

def gate_table(items):
    table = []
    for th in (0.5, 0.6, 0.7, 0.8, 0.9):
        kept = [i for i in items if i["conf"] is not None and i["conf"] >= th]
        c = sum(1 for i in kept if i["pred"] == i["gold"])
        table.append({"threshold": th, "kept": len(kept),
                      "kept_pct": round(100*len(kept)/len(items), 1) if items else None,
                      "kept_acc_pct": round(100*c/len(kept), 1) if kept else None})
    return table

def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    ds = load_datasets()
    print("dataset sizes:", {k: len(v) for k, v in ds.items()}, flush=True)
    rng = random.Random(20261020)

    models = []
    if which in ("quyet", "quyet-tiny", "all"):
        import quyet
        m = quyet.load("chinhnc/Quyet-1.0-Tiny")
        def d(state, crit, instr, _m=m):
            r = _m.predict(state, {"q": {"type": "choice", "instructions": instr, "criteria": crit}})
            a = r["answers"]["q"]
            return a["choice"], a["confidence"]
        models.append(("quyet", d))
    if which in ("quyet-small", "all"):
        import quyet
        m = quyet.load("chinhnc/Quyet-1.0-Small")
        def d(state, crit, instr, _m=m):
            r = _m.predict(state, {"q": {"type": "choice", "instructions": instr, "criteria": crit}})
            a = r["answers"]["q"]
            return a["choice"], a["confidence"]
        models.append(("quyet-small", d))
    if which in ("von", "all"):
        import von
        def d(state, crit, instr):
            r = von.decide(state=state, choices=crit, instructions=instr)
            return r.choice, r.confidence
        models.append(("von", d))
    if which in ("laya", "all"):
        import laya
        a = laya.load(device="cpu")
        def d(state, crit, instr, _a=a):
            r = laya.decide(_a, state, questions={"q": {"type": "choice", "instructions": instr, "criteria": crit}})
            q = r["q"] if isinstance(r, dict) else r.answers["q"]
            return q["choice"], q.get("answer_confidence", q.get("confidence"))
        models.append(("laya", d))

    for name, decide in models:
        out = {"model": name, "datasets": {}}
        all_items, all_lat = [], []
        for dname, rows in ds.items():
            items, lat = run_pass(decide, rows, reverse=False)
            items_rev, lat_rev = run_pass(decide, rows, reverse=True)
            revmap = {i["id"]: i for i in items_rev}
            flips = sum(1 for i in items if i["pred"] != revmap[i["id"]]["pred"])
            c, n = acc(items)
            cr, _ = acc(items_rev)
            # 3 shuffled-order repeats (forward order only)
            spreads = []
            for rep in range(3):
                shuffled = rows[:]
                rng.shuffle(shuffled)
                it, _ = run_pass(decide, shuffled, reverse=False)
                cc, nn = acc(it)
                spreads.append(round(100*cc/nn, 2))
            lat_all = lat + lat_rev
            lat_all.sort()
            per_cls = {}
            for i in items:
                d0 = per_cls.setdefault(i["cls"], {"correct": 0, "n": 0})
                d0["n"] += 1
                d0["correct"] += (i["pred"] == i["gold"])
            for k in per_cls:
                v = per_cls[k]
                v["acc_pct"] = round(100*v["correct"]/v["n"], 1)
            out["datasets"][dname] = {
                "n": n, "correct": c, "acc_pct": round(100*c/n, 1),
                "correct_rev": cr, "acc_rev_pct": round(100*cr/n, 1),
                "flip_rate_pct": round(100*flips/n, 1),
                "repeat_accs": spreads,
                "lat_p50_ms": round(statistics.median(lat_all), 1),
                "lat_p95_ms": round(lat_all[int(len(lat_all)*0.95)-1], 1),
                "gate": gate_table(items),
                "per_class": per_cls,
                "per_item": items,
            }
            all_items += items
            print(f"{name} {dname}: acc={out['datasets'][dname]['acc_pct']}% repeats={spreads}", flush=True)
        # pooled across datasets
        c, n = acc(all_items)
        out["pooled"] = {"n": n, "correct": c, "acc_pct": round(100*c/n, 1)}
        ram = subprocess.run(["ps", "-o", "rss=", "-p", str(os.getpid())], capture_output=True, text=True).stdout.strip()
        out["ram_mb_now"] = int(ram)//1024 if ram.isdigit() else ram
        os.makedirs(f"{WS}/results2", exist_ok=True)
        json.dump(out, open(f"{WS}/results2/{name}.json", "w"), indent=1)
        print(f"{name} pooled: {out['pooled']} ram={out['ram_mb_now']}MB", flush=True)

if __name__ == "__main__":
    main()
