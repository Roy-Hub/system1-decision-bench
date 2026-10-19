#!/usr/bin/env python3
"""Benchmark Von / Quyet-Tiny / Laya on the golden dataset.
Lanes: text (JSON states) and image (OCR evidence bridge).
Measures: accuracy, latency p50/p95, RAM, option-order flip rate, confidence gate.

Usage: python bench.py [von|quyet|laya|all]
Run from the repo root, or set S1_BENCH_WS to the repo root.
Requires the model packages (see requirements.txt).
"""
import csv, json, os, sys, time, statistics, resource, subprocess

os.environ.setdefault("OMP_NUM_THREADS", "8")
WS = os.environ.get("S1_BENCH_WS") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Canonical binary decision: is the session blocked/challenged?
CRIT_AB = {"blocked": "A bot challenge or block interstitial is shown; the human page content is not visible.",
           "clean": "Normal page content rendered; no challenge or block overlay."}
CRIT_BA = {"clean": CRIT_AB["clean"], "blocked": CRIT_AB["blocked"]}
INSTR = "Is the page blocked by a bot challenge or block interstitial?"

def load_rows():
    text = list(csv.DictReader(open(f"{WS}/dataset/text_states.csv")))
    img = json.load(open(f"{WS}/dataset/image_evidence.json"))
    return text, img

def gold_to_choice(label):
    # blank/ambiguous excluded from binary accuracy
    if label == "clean": return "clean"
    if label in ("blank",): return None
    return "blocked"

def vendor_choice(label):
    return {"datadome_block":"datadome","perimeterx_challenge":"perimeterx","turnstile_challenge":"cloudflare",
            "recaptcha_challenge":"recaptcha","other_challenge":"other","clean":None,"blank":None}.get(label)

def pct(a, b): return round(100*a/b, 1) if b else None

def run_model(name, decide_fn):
    text, img = load_rows()
    results = []
    lat = []
    flip = 0; flip_n = 0
    for lane, rows, key in (("text", text, "state"), ("image", img, "ocr")):
        for r in rows:
            state = r[key]
            if not state: continue
            gold = gold_to_choice(r["label"])
            t0 = time.perf_counter()
            c1, conf1 = decide_fn(state, CRIT_AB)
            dt = (time.perf_counter()-t0)*1000
            lat.append(dt)
            t0 = time.perf_counter()
            c2, conf2 = decide_fn(state, CRIT_BA)
            dt2 = (time.perf_counter()-t0)*1000
            lat.append(dt2)
            flipped = (c1 != c2)
            if gold:
                flip_n += 1
                flip += flipped
            results.append({"lane":lane,"id":r["id"],"gold":gold or r["label"],"pred":c1,"conf":conf1,
                            "pred_rev":c2,"conf_rev":conf2,"flip":flipped})
    correct = sum(1 for r in results if r["gold"] in ("clean","blocked") and r["pred"]==r["gold"])
    n = sum(1 for r in results if r["gold"] in ("clean","blocked"))
    correct_rev = sum(1 for r in results if r["gold"] in ("clean","blocked") and r["pred_rev"]==r["gold"])
    lat.sort()
    ram = subprocess.run(["ps","-o","rss=","-p",str(os.getpid())],capture_output=True,text=True).stdout.strip()
    out = {"model":name,"n":n,"correct":correct,"acc_pct":pct(correct,n),
           "correct_rev":correct_rev,"acc_rev_pct":pct(correct_rev,n),
           "flip_rate_pct":pct(flip,flip_n),
           "lat_p50_ms":round(statistics.median(lat),1),"lat_p95_ms":round(lat[int(len(lat)*0.95)-1],1),
           "ram_mb_now":int(ram)//1024 if ram.isdigit() else ram,
           "per_item":results}
    return out

def gate_table(results):
    # confidence gate: threshold sweep on max prob of chosen option
    rows = [r for r in results if r["gold"] in ("clean","blocked")]
    table=[]
    for th in (0.5,0.6,0.7,0.8,0.9):
        kept=[r for r in rows if r["conf"]>=th]
        c=sum(1 for r in kept if r["pred"]==r["gold"])
        table.append({"threshold":th,"kept":len(kept),"kept_pct":pct(len(kept),len(rows)),
                      "kept_acc_pct":pct(c,len(kept)) if kept else None})
    return table

def main():
    which = sys.argv[1]
    all_out = {}
    if which in ("von","all"):
        import von
        def d(state, crit):
            r = von.decide(state=state, choices=crit, instructions=INSTR)
            return r.choice, r.confidence
        all_out["von"] = run_model("von", d)
    if which in ("quyet", "quyet-tiny", "quyet-small", "all"):
        import quyet
        repo = "chinhnc/Quyet-1.0-Small" if which == "quyet-small" else "chinhnc/Quyet-1.0-Tiny"
        key = "quyet-small" if which == "quyet-small" else "quyet"
        m = quyet.load(repo)
        def d(state, crit):
            r = m.predict(state, {"q":{"type":"choice","instructions":INSTR,"criteria":crit}})
            a = r["answers"]["q"]
            return a["choice"], a["confidence"]
        all_out[key] = run_model(repo, d)
    if which in ("laya","all"):
        import laya
        a = laya.load(device="cpu")
        def d(state, crit):
            r = laya.decide(a, state, questions={"q":{"type":"choice","instructions":INSTR,"criteria":crit}})
            q = r["q"] if isinstance(r, dict) else r.answers["q"]
            return q["choice"], q.get("answer_confidence", q.get("confidence"))
        all_out["laya"] = run_model("laya", d)
    for k,v in all_out.items():
        v["gate"] = gate_table(v["per_item"])
        json.dump(v, open(f"{WS}/results/{k}.json","w"), indent=1)
        print(json.dumps({x:v[x] for x in v if x!="per_item"}, indent=1))

if __name__ == "__main__":
    main()
