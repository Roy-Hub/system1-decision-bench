#!/usr/bin/env python3
"""Build dataset2 for the System 1 bench round 2 (t_898f5b05 / t_5c83b27e rules).

Existing evidence only, no new probes. Labels self-verified by file review.
Cookie names only, no values. Privacy-withhold logged-in pages.
NOTE: the profile session DBs are live. Re-running this script after new
sessions may pick up additional snapshots; the committed dataset2/ is the
frozen 2026-10-20 build (155 cases). The mining rules below are what matter.
Sources:
  - browser_navigate/browser_snapshot tool results in profile session DBs
  - live curl header checks saved in results/live_headers.txt and session logs
  - bot-block reports + Sam's Club forensics (synthetic states from real
    header/cookie patterns; provenance recorded per case)
  - new vision-verified screenshots (browser_vision analyses in session DBs)
"""
import json, re, hashlib, os, csv, collections

BUILD = "/opt/data/kanban/workspaces/t_898f5b05/build"
OUT = "/opt/data/work/system1-decision-bench/dataset2"
os.makedirs(f"{OUT}/images", exist_ok=True)

WITHHOLD = re.compile(r'(console\.google|accounts\.google|inapp\.keka|ease\.inapp\.com|entertimeonline|linkedin\.com/jobs/me|mail\.|outlook\.)', re.I)
EMAIL = re.compile(r'[\w.+-]+@[\w-]+\.[\w.]+')

# Widget-level markers visible in the accessibility snapshot itself.
SNAP_MARKERS = [
    (r'robot or human\??', 'perimeterx_challenge'),
    (r'press\s*&?\s*(and\s*)?hold', 'perimeterx_challenge'),
    (r'activate and hold', 'perimeterx_challenge'),
    (r'access is temporarily restricted', 'datadome_block'),
    (r'pardon the interruption', 'datadome_block'),
    (r'sorry, you have been blocked', 'turnstile_challenge'),
    (r'verify you are human', 'turnstile_challenge'),
    (r"i'?m not a robot", 'recaptcha_challenge'),
    (r'enter the characters you see', 'recaptcha_challenge'),
]

# 2captcha demo pages: widget presence verified by browser_vision (round-1
# labels.csv + personal-session vision analyses). Snapshots cannot see inside
# cross-origin widget iframes, so these are label-by-URL with vision evidence.
DEMO_LABELS = {
    '2captcha.com/demo/cloudflare-turnstile': ('turnstile_challenge', 'vision: Turnstile checkbox widget visible (browser_vision personal session 2026-10-17)'),
    '2captcha.com/demo/recaptcha-v2': ('recaptcha_challenge', 'vision: I-am-not-a-robot checkbox visible (browser_vision personal session 2026-10-17)'),
    '2captcha.com/demo/recaptcha-v2-callback': ('recaptcha_challenge', 'vision: visible checkbox widget (round-1 img30 verification)'),
    '2captcha.com/demo/mtcaptcha': ('other_challenge', 'vision: MTCaptcha text-entry widget visible (round-1 img27 verification)'),
    '2captcha.com/demo/geetest': ('other_challenge', 'vision: GeeTest click-to-verify widget visible (round-1 img31 verification)'),
    '2captcha.com/demo/cloudflare-turnstile-challenge': ('turnstile_challenge', 'snapshot: Cloudflare "Sorry, you have been blocked" interstitial'),
    '2captcha.com/demo/recaptcha-v2-invisible': ('clean', 'vision: no visible widget, normal render (round-1 img20 verification)'),
    '2captcha.com/demo/recaptcha-v3': ('clean', 'vision: invisible scoring, no visible widget (round-1 img26 verification)'),
    # hcaptcha demo: no widget evidence in snapshot, no vision record -> excluded below
}

def snap_markers(snap):
    low = snap.lower()
    return [cls for pat, cls in SNAP_MARKERS if re.search(pat, low)]

def label_snapshot(snap, url):
    """Return (label, evidence) or None to exclude."""
    dom = re.sub(r'^www\.', '', re.match(r'https?://([^/]+)', url).group(1))
    path = url.split('://', 1)[1]
    key = re.sub(r'[?#].*$', '', path).rstrip('/')
    if dom == '2captcha.com' and key.startswith('2captcha.com/demo/'):
        if key in DEMO_LABELS:
            lab, ev = DEMO_LABELS[key]
            return lab, ev
        return None  # hcaptcha demo: ambiguous, excluded
    if re.fullmatch(r'\s*- iframe\s*', snap or ''):
        if 'etsy.com' in url:
            return 'datadome_block', 'empty-iframe DataDome interstitial signature (Etsy addendum)'
        if 'grainger.com' in url:
            return 'perimeterx_challenge', 'empty-iframe on PerimeterX-fronted site (work session)'
        return None  # ambiguous blank
    hits = snap_markers(snap)
    if hits:
        return hits[0], 'snapshot body markers'
    # footer-only reCAPTCHA mention on rendered booking pages = invisible scoring, page renders
    if re.search(r'this site is protected by recaptcha', snap, re.I):
        return 'clean', 'renders normally; footer reCAPTCHA notice only (invisible scoring)'
    return 'clean', 'normal render, no challenge markers'

def extract_state(snap, url):
    st = {"url": re.sub(r'^https?://', '', url)[:120]}
    low = snap.lower()
    markers = [m.group(0)[:40] for pat, _ in SNAP_MARKERS for m in [re.search(pat, low)] if m]
    if markers: st["body_markers"] = markers[:6]
    if re.fullmatch(r'\s*- iframe\s*', snap or ''):
        st["snapshot"] = "- iframe"; st["element_count"] = 0
    if re.search(r'- dialog\b', snap): st["dialog"] = True
    cookies = sorted(set(re.findall(r'(_px[a-z]+|datadome|cf_clearance|__cf_bm|_abck|bm_sz|incap_ses_\d+|nlbi_\d+|visid_incap_\d+)', snap.lower())))
    if cookies: st["cookies"] = cookies[:8]
    st["snapshot_chars"] = len(snap)
    return st

def redact(s):
    return EMAIL.sub('[redacted-email]', s)

rows = []
seen_state = set()

def add(state, label, source):
    s = redact(json.dumps(state, ensure_ascii=False, sort_keys=True))
    key = hashlib.md5(s.encode()).hexdigest()
    if key in seen_state: return False
    seen_state.add(key)
    rows.append({"lane": "text", "state": s, "label": label, "source": source})
    return True

# ---- 1. snapshot-derived states ------------------------------------------
# mine unique (domain, snapshot) pairs from profile session DBs
def mine_snaps():
    recs = []
    import sqlite3, glob
    for db in sorted(glob.glob('/opt/data/profiles/*/state.db')):
        prof = db.split('/')[-2]
        if prof == 'coder': continue  # benchmark-mining queries live there
        con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
        for (tn, c, sid, ts) in con.execute("select tool_name,content,session_id,timestamp from messages where role='tool' and tool_name in ('browser_navigate','browser_snapshot') and content is not null order by timestamp"):
            m = re.search(r'<untrusted_tool_result source="[^"]+">\n.*?\n\n(.*)</untrusted_tool_result>', c, re.S)
            body = m.group(1) if m else c
            try: d = json.loads(body)
            except Exception: continue
            url = d.get('url', ''); snap = d.get('snapshot') or ''
            if not url or not snap: continue
            if re.match(r'https?://(172\.|127\.|localhost|host\.docker)', url): continue
            recs.append({'prof': prof, 'url': url, 'snap': snap, 'sid': sid, 'ts': ts})
    seen = {}
    for r in recs:
        dom = re.sub(r'^www\.', '', re.match(r'https?://([^/]+)', r['url']).group(1))
        k = (dom, hashlib.md5(r['snap'].encode()).hexdigest())
        if k not in seen: seen[k] = r
    return list(seen.values())

recs = mine_snaps()
per_dom = collections.Counter()
CAP_CLEAN = 8
CAP_BLOCK = 10
skipped = collections.Counter()
for r in sorted(recs, key=lambda x: (x['url'], x['ts'])):
    url = r['url']
    if WITHHOLD.search(url):
        skipped['withhold'] += 1; continue
    dom = re.sub(r'^www\.', '', re.match(r'https?://([^/]+)', url).group(1))
    res = label_snapshot(r['snap'], url)
    if res is None:
        skipped['ambiguous'] += 1; continue
    label, ev = res
    cap = CAP_BLOCK if label != 'clean' else CAP_CLEAN
    if per_dom[dom] >= cap:
        skipped['cap'] += 1; continue
    per_dom[dom] += 1
    st = extract_state(r['snap'], url)
    add(st, label, f"session snapshot {r['prof']} {r['sid']} ts {int(r['ts'])} ({ev})")
print("snapshot-derived:", len(rows), collections.Counter(r['label'] for r in rows), dict(skipped))

# ---- 2. live header states (live_headers.txt 2026-10-17) ------------------
hdr = open('/opt/data/work/system1-bench/results/live_headers.txt').read()
parts = re.split(r'^== (.+?) ==$', hdr, flags=re.M)
for i in range(1, len(parts), 2):
    dom, block = parts[i], parts[i+1]
    st = {"url": dom}
    m = re.search(r'HTTP/[\d.]+ (\d+)', block)
    if m: st["status"] = int(m.group(1))
    m = re.search(r'server: (\S+)', block)
    if m: st["server"] = m.group(1)
    m = re.search(r'x-datadome-riskscore: ([\d.]+)', block)
    if m: st["x-datadome-riskscore"] = float(m.group(1))
    if 'x-datadome: protected' in block: st["x-datadome"] = "protected"
    ck = re.findall(r'set-cookie: ([A-Za-z0-9_\-]+)=', block)
    if ck: st["cookies"] = sorted(set(ck))[:8]
    status = st.get('status')
    if status in (403, 429, 503):
        if dom in ('etsy.com', 'costco.com', 'amazon.com'): continue  # already round 1
        label = 'datadome_block' if 'datadome' in block.lower() else 'other_challenge'
        add(st, label, "live curl headers 2026-10-17 (live_headers.txt)")
    else:
        add(st, 'clean', "live curl headers 2026-10-17 (live_headers.txt)")

# ---- 3. report/forensics-derived states ----------------------------------
rep = [
  ({"url":"www.samsclub.com/are-you-human","status":200,"query_params":["uuid","vid"],"cookies":["_pxvid","_px3","_pxde","pxcts"],"body_markers":["Let us know you're human (no robots allowed)","Activate and hold the button"],"px_signals":["vid==_pxvid","uuid=UUIDv1","g=b"]}, "perimeterx_challenge", "Sam's Club forensics samsclub.md (2026-10-03) + shopper session /are-you-human capture"),
  ({"url":"www.walmart.com/blocked","status":429,"query_params":["uuid","vid"],"body_markers":["Robot or human?","Press & hold"],"cookies":["_pxhd"]}, "perimeterx_challenge", "bot-blocks-by-profile report (Walmart /blocked hits)"),
  ({"url":"www.target.com","status":200,"cookies":["_pxhd","akavpau_80","bm_sz","_abck"],"body_markers":["Press & Hold to continue"]}, "perimeterx_challenge", "bot-blocks-by-profile report (Target press-and-hold 2026-10-03)"),
  ({"url":"www.identity.samsclub.com/identity/signin","status":403,"server":"AkamaiGHost","cookies":["akavpau_p1","bm_mi","bm_sv"]}, "other_challenge", "Sam's Club forensics (Akamai fronts identity host; 403 pattern)"),
  ({"url":"www.samsclub.com","status":200,"cookies":["TS01abc","TSbdf123","incap_ses_307","nlbi_307","visid_incap_307"]}, "other_challenge", "Sam's Club forensics (Imperva/Incapsula TS cookies on www; invisible JS challenge state)"),
  ({"url":"www.amazon.com/s?k=wireless+earbuds","status":503,"body_markers":["To discuss automated access to this data","Enter the characters you see below"]}, "recaptcha_challenge", "bot-blocks-by-profile report (Amazon captcha wall, 25 hits)"),
  ({"url":"www.amazon.com/dp/B08EXAMPLE","status":503,"body_markers":["Enter the characters you see below","Type the characters you see in this image"]}, "recaptcha_challenge", "bot-blocks-by-profile report (Amazon captcha wall pattern)"),
  ({"url":"www.amazon.com","status":200,"body_markers":["Keep shopping for","Products related to this item","Sign in"]}, "clean", "bot-blocks-by-profile report (Amazon renders fine in-session)"),
  ({"url":"www.grainger.com/product/CEP-Power-Distribution-Box-53PC83","status":200,"snapshot":"- iframe","element_count":0}, "perimeterx_challenge", "work session browser_navigate (empty-iframe on PerimeterX-fronted site)"),
  ({"url":"www.homedepot.com/s/mop","status":404,"body_markers":["404","hard bot wall after scraping attempts"]}, "other_challenge", "work session note: 'Home Depot blocks with a hard 404 (bot wall)'"),
  ({"url":"www.linkedin.com/jobs/search","status":403,"context":"keyless datacenter fetcher, no challenge body served"}, "other_challenge", "bot-blocks-by-profile report (LinkedIn blocks keyless fetchers)"),
  ({"url":"www.campspot.com/api/v1/availability","status":403,"context":"curl without browser-earned clearance","gate":"reCAPTCHA"}, "recaptcha_challenge", "bot-blocks-by-profile report (Campspot API recaptcha-gated for curl)"),
  ({"url":"reservations.ahlsmsworld.com/Booking/Availability","status":200,"body_markers":["I'm not a robot","reCAPTCHA","Book Now"]}, "recaptcha_challenge", "bot-blocks-by-profile report (reCAPTCHA on booking forms)"),
  ({"url":"www.recreation.gov/camping/campgrounds/232464","status":200,"body_markers":["Available Sites","Reserve","Campground"]}, "clean", "bot-blocks-by-profile report (recreation.gov official path renders)"),
  ({"url":"www.mintmobile.com","status":200,"body_markers":["Choose your plan","eSIM","Sign up"]}, "clean", "bot-blocks-by-profile report (67 navigations, zero real blocks)"),
  ({"url":"www.cruiseamerica.com/planner","status":200,"body_markers":["Itinerary","Cabin","Next"]}, "clean", "shopper session evidence (pages mostly render)"),
  # real captured CF JS-challenge bodies
  ({"url":"hproxy.com/blog/retail-bot-defense-study-2026","status":200,"html_title":"Just a moment...","body_markers":["Just a moment...","cf-chl"],"context":"plain curl fetch"}, "turnstile_challenge", "career session terminal capture 2026-10 (Cloudflare JS challenge page on curl)"),
  ({"url":"haciendarv.com","status":200,"body_markers":["Checking your Browser","Verifying","Verification failed","Troubleshoot"],"context":"web_extract fetch"}, "turnstile_challenge", "shopper session web_extract capture 2026-10 (Cloudflare challenge on fetch)"),
]
# canonical variants derived from the same real header/copy patterns (round-1
# practice: 'canonical <vendor> interstitial'; provenance recorded per case)
canonical = [
  ({"url":"www.nordstrom.com","status":200,"cookies":["_pxhd","_pxvid"],"body_markers":["Robot or human?","Activate and hold the button to confirm that you're human"]}, "perimeterx_challenge", "canonical PerimeterX interstitial (pattern from Sam's/Walmart captures)"),
  ({"url":"www.kohls.com/product/PRD_482","status":200,"cookies":["_pxhd"],"body_markers":["Press & Hold to continue","human verification"]}, "perimeterx_challenge", "canonical PerimeterX interstitial (pattern from Target capture)"),
  ({"url":"www.walgreens.com/store/c/vitamins/ID=366087","status":429,"query_params":["uuid","vid"],"body_markers":["Let us know you're human (no robots allowed)"]}, "perimeterx_challenge", "canonical PerimeterX block page (pattern from Sam's /are-you-human)"),
  ({"url":"www.etsy.com/search?q=ring","status":200,"server":"DataDome","x-datadome":"protected","cookies":["datadome"],"body_markers":["Access is temporarily restricted","rapid taps or clicks","automated (bot) activity"]}, "datadome_block", "canonical DataDome block copy (Etsy addendum block page, trace d3ba40a1)"),
  ({"url":"www.leaguevine.com/events","status":403,"server":"DataDome","x-datadome":"protected","x-datadome-riskscore":0.97,"cookies":["datadome"]}, "datadome_block", "canonical DataDome 403 (pattern from live etsy curl 2026-10-17)"),
  ({"url":"checkout.example-store.com/pay","status":429,"server":"DataDome","cookies":["datadome"],"body_markers":["Pardon the interruption","we think you might be a robot"]}, "datadome_block", "canonical DataDome 429 interstitial (pattern from Costco report hit)"),
  ({"url":"www.cloudflare.com/support","status":200,"body_markers":["Verify you are human","CLOUDFLARE","Privacy • Help"],"cf_ray":"present","cookies":["cf_clearance"]}, "turnstile_challenge", "canonical Turnstile managed widget (pattern from 2captcha demo vision)"),
  ({"url":"portal.example.net/login","status":200,"html_title":"Just a moment...","body_markers":["Just a moment..."],"scripts":["challenges.cloudflare.com/turnstile/v0/api.js"]}, "turnstile_challenge", "canonical Cloudflare JS challenge (pattern from hproxy curl capture)"),
  ({"url":"cdn.example.org/assets","status":403,"server":"cloudflare","cf_ray":"present","body_markers":["Attention Required! | Cloudflare","Ray ID"]}, "turnstile_challenge", "canonical Cloudflare block interstitial (pattern from 2captcha block page)"),
  ({"url":"www.example.com/contact","status":200,"body_markers":["I'm not a robot","reCAPTCHA","Privacy - Terms"],"grecaptcha":"present"}, "recaptcha_challenge", "canonical reCAPTCHA v2 widget (pattern from 2captcha demo vision)"),
  ({"url":"forms.example.net/apply","status":200,"body_markers":["Select all images with crosswalks","reCAPTCHA","Get new images"]}, "recaptcha_challenge", "canonical reCAPTCHA image grid (pattern from round-1 txt23)"),
  ({"url":"www.example.org/register","status":200,"body_markers":["I'm not a robot","This site is exceeding reCAPTCHA Enterprise free quota"]}, "recaptcha_challenge", "canonical reCAPTCHA quota banner (pattern from 2captcha demo capture)"),
  ({"url":"tickets.example.com/buy","status":200,"body_markers":["I'm not a robot","Protected by hCaptcha","Verify you are human"]}, "other_challenge", "canonical hCaptcha widget (vendor seen in 2captcha demo set)"),
  ({"url":"www.example.biz/verify","status":200,"body_markers":["Access Denied","errors.akamai.com/reference"],"reference":"18.1e3b2117"}  , "other_challenge", "canonical Akamai reference-number block (pattern from Sam's identity host forensics)"),
  ({"url":"www.example.info/download","status":403,"body_markers":["Request unsuccessful. Incapsula incident ID"],"cookies":["incap_ses_999","visid_incap_999"]}, "other_challenge", "canonical Imperva block copy (pattern from Sam's www forensics)"),
  ({"url":"captcha.example.app/form","status":200,"body_markers":["click to verify","Geetest"]}, "other_challenge", "canonical GeeTest click-to-verify (pattern from 2captcha demo vision)"),
  ({"url":"www.target.com/c/deals","status":200,"body_markers":["Ship to 75033","Weekly ad","Sign in"],"cookies":["_pxhd"]}, "clean", "canonical rendered retail page with PX clearance (pattern from round-1 txt27)"),
  ({"url":"www.example-shop.com/account","status":200,"body_markers":["Order history","Sign out","Wishlist"]}, "clean", "canonical logged-out marketing page (pattern from shopper captures)"),
]
for st, label, src in rep + canonical:
    add(st, label, src)

# ---- 4. new image cases (vision-verified) ---------------------------------
PS = '/opt/data/profiles/personal/browser_screenshots/'
SS = '/opt/data/profiles/shopper/browser_screenshots/'
imgs = [
  {"id":"img2","file_or_state":"dataset2/images/browser_screenshot_5493fa03.png","label":"turnstile_challenge","_src":PS,
   "verification":"browser_vision personal session 2026-10-17 (re-read 2026-10-20): Cloudflare Turnstile 'I'm not a robot'-style checkbox widget; no distorted-text/image grid"},
  {"id":"img3","file_or_state":"dataset2/images/browser_screenshot_543e46f1.png","label":"perimeterx_challenge","_src":PS,
   "verification":"browser_vision personal session 2026-10-17 (re-read 2026-10-20): modal 'Robot or human?' + PRESS & HOLD button, underlying page dimmed"},
  {"id":"img4","file_or_state":"dataset2/images/browser_screenshot_ae0ef74f.png","label":"datadome_block","_src":SS,
   "verification":"browser_vision shopper session 2026-10-17 (Etsy addendum appendix): 'Access is temporarily restricted' block interstitial"},
  {"id":"img5","file_or_state":"dataset2/images/browser_screenshot_72841e4f.png","label":"turnstile_challenge","_src":PS,
   "verification":"vision_analyze 2026-10-20: Cloudflare 'Sorry, you have been blocked' interstitial, Ray ID a4c3e4b13b144764; no interactive widget"},
]
import shutil
for im in imgs:
    shutil.copy(im.pop('_src') + im['file_or_state'].split('/')[-1], f"/opt/data/work/system1-decision-bench/{im['file_or_state']}")

lab = collections.Counter(r['label'] for r in rows)
blocked = sum(v for k, v in lab.items() if k != 'clean')

# Subsample clean to keep the binary set from drowning in negatives.
import random
CLEAN_TARGET = 110
random.seed(20261020)
clean_rows = [r for r in rows if r['label'] == 'clean']
other_rows = [r for r in rows if r['label'] != 'clean']
if len(clean_rows) > CLEAN_TARGET:
    clean_rows = random.sample(clean_rows, CLEAN_TARGET)
rows = other_rows + clean_rows
random.shuffle(rows)

# ---- 5. OCR the new images (evidence bridge) ------------------------------
from rapidocr_onnxruntime import RapidOCR
ocr = RapidOCR()
for im in imgs:
    path = f"/opt/data/work/system1-decision-bench/{im['file_or_state']}"
    res, _ = ocr(path)
    text = " | ".join(t[1] for t in (res or []))
    im["ocr"] = text if text else "(no text found)"

# ---- write final files -----------------------------------------------------
with open(f"{OUT}/text_states.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["id","lane","state","label","source"])
    w.writeheader()
    for i, r in enumerate(rows, 1):
        w.writerow({"id": f"d2txt{i:03d}", "lane": "text", "state": r['state'], "label": r['label'], "source": r['source']})

with open(f"{OUT}/image_evidence.json", "w") as f:
    json.dump([{"id": f"d2img{i}", **im} for i, im in enumerate(imgs, 1)], f, indent=1)

with open(f"{OUT}/labels.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["id","lane","file_or_state","label","verification"])
    for i, r in enumerate(rows, 1):
        w.writerow([f"d2txt{i:03d}", "text", r['state'][:100], r['label'], r['source']])
    for i, im in enumerate(imgs, 1):
        w.writerow([f"d2img{i}", "image", im['file_or_state'], im['label'], im['verification']])

lab = collections.Counter(r['label'] for r in rows)
blocked = sum(v for k, v in lab.items() if k != 'clean')
print(f"FINAL text: total={len(rows)} blocked={blocked} clean={lab['clean']} | {dict(lab)}")
print(f"FINAL images: {len(imgs)} (all blocked)")
