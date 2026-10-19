# System 1 Decision Model Benchmark

Benchmark small "System 1" decision models on a golden dataset of bot-challenge
and clean-page states. Built for a web-exploration stack that must decide, fast
and on CPU, whether a page is blocked by a bot challenge.

Date of the reported run: 2026-10-17. Box: AMD Ryzen AI Max+ 395, 32 threads,
121 GB RAM, CPU only.

## Models

| Model | Package | Checkpoint |
|---|---|---|
| Quyet-1.0-Tiny | `quyet` (1.0.2) | `chinhnc/Quyet-1.0-Tiny` |
| Von 1.3 | `von_sdk` (1.3.7) | `wfzyx/von` (`option_marker.pt`) |
| Laya | `laya` (0.4.11) | ConvAI Laya checkpoint |

All three are Apache-2.0 and run on CPU.

## Dataset

- Text lane: 40 session-state records (`dataset/text_states.csv`). Each state
  is JSON: status codes, server headers, cookie names, DOM/body markers.
  Balanced across DataDome, PerimeterX, Turnstile, reCAPTCHA, clean, blank.
  Cookie names only. No cookie values. No credentials.
- Image lane: 30 screenshots (`dataset/images/`, labels in
  `dataset/image_evidence.json`). Raw pixels never reach the model. An OCR
  evidence bridge (RapidOCR, ONNX, CPU) extracts visible text first; the
  decision model answers one typed choice question on that text. The checked-in
  `image_evidence.json` holds the pre-extracted evidence, so the benchmark
  reproduces without running OCR.

## Method

- One binary choice question per case: "Is the page blocked by a bot challenge
  or block interstitial?" Options: blocked / clean.
- Fragility: same call with option order reversed. Flip rate = share of answers
  that changed.
- Latency: wall time per call, model loaded once, p50/p95 over all calls.
- RAM: process RSS after the run.
- Confidence gate: sweep the model's own confidence 0.5-0.9; report kept
  volume and kept accuracy.

## Results (headline)

Binary accuracy on 67 decidable cases (38 text + 29 image):

| Model | Accuracy | Flipped order | Flip rate | p50 ms | p95 ms | RAM MB |
|---|---|---|---|---|---|---|
| Quyet-1.0-Tiny | 82.1% | 73.1% | 11.9% | 104 | 256 | 1837 |
| Von 1.3 | 65.7% | 65.7% | 0.0% | 394 | 2294 | 2357 |
| Laya | 64.2% | 53.7% | 13.4% | 390 | 1115 | 2429 |

Confidence gate (kept volume / kept accuracy): Quyet at >=0.6 keeps 46.3% of
cases at 90.3% accuracy.

Decision: GO on the text lane with Quyet-1.0-Tiny as primary. Image lane is a
conditional GO, Quyet only, in shadow mode. Full write-up: `report.md`, plus
per-item results in `results/`.

## Reproduce

```
python -m venv venv && . venv/bin/activate
pip install -r requirements.txt
python scripts/bench.py all
```

First run downloads model weights from Hugging Face Hub (set `HF_TOKEN` to
avoid rate limits). Expect a few minutes of model loading on CPU.

## Layout

```
scripts/bench.py            benchmark driver (von|quyet|laya|all)
dataset/text_states.csv     text lane golden states
dataset/image_evidence.json OCR evidence + labels for the image lane
dataset/images/             the 30 labeled screenshots
results/*.json              per-model scores, gate tables, per-item detail
report.md                   STE-style benchmark report
```
