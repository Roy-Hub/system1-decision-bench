# System 1 Models On Our Own Data  -  Benchmark Report

Date: 2026-10-17. Box: AMD Ryzen AI Max+ 395, 32 threads, 121 GB RAM, CPU only. Scope: Von (wfzyx), Quyet-1.0-Tiny (chinhnc), Laya (ConvAI). Task: decide if these models are useful for the web-exploration stack. All three ran on this box. No profile config was changed.

## 1. What we built

Golden dataset. Two lanes.

- Image lane: 30 screenshots. Labels: 19 clean, 3 PerimeterX press-and-hold, 2 Turnstile/Cloudflare interstitial, 2 reCAPTCHA, 2 other captcha (MTCaptcha, GeeTest), 1 DataDome block, 1 blank/ambiguous. Sources: fresh Camofox captures plus saved evidence from the bot-block investigations. Every label was read back and verified by file review. Log: dataset/labels.csv.
- Text lane: 40 session-state records (JSON: status codes, server headers, cookies, DOM/body markers). Balanced: 6 DataDome, 6 PerimeterX, 6 Turnstile, 6 reCAPTCHA, 14 clean, 2 blank. Sources: live curl header checks, the bot-blocks-by-profile report, the Etsy addendum, and fresh captures.
- Image lane uses the evidence-bridge pattern. Local OCR (RapidOCR, ONNX, CPU) extracts visible text. The decision model then answers one typed choice question on that text: "Is the page blocked by a bot challenge or block interstitial?" Options: blocked / clean. Raw pixels never reach the model.
- Binary accuracy excludes the blank/ambiguous cases (1 image, 2 text).

## 2. Method

- One choice question, two options, per case. Same instructions both lanes.
- Fragility: the same call with the option order reversed. Flip rate = how often the answer changed.
- Latency: wall time per call, cold model loaded once, p50/p95 over all calls (both orders).
- RAM: process RSS after the run.
- Confidence gate: sweep the model's own confidence 0.5–0.9. Report kept volume and kept accuracy.

## 3. Results

Headline (binary accuracy on 67 decidable cases, 38 text + 29 image; flip = answer change when option order reverses; CPU on this box):

|Model|Accuracy|Accuracy (order flipped)|Flip rate|p50 ms|p95 ms|RAM MB|
|---|---|---|---|---|---|---|
|Quyet-1.0-Tiny|82.1%|73.1%|11.9%|104|256|1837|
|Von 1.3|65.7%|65.7%|0.0%|394|2294|2357|
|Laya|64.2%|53.7%|13.4%|390|1115|2429|

Per-lane split (accuracy, order flipped in parentheses):

|Model|Text lane (n=38)|Image lane via OCR bridge (n=29)|
|---|---|---|
|Quyet-1.0-Tiny|81.6% (76.3%)|82.8% (69.0%)|
|Von 1.3|76.3% (76.3%)|51.7% (51.7%)|
|Laya|60.5% (55.3%)|69.0% (51.7%)|

Confidence gate (kept volume / kept accuracy, all cases):

|Threshold|Quyet|Von|Laya|
|---|---|---|---|
|>=0.5|100% / 82.1%|6.0% / 100%|100% / 64.2%|
|>=0.6|46.3% / 90.3%|1.5% / 100%|65.7% / 65.9%|
|>=0.7|6.0% / 100%|0%|44.8% / 63.3%|
|>=0.8|0%|0%|25.4% / 76.5%|
|>=0.9|0%|0%|4.5% / 100%|

## 4. What the numbers say

- Quyet-Tiny is the best overall on our data: 82% binary accuracy, and its gate works  -  at confidence >=0.6 it keeps 46% of cases at 90% accuracy. That matches its published calibration strength.
- Von was order-stable (0% flip) but weak here (66%), and it collapsed in the image lane (52%). Its confidence never left the low band, so its gate kept almost nothing. Von's own README warns: out of domain, the ranking breaks and only labels plus a refit fix it. Our dataset is out of domain.
- Laya was the weakest (64%) and the most order-fragile in the image lane (24% flip). This matches the published finding that Laya changes 30% of answers when option order flips.
- The OCR bridge caps the image lane. Quyet held up (83%), but Von fell to chance level. OCR text loses layout cues  -  a modal overlay reads the same as body text. The bridge works only on top of a model with strong calibration.
- Small n. 30 images and 40 text states are a feasibility sample, not a verdict. Treat single-case differences as noise; treat the ordering (Quyet > Von ≈ Laya) and the gate shape as the signal.

## 5. Go / no-go

- Text lane: GO with Quyet-1.0-Tiny as primary, confidence gate >=0.6 (keeps ~46% at ~90% accuracy), escalate the rest to the System 2 tier. Von stays as challenger only after a refit on our labels (von calibrate labels.jsonl). Laya: no-go as primary; keep as fallback only.
- Image lane: CONDITIONAL GO, Quyet only. It scored 83% through the OCR bridge and held up across order flips (14% flip). Von and Laya are no-go on this lane. The gate on image evidence is thin (small n)  -  run it in shadow mode first and re-fit the threshold once the image set passes ~100 labeled cases. A native vision decision model (PixelJev pattern) remains the long-term fix.
- Ceiling check (optional): skipped. No Jev API key on this box. The published Jev reference (71.09 JevBench) stays the calibration target.

## 6. Practical rules if we ship the text lane

1. Keep option sets small and distinct. Two clear options beat five fuzzy ones.
2. Feed the model the detector's structured state, not raw page dumps.
3. Gate at >=0.6 on Quyet. Anything below goes to System 2.
4. Re-measure the gate after any label-set change. A threshold is only valid on the data that made it.
5. Watch the flip rate in production. A rising flip rate means the input drifted out of domain.

## Artifacts

- dataset/labels.csv  -  30 image labels, human-readable verification per row.
- dataset/text_states.csv  -  40 text states with labels and sources.
- dataset/image_evidence.json  -  OCR evidence per image.
- results/{quyet,von,laya}.json  -  per-item predictions, confidences, flips, gate sweeps.
- scripts/bench.py  -  the harness (reproducible).
