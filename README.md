# System 1 Decision Model Benchmark

Benchmark small "System 1" decision models on golden datasets of bot-challenge
and clean-page states, plus an external public decision set. Built for a
web-exploration stack that must decide, fast and on CPU, whether a page is
blocked by a bot challenge.

Round 1 run: 2026-10-17 (67 cases). Round 2 run: 2026-10-20 (1222 cases across
3 datasets, 4 models, stability checks). Box: AMD Ryzen AI Max+ 395, 32
threads, 121 GB RAM, CPU only.

## Models

| Model | Params | Type | Runs on | Package | Checkpoint |
|---|---|---|---|---|---|
| Quyet-1.0-Tiny | 180M | Encoder (mmBERT-small, 16 layers) | CPU, ~6 ms claimed | `quyet` (1.0.2) | `chinhnc/Quyet-1.0-Tiny` |
| Quyet-1.0-Small | 330M | Encoder | CPU | `quyet` (1.0.2) | `chinhnc/Quyet-1.0-Small` |
| Von 1.3 | 395M | Encoder (ModernBERT, 28 layers, F32) | CPU | `von_sdk` (1.3.7) | `wfzyx/von` (`option_marker.pt`) |
| Laya | 421M | Encoder (F16, calibrated heads) | CPU | `laya` (0.4.11) | ConvAI Laya checkpoint |

All four are Apache-2.0 and run on CPU.

Not benched (same Quyet family, for context):

| Model | Params | Type | Runs on |
|---|---|---|---|
| Quyet-1.0-Small-EN | 150M | Encoder | CPU or any GPU |
| Quyet-1.0-Medium | 4.7B | LLM (Qwen3.5) | 16 GB GPU |
| Quyet-1.0-Large | 31.3B | LLM (Gemma 4) | 80 GB GPU |

## Datasets

- `dataset/` (round 1): 40 text states + 30 screenshots (67 decidable cases).
  See round-1 `report.md`.
- `dataset2/` (round 2): 155 cases. 151 text states + 4 screenshots.
  Sources: existing evidence only (no new probes) — session snapshots mined
  from profile session DBs, live curl header checks, bot-block report and
  Sam's Club forensics patterns, and vision-verified screenshots. Labels and
  verification per row in `dataset2/labels.csv`. Cookie names only, no values.
  Logged-in surfaces withheld. 110 clean, 41 blocked (DataDome 4, PerimeterX
  11, Turnstile 7, reCAPTCHA 9, other 10). Builder: `scripts/build_dataset2.py`.
- `dataset_external/`: jev-bench banking77 subset (external public decision
  set, 1000 rows, 10 intents x 100). Same typed-choice shape as our lanes.
  Shows generalization; our sets show domain fit. Provenance:
  `dataset_external/README.md`.

## Method

- One binary choice question per case: "Is the page blocked by a bot challenge
  or block interstitial?" Options: blocked / clean.
- Fragility: same call with option order reversed. Flip rate = share of answers
  that changed.
- Stability: 3 shuffled-order repeats per model per dataset; report per-run
  accuracy spread.
- Significance: paired bootstrap (10k resamples) 95% CI on the Tiny-vs-Small
  accuracy gap per dataset and pooled.
- Latency: wall time per call, model loaded once, p50/p95 over all calls.
- RAM: process RSS after the run.
- Confidence gate: sweep the model's own confidence 0.5-0.9; report kept
  volume and kept accuracy.

## Round-2 results

Accuracy (flipped-order in parentheses), n = 67 / 155 / 1000 / 1222:

| Model | round1 | dataset2 | external | pooled |
|---|---|---|---|---|
| Quyet-1.0-Tiny | 82.1% (73.1%) | 78.7% (50.3%) | 95.0% (94.7%) | 92.2% |
| Quyet-1.0-Small | 77.6% (77.6%) | 87.7% (75.5%) | 94.4% (96.1%) | 92.6% |
| Von 1.3 | 67.2% (67.2%) | 60.0% (60.0%) | 95.2% (95.2%) | 89.2% |
| Laya | 64.2% (53.7%) | 46.5% (26.5%) | 83.0% (82.4%) | 77.3% |

Flip rates (round1 / dataset2 / external): Tiny 11.9 / 43.9 / 4.2;
Small 17.9 / 16.1 / 5.0; Von 0.0 / 0.0 / 2.4; Laya 13.4 / 26.5 / 8.2.

Stability: all four models are deterministic — the 3 shuffled-order repeats
give identical accuracy on every dataset (spread 0.00 pp). Order of cases does
not matter; order of OPTIONS does (flip rates above).

Latency p50/p95 ms (per dataset): Tiny 110-125 / 170-300; Small 195-212 /
380-900; Von 282-697 / 524-2808; Laya 316-397 / 474-1081. RAM with all models
loaded in one process: 4.2-4.8 GB.

Confidence gate at >=0.6 (kept / kept accuracy, dataset2):
Tiny 45.2% / 80.0%; Small 38.1% / 94.9%; external: Tiny 96.7% / 96.7%,
Small 97.9% / 95.3%.

Tiny-vs-Small paired bootstrap (accuracy gap, percentage points):

| Dataset | Gap (Tiny - Small) | 95% CI | p | Verdict |
|---|---|---|---|---|
| round1 (n=67) | +4.48 | [-7.46, +16.42] | 0.40 | not significant |
| dataset2 (n=155) | -9.03 | [-16.13, -1.94] | 0.017 | Small better |
| external (n=1000) | +0.62 | [-0.93, +2.16] | 0.37 | not significant |
| pooled (n=1222) | -0.42 | [-2.09, +1.26] | 0.66 | not significant |

## Verdict (round 2)

The round-1 "Tiny beats Small" result does NOT survive. It was noise at
n=67 (gap +4.5 pp, CI spans zero). On the larger round-2 in-domain set,
Small beats Tiny by 9.0 pp and the gap is significant (p=0.017). Pooled over
all 1222 cases the two are a statistical tie, but Small wins where it
matters most:

- dataset2 blocked classes: Small 60-90% per vendor vs Tiny 22-67%.
- Order fragility on dataset2: Tiny flips 43.9% of answers when option order
  reverses; Small flips 16.1%.
- Gate quality on dataset2: at >=0.6, Small keeps 38% of cases at 94.9%
  accuracy; Tiny keeps 45% at 80.0%.

Decision update (recommendation, pending Mathew's approval): switch the text
lane primary to Quyet-1.0-Small (gate >=0.6). Tiny stays as the cheap fallback
where latency dominates (p50 ~110 ms vs ~200 ms). Von and Laya stay no-go as
primary on our domain (Von 60%, Laya 46.5% on dataset2); both are strong on
the external set (95.2% / 83.0%), which confirms the round-1 diagnosis: they
are out of domain on bot-challenge states, not broken. The external set also
shows all four models generalize well on in-distribution intent routing
(83-95%).

Round-1 numbers reproduce exactly for Tiny and Laya; Von moved 1 case
(65.7 -> 67.2%) with the current von-1.3.0 weights.

## Reproduce

```
python -m venv venv && . venv/bin/activate
pip install -r requirements.txt
python scripts/bench.py all        # round 1
python scripts/bench2.py all       # round 2: 4 models x 3 datasets + repeats
python scripts/analyze2.py         # tables + bootstrap CIs -> results2/summary.json
```

First run downloads model weights from Hugging Face Hub (set `HF_TOKEN` to
avoid rate limits). Expect a few minutes of model loading on CPU. The round-2
run takes roughly 2 hours on this box (Von and Laya are slow on CPU).

## Layout

```
scripts/bench.py             round-1 benchmark driver (von|quyet|laya|all)
scripts/bench2.py            round-2 driver (4 models x 3 datasets + repeats)
scripts/analyze2.py          round-2 tables + paired bootstrap CIs
scripts/build_dataset2.py    dataset2 builder (session-DB mining + rules)
dataset/                     round-1 golden set
dataset2/                    round-2 golden set (155 cases) + images
dataset_external/            jev-bench banking77 subset (1000 rows)
results/*.json               round-1 per-model scores
results2/*.json              round-2 per-model scores, gates, repeats, summary
report.md                    round-1 STE-style benchmark report
```
