"""
streamlit_app.py - LinkLens as a Streamlit app (pure Python, no JavaScript).

How Streamlit works, in one line: it re-runs this file from top to bottom every time
the user interacts with the page. So the flow below is simply:
    1. draw the form  ->  2. if the user submitted, call analyze()  ->  3. draw the result

All the real logic lives in analyzer.py and suggestions.py (shared with the Flask version).
This file only draws things. The look (space background, neon cards) is plain CSS
injected with st.markdown, and every card is a small HTML string built by a helper below.

Run locally:   streamlit run streamlit_app.py
"""
import base64
import html
import math
import random

import streamlit as st

from analyzer import analyze
from scanner import MAX_IMAGE_BYTES, analyze_message, analyze_qr_image   # NEW: QR + message checking

st.set_page_config(page_title="LinkLens", page_icon="🔍", layout="wide")

# --- colours ---------------------------------------------------------------
LEVEL_COLOR = {"safe": "#39FFB0", "caution": "#FFC531", "danger": "#FF3B6B"}
SEV_COLOR = {"high": "#FF3B6B", "medium": "#FFA21F", "low": "#29E3FF"}
SEV_BG = {"high": "rgba(255,59,107,.28)", "medium": "rgba(255,162,31,.26)", "low": "rgba(41,227,255,.20)"}
SEV_RANK = {"high": 3, "medium": 2, "low": 1}

EXAMPLES = {
    "fake PayPal": "http://paypa1-secure-login.xyz/verify/account/update",
    "raw IP": "http://185.220.101.4:8080/login.php",
    "@ trick": "https://paypal.com@evil-site.top/",
    "hidden redirect": "http://x8f3k29dkq1z.click/a?next=https://evil.com",
    "github.com": "https://github.com/anthropics",
}


# --------------------------------------------------------------------------- #
# Space background: three tiles of random stars (tiny SVGs) that slowly drift,
# layered over a few blurry "nebula" gradients.
# --------------------------------------------------------------------------- #
# (tile size in px, number of stars, random seed, star colours, star radii)
STAR_TILES = [
    (900, 16, 11, ["#ffffff", "#ffe2c4"], [1.4, 1.8, 2.2]),     # few, big, drift fastest
    (560, 22, 5, ["#cfe0ff", "#ffffff"], [1.0, 1.3]),
    (360, 26, 3, ["#9fb7ff", "#ffffff"], [0.7, 0.9, 1.1]),      # many, tiny, drift slowest
]


def star_tile(size, count, seed, colors, radii) -> str:
    rnd = random.Random(seed)
    dots = "".join(
        f"<circle cx='{rnd.randint(6, size - 6)}' cy='{rnd.randint(6, size - 6)}' r='{rnd.choice(radii)}' "
        f"fill='{rnd.choice(colors)}' opacity='{rnd.uniform(0.45, 1):.2f}'/>"
        for _ in range(count)
    )
    svg = f"<svg xmlns='http://www.w3.org/2000/svg' width='{size}' height='{size}'>{dots}</svg>"
    return 'url("data:image/svg+xml;base64,' + base64.b64encode(svg.encode()).decode() + '")'


CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Chakra+Petch:wght@500;600;700&family=JetBrains+Mono:wght@400;600&display=swap');
:root { --neon:#FF7A1A; --neon-soft:rgba(255,122,26,.5); --cyan:#29E3FF; --text:#E8EEFF; --muted:#9AA9D6;
        --display:'Chakra Petch', system-ui, sans-serif; --mono:'JetBrains Mono', ui-monospace, Menlo, Consolas, monospace; }

/* ---------- space ---------- */
.stApp {
  background-color:#030717;
  background-image: __STARS__,
    radial-gradient(1100px 700px at 88% -8%, rgba(56,84,235,.50), transparent 62%),
    radial-gradient(900px 620px at -8% 28%, rgba(112,44,200,.34), transparent 62%),
    radial-gradient(900px 520px at 62% 112%, rgba(255,122,26,.20), transparent 62%),
    linear-gradient(180deg, #050C28 0%, #030717 100%);
  background-size: __SIZES__, auto, auto, auto, auto;
  background-attachment: fixed;
  animation: ll-drift 240s linear infinite;
}
@keyframes ll-drift { from { background-position: __FROM__; } to { background-position: __TO__; } }
@media (prefers-reduced-motion: reduce) { .stApp { animation: none; } }
[data-testid="stHeader"], [data-testid="stAppViewContainer"], [data-testid="stMain"] { background: transparent; }
#MainMenu, footer { visibility: hidden; }
.block-container, [data-testid="stMainBlockContainer"] { max-width: 1480px; padding: 2.2rem 3rem 4rem; }

/* ---------- hero ---------- */
.ll-hero { display:flex; align-items:center; justify-content:space-between; gap:24px; margin:4px 0 26px; }
.ll-brand { display:flex; align-items:center; gap:10px; margin-bottom:14px; font:700 1.15rem var(--display);
            color:var(--neon); text-shadow:0 0 14px var(--neon-soft); }
.ll-brand i { width:12px; height:12px; border-radius:50%; background:var(--neon); box-shadow:0 0 14px var(--neon); }
.ll-title { font:700 clamp(2.2rem, 5vw, 3.8rem)/1.03 var(--display); max-width:16ch; color:var(--text);
            text-shadow:0 0 30px rgba(90,130,255,.5); }
.ll-lede { color:var(--muted); max-width:60ch; margin:12px 0 0; font-size:1.05rem; }
.ll-planet { position:relative; width:150px; height:150px; flex:none; margin-right:48px; }
.ll-planet::before { content:""; position:absolute; inset:16px; border-radius:50%;
  background:radial-gradient(circle at 32% 30%, #ffc27a, #ff7a1a 42%, #8a2f00 78%, #2a0d00 100%);
  box-shadow:0 0 44px rgba(255,122,26,.65), inset -14px -10px 26px rgba(0,0,0,.45); }
.ll-planet::after { content:""; position:absolute; left:-34px; right:-34px; top:50%; height:50px; margin-top:-25px;
  border:3px solid rgba(41,227,255,.8); border-radius:50%; transform:rotate(-18deg);
  box-shadow:0 0 18px rgba(41,227,255,.6), inset 0 0 14px rgba(41,227,255,.3); }
@media (max-width: 900px) { .ll-planet { display:none; } .block-container, [data-testid="stMainBlockContainer"] { padding:1.4rem 1rem 3rem; } }

/* ---------- inputs, toggle, buttons ---------- */
[data-testid="stForm"] { background:rgba(8,16,50,.66); backdrop-filter:blur(6px); border:1px solid var(--neon-soft);
  border-radius:16px; padding:20px 22px; box-shadow:0 0 26px rgba(255,122,26,.16), inset 0 0 30px rgba(41,227,255,.05); }
[data-baseweb="input"] { background:rgba(4,10,38,.9); border:1px solid rgba(255,122,26,.5); border-radius:10px; }
[data-baseweb="input"]:focus-within { border-color:var(--neon); box-shadow:0 0 0 2px rgba(255,122,26,.35), 0 0 24px rgba(255,122,26,.5); }
[data-baseweb="input"] input { color:var(--text); font-family:var(--mono); }
[data-testid="stFormSubmitButton"] button { background:linear-gradient(135deg,#FF9A3D,#FF6A00); border:0; border-radius:10px;
  box-shadow:0 0 24px rgba(255,122,26,.6); transition:box-shadow .15s, transform .15s; }
[data-testid="stFormSubmitButton"] button:hover { box-shadow:0 0 38px rgba(255,122,26,.95); transform:translateY(-1px); }
[data-testid="stFormSubmitButton"] button p { color:#1A0A00; font:700 1.02rem var(--display); }
[data-testid="stButton"] button { background:rgba(41,227,255,.06); border:1px solid rgba(41,227,255,.7); border-radius:999px;
  transition:box-shadow .15s, background .15s; }
[data-testid="stButton"] button:hover { background:rgba(41,227,255,.16); box-shadow:0 0 18px rgba(41,227,255,.55); }
[data-testid="stButton"] button p { color:var(--cyan); font:500 .9rem var(--mono); }
[data-testid="stExpander"] { background:rgba(8,16,50,.66); border:1px solid rgba(41,227,255,.4); border-radius:12px; }

/* ---------- result cards ---------- */
.ll-h { display:flex; align-items:center; gap:12px; margin:30px 0 8px; font:700 1.5rem var(--display); color:var(--text); }
.ll-h::before { content:""; width:6px; height:1.15em; border-radius:3px; background:var(--neon); box-shadow:0 0 12px var(--neon); }
.ll-sub { color:var(--muted); margin:0 0 14px; }
.ll-banner { display:flex; flex-wrap:wrap; align-items:center; gap:26px 54px; padding:28px 38px; margin-top:26px; border-radius:18px;
  background:linear-gradient(135deg, rgba(14,28,84,.86), rgba(6,12,42,.9));
  border:1px solid color-mix(in srgb, var(--lvl) 65%, transparent);
  box-shadow:0 0 34px color-mix(in srgb, var(--lvl) 32%, transparent), inset 0 0 44px rgba(41,227,255,.05); }
.ll-pie { width:250px; height:250px; flex:none; filter:drop-shadow(0 0 20px color-mix(in srgb, var(--lvl) 55%, transparent));
          animation:ll-pop .9s cubic-bezier(.2,.9,.3,1) both; }
@keyframes ll-pop { from { transform:rotate(-140deg) scale(.82); opacity:0; } to { transform:none; opacity:1; } }
@media (prefers-reduced-motion: reduce) { .ll-pie { animation:none; } }
.ll-verdict { flex:1 1 320px; min-width:0; }
.ll-pct { font:700 clamp(4.4rem, 11vw, 7rem)/.9 var(--display); color:var(--lvl); text-shadow:0 0 36px color-mix(in srgb, var(--lvl) 60%, transparent); }
.ll-pct small { font-size:.3em; margin-left:8px; color:var(--muted); text-shadow:none; font-weight:500; }
.ll-headline { margin:12px 0 0; font:700 clamp(1.5rem, 3vw, 2.2rem)/1.12 var(--display); color:var(--text); }
.ll-advice { margin:12px 0 0; color:#C3CFF2; max-width:62ch; }
.ll-legend { display:flex; flex-wrap:wrap; gap:6px 22px; margin-top:16px; color:var(--muted); font-size:.92rem; }
.ll-legend i { display:inline-block; width:12px; height:12px; border-radius:3px; margin-right:7px; vertical-align:-1px; }

.ll-card { margin:0 0 12px; padding:16px 18px; border-radius:12px; background:rgba(8,16,50,.7); backdrop-filter:blur(5px);
  border:1px solid rgba(120,150,255,.22); border-left:4px solid var(--c, var(--neon));
  box-shadow:0 0 16px color-mix(in srgb, var(--c, var(--neon)) 18%, transparent); }
.ll-card:hover { box-shadow:0 0 24px color-mix(in srgb, var(--c, var(--neon)) 40%, transparent); }
.ll-card-top { display:flex; align-items:center; gap:12px; flex-wrap:wrap; }
.ll-card-top b { font:600 1.08rem var(--display); color:var(--text); }
.ll-card p { margin:8px 0 0; color:#B5C2EA; }
.ll-badge { width:30px; height:30px; border-radius:50%; display:grid; place-items:center; flex:none;
            font:700 .95rem var(--display); color:#050B1F; }
.ll-sev { margin-left:auto; padding:1px 10px; border:1px solid; border-radius:999px; font-size:.78rem; font-weight:600; }
.ll-found { margin-top:10px; color:var(--muted); font-size:.86rem; display:flex; flex-wrap:wrap; gap:6px 8px; align-items:center; }
.ll-code { font:600 .86rem var(--mono); color:var(--neon); background:rgba(255,122,26,.1); border:1px solid rgba(255,122,26,.45);
           padding:1px 8px; border-radius:5px; overflow-wrap:anywhere; }
.ll-good { --c:#39FFB0; color:#BFFFE6; }
.ll-alt { --c:var(--neon); border-top:3px solid var(--neon); }
.ll-ok { margin-left:auto; padding:1px 10px; border:1px solid #39FFB0; border-radius:999px; color:#39FFB0; font-size:.78rem; font-weight:600; }
.ll-tag { margin-top:6px; color:var(--muted); font-size:.84rem; }
.ll-addr { margin-top:8px; font:600 .9rem var(--mono); color:var(--neon); overflow-wrap:anywhere; }
a.ll-open { display:inline-block; margin-top:12px; padding:8px 18px; border-radius:9px; text-decoration:none; font-weight:700;
  color:#1A0A00; background:linear-gradient(135deg,#FF9A3D,#FF6A00); box-shadow:0 0 16px rgba(255,122,26,.55); }
a.ll-open:hover { box-shadow:0 0 28px rgba(255,122,26,.95); }
.ll-tips { margin:4px 0 0; padding-left:20px; color:#B5C2EA; }
.ll-tips li { margin:5px 0; }
.ll-tips li::marker { color:var(--neon); }
.ll-foot { color:#7F90C4; font-size:.84rem; margin-top:10px; }
</style>
"""


def build_css() -> str:
    tiles = [star_tile(*t) for t in STAR_TILES]
    sizes = ", ".join(f"{t[0]}px {t[0]}px" for t in STAR_TILES)
    start = ", ".join(["0 0"] * (len(STAR_TILES) + 4))
    end = ", ".join([f"-{t[0]}px {t[0]}px" for t in STAR_TILES] + ["0 0"] * 4)   # drift exactly one tile = seamless loop
    return CSS.replace("__STARS__", ", ".join(tiles)).replace("__SIZES__", sizes) \
              .replace("__FROM__", start).replace("__TO__", end)


# --------------------------------------------------------------------------- #
# Helpers (plain Python: easy to explain and to test)
# --------------------------------------------------------------------------- #
def safe(text: str) -> str:
    """Escape text that came from the analysed URL before it goes into HTML.
    (The URL is attacker-controlled, so we never let it be interpreted as markup.)"""
    return html.escape(str(text)).replace("$", "&#36;")


def heading(text: str) -> None:
    st.markdown(f'<div class="ll-h" role="heading" aria-level="2">{text}</div>', unsafe_allow_html=True)


def highlight_url(url: str, findings: list) -> str:
    """Return the URL as HTML with every problem marked in place.

    Each finding carries `spans` = [start, end] character ranges inside the URL.
    We note which findings cover each character, group neighbouring characters that
    share the same findings, and wrap each group in a coloured <mark>.
    """
    cover = [[] for _ in url]
    for i, f in enumerate(findings):
        for a, b in f["spans"]:
            for k in range(a, min(b, len(url))):
                if i not in cover[k]:
                    cover[k].append(i)
    first_end = {i: min(f["spans"])[1] for i, f in enumerate(findings) if f["spans"]}

    parts, i = [], 0
    while i < len(url):
        key = tuple(cover[i])
        j = i + 1
        while j < len(url) and tuple(cover[j]) == key:
            j += 1
        text = safe(url[i:j])
        if key:
            worst = max((findings[x]["severity"] for x in key), key=SEV_RANK.get)
            parts.append(
                f'<mark style="background:{SEV_BG[worst]};border-bottom:3px solid {SEV_COLOR[worst]};'
                f'color:#E8EEFF;padding:2px 1px;border-radius:3px;box-shadow:0 0 12px {SEV_BG[worst]}">{text}</mark>'
            )
        else:
            parts.append(f'<span style="color:#B6C3EA">{text}</span>')
        for idx, end in first_end.items():           # numbered badge after the first mark of each finding
            if end == j:
                parts.append(
                    f'<sup style="background:{SEV_COLOR[findings[idx]["severity"]]};color:#050B1F;'
                    f'font:700 .62rem sans-serif;padding:2px 5px;border-radius:999px;margin:0 5px 0 2px">{idx + 1}</sup>'
                )
        i = j

    # one single line, no indentation: Streamlit's markdown would turn indented lines into a code block
    return (
        '<div style="font-family:\'JetBrains Mono\',ui-monospace,Menlo,Consolas,monospace;font-size:1.08rem;line-height:2.1;'
        'overflow-wrap:anywhere;background:rgba(6,12,44,.85);border:1px solid rgba(41,227,255,.4);border-radius:14px;'
        'padding:18px 20px;box-shadow:0 0 22px rgba(41,227,255,.14), inset 0 0 30px rgba(41,227,255,.05)">'
        + "".join(parts) + "</div>"
    )


def pie_img(risk: int, color: str) -> str:
    """The risk pie chart: an SVG drawn with plain trigonometry, embedded as an <img>.
    The risk slice starts at 12 o'clock and runs clockwise."""
    R, C = 92, 100

    def point(radius, deg):
        a = math.radians(deg - 90)
        return C + radius * math.cos(a), C + radius * math.sin(a)

    end = 360 * risk / 100
    x1, y1 = point(R, 0)
    x2, y2 = point(R, end)
    path = f"M{C} {C} L{x1:.2f} {y1:.2f} A{R} {R} 0 {1 if end > 180 else 0} 1 {x2:.2f} {y2:.2f} Z"

    def label(deg, text, fill):
        x, y = point(R * 0.62, deg)
        return (f'<text x="{x:.1f}" y="{y:.1f}" fill="{fill}" text-anchor="middle" dominant-baseline="central" '
                f'font-family="system-ui, sans-serif" font-size="17" font-weight="700">{text}</text>')

    labels = ""
    if risk >= 12:
        labels += label(end / 2, f"{risk}%", "#050B1F")
    if risk <= 88:
        labels += label(end + (360 - end) / 2, f"{100 - risk}%", "#C9D6FF")

    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-8 -8 216 216" width="260" height="260">'
           f'<circle cx="100" cy="100" r="{R}" fill="#14275C" stroke="#2B428F" stroke-width="1.5"/>'
           f'<path d="{path}" fill="{color}" stroke="#050B1F" stroke-width="2" stroke-linejoin="round"/>{labels}</svg>')
    uri = "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()
    return f'<img class="ll-pie" src="{uri}" alt="Pie chart: {risk}% risk, {100 - risk}% no sign of threat">'


def banner_html(d: dict) -> str:
    color = LEVEL_COLOR[d["level"]]
    return (
        f'<div class="ll-banner" style="--lvl:{color}">{pie_img(d["risk"], color)}'
        f'<div class="ll-verdict"><div class="ll-pct">{d["risk"]}<small>% risk</small></div>'
        f'<div class="ll-headline">{safe(d["headline"])}</div><p class="ll-advice">{safe(d["advice"])}</p>'
        f'<div class="ll-legend"><span><i style="background:{color}"></i>Risk {d["risk"]}%</span>'
        f'<span><i style="background:#14275C;border:1px solid #3A55B0"></i>No sign of threat {100 - d["risk"]}%</span>'
        f'</div></div></div>'
    )


def problem_card(n: int, f: dict, url: str) -> str:
    color = SEV_COLOR[f["severity"]]
    snippets = list(dict.fromkeys(url[a:b] for a, b in f["spans"]))[:6]
    found = ""
    if snippets:
        found = ('<div class="ll-found">Found in: '
                 + "".join(f'<span class="ll-code">{safe(s)}</span>' for s in snippets) + "</div>")
    return (
        f'<div class="ll-card" style="--c:{color}"><div class="ll-card-top">'
        f'<span class="ll-badge" style="background:{color}">{n}</span><b>{safe(f["title"])}</b>'
        f'<span class="ll-sev" style="color:{color}">{f["severity"].title()}</span></div>'
        f'<p>{safe(f["detail"])}</p>{found}</div>'
    )


def alt_card(s: dict) -> str:
    link = ""
    if s["url"].startswith("https://"):
        link = (f'<a class="ll-open" href="{html.escape(s["url"], quote=True)}" target="_blank" '
                f'rel="noopener noreferrer">Open official site</a>')
    return (
        f'<div class="ll-card ll-alt"><div class="ll-card-top"><b>{safe(s["name"])}</b>'
        f'<span class="ll-ok">Verified</span></div><p>{safe(s["why"])}</p>'
        f'<div class="ll-tag">{safe(s["tag"])}</div><div class="ll-addr">{safe(s["display"])}</div>{link}</div>'
    )


@st.cache_data(ttl=600, show_spinner=False)
def run_check(url: str, live: bool, intent: str) -> dict:
    """Cache results for 10 minutes so repeated checks of the same link are instant."""
    return analyze(url, live=live, intent=intent)


def pick_example(url: str) -> None:
    """Button callback: fill the box and ask the main flow to run the check."""
    st.session_state["url"] = url
    st.session_state["auto_run"] = True


# --------------------------------------------------------------------------- #
# Result drawing: a full-width verdict banner, then two columns
# --------------------------------------------------------------------------- #
def render(d: dict) -> None:
    st.markdown(banner_html(d), unsafe_allow_html=True)

    left, right = st.columns([1.2, 1], gap="large")

    with left:
        heading("Where the problems are")
        st.markdown('<p class="ll-sub">' + ("Numbers match the cards below." if d["findings"]
                    else "Nothing in this link needed highlighting.") + "</p>", unsafe_allow_html=True)
        st.markdown(highlight_url(d["url"], d["findings"]), unsafe_allow_html=True)
        if d["findings"]:
            st.markdown(
                '<div class="ll-legend"><span style="color:#FF3B6B">■ High</span>'
                '<span style="color:#FFA21F">■ Medium</span><span style="color:#29E3FF">■ Low</span></div>',
                unsafe_allow_html=True)
        heading(f"Every problem found ({len(d['findings'])})" if d["findings"] else "Every problem found")
        if not d["findings"]:
            st.markdown('<div class="ll-card ll-good">No problems found with this link.</div>', unsafe_allow_html=True)
        for n, f in enumerate(d["findings"], 1):
            st.markdown(problem_card(n, f, d["url"]), unsafe_allow_html=True)

    with right:
        alt = d["alternatives"]
        if alt:
            heading(safe(alt["headline"]))
            st.markdown(f'<p class="ll-sub">{safe(alt["reason"])}</p>', unsafe_allow_html=True)
            for s in alt["sites"]:
                st.markdown(alt_card(s), unsafe_allow_html=True)
            tips = "".join(f"<li>{safe(t)}</li>" for t in alt["tips"])
            st.markdown(f'<ul class="ll-tips">{tips}</ul>', unsafe_allow_html=True)
            st.markdown('<div class="ll-foot">Addresses come from a hand-curated list of official sites, not a live '
                        'lookup. Type the address yourself or use a bookmark rather than clicking it from a message.</div>',
                        unsafe_allow_html=True)
        heading("Checks")
        with st.expander(f"{len(d['passed'])} checks passed"):
            st.markdown("\n".join(f"- {p}" for p in d["passed"]))
        for note in d["notes"]:
            st.caption(note)

    st.caption("This is an automated estimate based on how the link is written and, if enabled, public domain "
               "records. It can miss threats and can flag harmless links. A low score is not a guarantee.")


# --------------------------------------------------------------------------- #
# NEW: QR code + message (SMS) checking. Everything below only ADDS; nothing above changed.
# --------------------------------------------------------------------------- #
EXAMPLE_MESSAGES = {
    "fake bank KYC": "Dear customer, your SBI account will be blocked today. Update your KYC now: http://sbi-kyc-update.top/login",
    "parcel fee": "Your parcel could not be delivered due to incomplete address. Reschedule delivery and pay a small fee of Rs 25: https://post-india-track.top/redeliver",
    "OTP request": "Bank officer here. Please share your OTP to stop the transaction immediately.",
    "normal message": "Hi Priya, lunch at 1pm? Menu is here: https://github.com/anthropics",
}

# Styling for the new tabs, text box and upload area (same neon look as the rest of the page).
EXTRA_CSS = """
<style>
[data-baseweb="tab-list"] { gap:8px; }
button[data-baseweb="tab"] { height:auto; padding:7px 20px; background:rgba(8,16,50,.55); border:1px solid rgba(41,227,255,.35); border-radius:999px; }
button[data-baseweb="tab"] p { color:var(--cyan); font:600 .98rem var(--display); }
button[data-baseweb="tab"][aria-selected="true"] { background:rgba(255,122,26,.16); border-color:var(--neon); box-shadow:0 0 18px rgba(255,122,26,.45); }
button[data-baseweb="tab"][aria-selected="true"] p { color:var(--neon); }
[data-baseweb="tab-highlight"], [data-baseweb="tab-border"] { display:none; }
[data-baseweb="textarea"] { background:rgba(4,10,38,.9); border:1px solid rgba(255,122,26,.5); border-radius:10px; }
[data-baseweb="textarea"]:focus-within { border-color:var(--neon); box-shadow:0 0 0 2px rgba(255,122,26,.35), 0 0 24px rgba(255,122,26,.5); }
[data-baseweb="textarea"] textarea { background:transparent; color:var(--text); font-family:var(--mono); }
[data-testid="stFileUploaderDropzone"] { background:rgba(4,10,38,.9); border:1px dashed rgba(255,122,26,.6); border-radius:12px; }
[data-testid="stFileUploaderDropzone"] small, [data-testid="stFileUploaderDropzone"] span { color:var(--muted); }
</style>
"""


@st.cache_data(ttl=600, show_spinner=False)
def run_message_check(text: str, live: bool) -> dict:
    """Same 10-minute cache as run_check, for pasted messages."""
    return analyze_message(text, live=live)


@st.cache_data(ttl=600, show_spinner=False)
def run_qr_check(data: bytes, live: bool) -> list:
    """Read the QR code(s) in a picture and analyse what is inside. Cached by picture bytes."""
    return analyze_qr_image(data, live=live)


def pick_message(text: str) -> None:
    """Button callback: fill the message box and ask the main flow to run the check."""
    st.session_state["msg_text"] = text
    st.session_state["msg_auto"] = True


def link_summary_card(r: dict) -> str:
    color = LEVEL_COLOR[r["level"]]
    return (
        f'<div class="ll-card" style="--c:{color}"><div class="ll-card-top"><b>{safe(r["headline"])}</b>'
        f'<span class="ll-sev" style="color:{color}">{r["risk"]}% risk</span></div>'
        f'<div class="ll-addr">{safe(r["url"])}</div></div>'
    )


def payload_card(label: str, display: str) -> str:
    return (
        f'<div class="ll-card ll-alt"><div class="ll-card-top"><b>QR code contains: {safe(label)}</b></div>'
        f'<div class="ll-addr">{safe(display)}</div>'
        '<div class="ll-tag">This is the text hidden inside the QR code. It was only read, never opened.</div></div>'
    )


def render_message(d: dict) -> None:
    """Verdict banner, the message with problems marked, every reason, then one report per link."""
    st.markdown(banner_html(d), unsafe_allow_html=True)

    left, right = st.columns([1.2, 1], gap="large")
    with left:
        heading("Where the problems are")
        st.markdown('<p class="ll-sub">' + ("Numbers match the cards below." if d["findings"]
                    else "Nothing in this message needed highlighting.") + "</p>", unsafe_allow_html=True)
        st.markdown(highlight_url(d["text"], d["findings"]), unsafe_allow_html=True)
        if d["findings"]:
            st.markdown(
                '<div class="ll-legend"><span style="color:#FF3B6B">■ High</span>'
                '<span style="color:#FFA21F">■ Medium</span><span style="color:#29E3FF">■ Low</span></div>',
                unsafe_allow_html=True)
        heading(f"Why this risk score ({len(d['findings'])})" if d["findings"] else "Why this risk score")
        if not d["findings"]:
            st.markdown('<div class="ll-card ll-good">No problems found with this message.</div>', unsafe_allow_html=True)
        for n, f in enumerate(d["findings"], 1):
            st.markdown(problem_card(n, f, d["text"]), unsafe_allow_html=True)

    with right:
        heading(f"Links in this message ({len(d['links'])})")
        if not d["links"]:
            st.markdown('<div class="ll-card ll-good">No links found in this message.</div>', unsafe_allow_html=True)
        for item in d["links"]:
            st.markdown(link_summary_card(item["result"]), unsafe_allow_html=True)
        heading("Checks")
        with st.expander(f"{len(d['passed'])} checks passed"):
            st.markdown("\n".join(f"- {p}" for p in d["passed"]))
        for note in d["notes"]:
            st.caption(note)

    if d["links"]:
        heading("Link-by-link reports")
        for i, item in enumerate(d["links"], 1):
            r = item["result"]
            with st.expander(f"Link {i}: {r['risk']}% risk, {r['headline']}", expanded=(i == 1)):
                render(r)

    st.caption("This is an automated estimate based on the wording of the message and how its links are written. "
               "It can miss scams and can flag harmless messages. A low score is not a guarantee.")


def render_qr(codes: list) -> None:
    for i, c in enumerate(codes, 1):
        if len(codes) > 1:
            heading(f"QR code {i} of {len(codes)}")
        st.markdown(payload_card(c["label"], c["display"]), unsafe_allow_html=True)
        if c["kind"] == "message":
            render_message(c["result"])      # the code held a whole text: judged like a message
        else:
            render(c["result"])              # a link, a payment request, Wi-Fi ... (same layout as a link report)


# --------------------------------------------------------------------------- #
# Page
# --------------------------------------------------------------------------- #
st.markdown(build_css(), unsafe_allow_html=True)

st.markdown(
    '<div class="ll-hero"><div><div class="ll-brand"><i></i>LinkLens</div>'
    '<div class="ll-title" role="heading" aria-level="1">Is this link safe to open?</div>'
    '<p class="ll-lede">Paste any link. We inspect the address itself, without opening the page, '
    'and mark every problem directly inside it.</p></div><div class="ll-planet"></div></div>',
    unsafe_allow_html=True,
)

if "url" not in st.session_state:
    st.session_state["url"] = ""

if "msg_text" not in st.session_state:
    st.session_state["msg_text"] = ""

st.markdown(EXTRA_CSS, unsafe_allow_html=True)
tab_link, tab_qr, tab_msg = st.tabs(["🔗 Check a link", "📷 Scan a QR code", "💬 Check a message / SMS"])

# ---- Tab 1: the original link checker, unchanged except that it now sits inside a tab ----
with tab_link:
    with st.form("check"):
        c1, c2 = st.columns([6, 1.4])
        with c1:
            st.text_input("Link to check", key="url", label_visibility="collapsed",
                          placeholder="Paste a link, e.g. http://paypa1-login.xyz/verify")
        with c2:
            submitted = st.form_submit_button("Check link", type="primary", use_container_width=True)
        c3, c4 = st.columns([5, 2])
        with c3:
            st.text_input("What were you trying to find? (optional)", key="intent", label_visibility="collapsed",
                          placeholder="Optional: what were you trying to find? e.g. track my parcel, download VLC")
        with c4:
            live = st.toggle("Live domain checks", value=True, help="DNS, security certificate and domain age")

    for col, (label, example_url) in zip(st.columns(len(EXAMPLES)), EXAMPLES.items()):
        col.button(label, key=f"ex_{label}", on_click=pick_example, args=(example_url,), use_container_width=True)

    if submitted or st.session_state.pop("auto_run", False):
        url = st.session_state["url"].strip()
        if not url:
            st.warning("Paste a link to check.")
            st.session_state.pop("result", None)
        else:
            try:
                with st.spinner("Inspecting link..."):
                    st.session_state["result"] = run_check(url, live, st.session_state.get("intent", "").strip())
            except ValueError as err:          # bad input (empty, spaces, too long ...)
                st.session_state.pop("result", None)
                st.error(str(err))

    if st.session_state.get("result"):
        render(st.session_state["result"])

# ---- Tab 2 (NEW): QR code ----
with tab_qr:
    st.markdown('<p class="ll-sub">Upload a picture or screenshot of a QR code (or use your camera). We read what is '
                'hidden inside it and judge it. Nothing is opened.</p>', unsafe_allow_html=True)
    q1, q2 = st.columns([3, 2])
    with q1:
        use_camera = st.toggle("Use my camera instead of uploading a picture", key="qr_camera_on")
    with q2:
        qr_live = st.toggle("Live domain checks", value=True, key="qr_live", help="DNS, security certificate and domain age")
    if use_camera:
        shot = st.camera_input("Point the camera at the QR code", key="qr_camera")
    else:
        shot = st.file_uploader("Upload a picture of the QR code", type=["png", "jpg", "jpeg", "webp", "bmp"], key="qr_file")
    if shot is not None:
        data = shot.getvalue()
        if len(data) > MAX_IMAGE_BYTES:
            st.error("That picture is larger than 8 MB. Try a smaller photo or screenshot.")
        else:
            try:
                with st.spinner("Reading QR code..."):
                    qr_results = run_qr_check(data, qr_live)
                render_qr(qr_results)
            except (ValueError, RuntimeError) as err:     # no QR found, not an image, packages missing ...
                st.error(str(err))

# ---- Tab 3 (NEW): whole message / SMS ----
with tab_msg:
    st.markdown('<p class="ll-sub">Paste a whole SMS, WhatsApp or e-mail message, link included. We check the wording '
                'for scam tricks and check every link inside it.</p>', unsafe_allow_html=True)
    with st.form("msg_form"):
        st.text_area("Message to check", key="msg_text", height=170, label_visibility="collapsed",
                     placeholder="Paste the whole message here, e.g. Dear customer, your account will be blocked. "
                                 "Update KYC now: http://sbi-kyc-update.top/login")
        m1, m2 = st.columns([5, 2])
        with m1:
            msg_submitted = st.form_submit_button("Check message", type="primary", use_container_width=True)
        with m2:
            msg_live = st.toggle("Live domain checks", value=True, key="msg_live", help="DNS, security certificate and domain age")

    for col, (label, example_text) in zip(st.columns(len(EXAMPLE_MESSAGES)), EXAMPLE_MESSAGES.items()):
        col.button(label, key=f"msgex_{label}", on_click=pick_message, args=(example_text,), use_container_width=True)

    if msg_submitted or st.session_state.pop("msg_auto", False):
        message = st.session_state["msg_text"].strip()
        if not message:
            st.warning("Paste a message to check.")
            st.session_state.pop("msg_result", None)
        else:
            try:
                with st.spinner("Checking message..."):
                    st.session_state["msg_result"] = run_message_check(message, st.session_state.get("msg_live", True))
            except ValueError as err:
                st.session_state.pop("msg_result", None)
                st.error(str(err))

    if st.session_state.get("msg_result"):
        render_message(st.session_state["msg_result"])
