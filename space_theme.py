"""space_theme.py - dark starry space theme (white x neon purple) for a Streamlit app.

How to use (2 lines in your app.py):
    from space_theme import apply_space_theme, space_hero
    apply_space_theme()        # call it right after st.set_page_config(...)

It only changes how things LOOK. It never touches your logic.
"""

import html
import random
from urllib.parse import quote

import streamlit as st

# ----------------------------------------------------------------------------- palette
NEON = "#B026FF"        # neon purple
NEON_SOFT = "#C77DFF"   # lighter purple for glows and links
WHITE = "#FFFFFF"
INK = "#05030F"         # deep space background


# ----------------------------------------------------------------------------- planets (inline SVG)
def _data_uri(svg: str) -> str:
    """Turn an SVG string into a CSS-friendly data: URL."""
    return "data:image/svg+xml;charset=utf-8," + quote(" ".join(svg.split()), safe="")


PLANET_RINGED = _data_uri("""
<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 560 380'>
  <defs>
    <radialGradient id='g' cx='34%' cy='30%' r='78%'>
      <stop offset='0' stop-color='#ffffff'/><stop offset='.16' stop-color='#eadbff'/>
      <stop offset='.5' stop-color='#9a4dff'/><stop offset='.85' stop-color='#3a0f8c'/>
      <stop offset='1' stop-color='#12042b'/>
    </radialGradient>
    <linearGradient id='r' x1='0' x2='1'>
      <stop offset='0' stop-color='#b026ff' stop-opacity='.1'/>
      <stop offset='.5' stop-color='#f4eaff' stop-opacity='.95'/>
      <stop offset='1' stop-color='#b026ff' stop-opacity='.15'/>
    </linearGradient>
    <clipPath id='c'><circle cx='280' cy='190' r='120'/></clipPath>
    <filter id='glow' x='-40%' y='-40%' width='180%' height='180%'><feGaussianBlur stdDeviation='16'/></filter>
  </defs>
  <circle cx='280' cy='190' r='138' fill='#b026ff' opacity='.35' filter='url(#glow)'/>
  <g transform='rotate(-16 280 190)'>
    <path d='M60 190 A220 52 0 0 1 500 190' fill='none' stroke='url(#r)' stroke-width='14'/>
    <path d='M86 190 A194 44 0 0 1 474 190' fill='none' stroke='url(#r)' stroke-width='5' opacity='.7'/>
  </g>
  <circle cx='280' cy='190' r='120' fill='url(#g)'/>
  <g clip-path='url(#c)'>
    <rect x='150' y='128' width='260' height='9' rx='4' fill='#2a0b66' opacity='.35'/>
    <rect x='150' y='158' width='260' height='14' rx='6' fill='#ffffff' opacity='.12'/>
    <rect x='150' y='200' width='260' height='10' rx='5' fill='#2a0b66' opacity='.35'/>
    <rect x='150' y='232' width='260' height='16' rx='7' fill='#ffffff' opacity='.10'/>
  </g>
  <g transform='rotate(-16 280 190)'>
    <path d='M60 190 A220 52 0 0 0 500 190' fill='none' stroke='url(#r)' stroke-width='14'/>
    <path d='M86 190 A194 44 0 0 0 474 190' fill='none' stroke='url(#r)' stroke-width='5' opacity='.7'/>
  </g>
</svg>""")

PLANET_MOON = _data_uri("""
<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 200 200'>
  <defs>
    <radialGradient id='m' cx='35%' cy='30%' r='80%'>
      <stop offset='0' stop-color='#ffffff'/><stop offset='.45' stop-color='#ddd2ff'/>
      <stop offset='1' stop-color='#54418f'/>
    </radialGradient>
    <clipPath id='mc'><circle cx='100' cy='100' r='70'/></clipPath>
    <filter id='mg' x='-40%' y='-40%' width='180%' height='180%'><feGaussianBlur stdDeviation='9'/></filter>
  </defs>
  <circle cx='100' cy='100' r='78' fill='#c9a7ff' opacity='.3' filter='url(#mg)'/>
  <circle cx='100' cy='100' r='70' fill='url(#m)'/>
  <g clip-path='url(#mc)' fill='#6f5bb0' opacity='.35'>
    <ellipse cx='72' cy='78' rx='16' ry='13'/><ellipse cx='125' cy='112' rx='22' ry='18'/>
    <ellipse cx='88' cy='132' rx='10' ry='8'/><ellipse cx='132' cy='70' rx='8' ry='7'/>
  </g>
</svg>""")

PLANET_ORB = _data_uri("""
<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 120 120'>
  <defs>
    <radialGradient id='o' cx='34%' cy='30%' r='80%'>
      <stop offset='0' stop-color='#ffffff'/><stop offset='.35' stop-color='#d98cff'/>
      <stop offset='.8' stop-color='#7a1fd6'/><stop offset='1' stop-color='#2a0b66'/>
    </radialGradient>
    <filter id='og' x='-60%' y='-60%' width='220%' height='220%'><feGaussianBlur stdDeviation='8'/></filter>
  </defs>
  <circle cx='60' cy='60' r='34' fill='#b026ff' opacity='.55' filter='url(#og)'/>
  <circle cx='60' cy='60' r='26' fill='url(#o)'/>
</svg>""")


# ----------------------------------------------------------------------------- stars
def _stars(count: int, seed: int, blur: int, colors: list) -> str:
    """Random star positions written as a CSS box-shadow list (fixed seed = same sky every run)."""
    rnd = random.Random(seed)
    parts = []
    for _ in range(count):
        x, y = rnd.uniform(0, 100), rnd.uniform(0, 100)
        parts.append(f"{x:.2f}vw {y:.2f}vh {blur}px 0 {rnd.choice(colors)}")
    return ",".join(parts)


# ----------------------------------------------------------------------------- the CSS
_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Unbounded:wght@500;700&family=Manrope:wght@400;500;700&display=swap');

html, body, .stApp, button, input, textarea, select { font-family: 'Manrope', sans-serif; }
h1, h2, h3, h4 { font-family: 'Unbounded', sans-serif !important; letter-spacing: .01em; color: #fff; }
::selection { background: __NEON__; color: #fff; }

/* ---------- the sky ---------- */
.stApp {
  background-color: __INK__;
  background-image:
    url("__ORB__"),
    radial-gradient(60vw 45vh at 85% 8%, rgba(176,38,255,.24), transparent 70%),
    radial-gradient(55vw 50vh at 6% 92%, rgba(124,77,255,.22), transparent 70%),
    radial-gradient(35vw 25vh at 45% 40%, rgba(255,255,255,.035), transparent 70%),
    linear-gradient(180deg, #04020c 0%, #09041d 55%, #12072e 100%);
  background-repeat: no-repeat;
  background-size: 86px 86px, auto, auto, auto, auto;
  background-position: 71% 22%, 0 0, 0 0, 0 0, 0 0;
  background-attachment: fixed;
}
/* twinkling stars: two layers */
.stApp::before, .stApp::after { content: ""; position: fixed; top: 0; left: 0; z-index: 0; pointer-events: none; border-radius: 50%; }
.stApp::before { width: 1px; height: 1px; box-shadow: __STARS_SMALL__; animation: lens-twinkle 5s ease-in-out infinite; }
.stApp::after  { width: 2px; height: 2px; box-shadow: __STARS_BIG__;   animation: lens-twinkle 3.4s ease-in-out -1.7s infinite; }
@keyframes lens-twinkle { 0%, 100% { opacity: .35; } 50% { opacity: 1; } }

/* planets */
[data-testid="stAppViewContainer"]::before {
  content: ""; position: fixed; z-index: 0; pointer-events: none;
  right: -3vw; bottom: -5vh; width: min(36vw, 540px); aspect-ratio: 560 / 380;
  background: url("__RINGED__") center / contain no-repeat;
  animation: lens-float-a 17s ease-in-out infinite;
}
[data-testid="stAppViewContainer"]::after {
  content: ""; position: fixed; z-index: 0; pointer-events: none;
  left: 4vw; top: 17vh; width: min(10vw, 140px); aspect-ratio: 1;
  background: url("__MOON__") center / contain no-repeat;
  animation: lens-float-b 12s ease-in-out infinite;
}
@keyframes lens-float-a { 0%, 100% { transform: translateY(0) rotate(0deg); } 50% { transform: translateY(-16px) rotate(1.6deg); } }
@keyframes lens-float-b { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(12px); } }

/* a shooting star every so often */
body::before {
  content: ""; position: fixed; top: 9vh; left: 74vw; width: 170px; height: 2px; z-index: 0; pointer-events: none;
  background: linear-gradient(90deg, #e6ccff, #fff 25%, rgba(255,255,255,0));
  border-radius: 2px; opacity: 0; transform: rotate(-35deg);
  animation: lens-shoot 13s linear infinite;
}
@keyframes lens-shoot {
  0%, 85% { opacity: 0; transform: translate(0, 0) rotate(-35deg); }
  87% { opacity: 1; }
  100% { opacity: 0; transform: translate(-48vw, 34vh) rotate(-35deg); }
}

/* keep the app on top of the sky */
[data-testid="stMain"], section.main { position: relative; z-index: 1; }
[data-testid="stHeader"] { background: transparent; }
footer { visibility: hidden; }

/* ---------- text ---------- */
h1 {
  background: linear-gradient(90deg, #ffffff 0%, #efe3ff 45%, __NEON_SOFT__ 100%);
  -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent;
  filter: drop-shadow(0 0 16px rgba(176,38,255,.5));
}
h2, h3 { text-shadow: 0 0 18px rgba(176,38,255,.45); }
.stMarkdown, label, [data-testid="stWidgetLabel"] { color: #eee7ff; }
a { color: __NEON_SOFT__; }
code, pre { background: rgba(176,38,255,.14) !important; color: #f4ecff !important; border-radius: 8px; }

/* ---------- glass panels ---------- */
[data-testid="stSidebar"] { background: rgba(10,5,30,.80); backdrop-filter: blur(14px); border-right: 1px solid rgba(176,38,255,.28); }
[data-testid="stExpander"], [data-testid="stMetric"], [data-testid="stForm"], [data-testid="stFileUploaderDropzone"] {
  background: rgba(18,10,44,.66); border: 1px solid rgba(176,38,255,.35); border-radius: 16px; backdrop-filter: blur(10px);
}
[data-testid="stMetric"] { padding: 14px 18px; box-shadow: 0 0 22px -10px __NEON__; }
[data-testid="stFileUploaderDropzone"] { border-style: dashed; }
[data-testid="stAlert"] { backdrop-filter: blur(8px); border-radius: 14px; }
[data-testid="stDataFrame"] { border: 1px solid rgba(176,38,255,.35); border-radius: 14px; overflow: hidden; }

/* ---------- inputs ---------- */
[data-baseweb="input"], [data-baseweb="textarea"], [data-baseweb="select"] > div {
  background: rgba(10,5,30,.82) !important; border: 1px solid rgba(176,38,255,.5) !important; border-radius: 12px !important;
}
[data-baseweb="input"]:focus-within, [data-baseweb="textarea"]:focus-within, [data-baseweb="select"] > div:focus-within {
  border-color: #e3c8ff !important; box-shadow: 0 0 0 1px __NEON__, 0 0 22px rgba(176,38,255,.5) !important;
}
input, textarea { color: #fff !important; }

/* ---------- buttons ---------- */
.stButton > button, .stDownloadButton > button, [data-testid="stFormSubmitButton"] > button {
  background: linear-gradient(135deg, #7c3aed, __NEON__); color: #fff; font-weight: 700;
  border: 1px solid rgba(255,255,255,.28); border-radius: 999px; padding: .55rem 1.5rem;
  box-shadow: 0 0 20px rgba(176,38,255,.55); transition: transform .15s ease, box-shadow .15s ease;
}
.stButton > button:hover, .stDownloadButton > button:hover, [data-testid="stFormSubmitButton"] > button:hover {
  transform: translateY(-2px); box-shadow: 0 0 34px rgba(199,125,255,.85); color: #fff; border-color: #fff;
}
.stButton > button:focus-visible { outline: 2px solid #fff; outline-offset: 3px; }

/* ---------- tabs, progress, scrollbar ---------- */
button[data-baseweb="tab"] { color: #cdbdf2; }
button[data-baseweb="tab"][aria-selected="true"] { color: #fff; }
[data-baseweb="tab-highlight"] { background: __NEON__ !important; box-shadow: 0 0 12px __NEON__; }
[data-testid="stProgress"] [role="progressbar"] > div { background: linear-gradient(90deg, #7c3aed, __NEON_SOFT__) !important; }
::-webkit-scrollbar { width: 10px; } ::-webkit-scrollbar-thumb { background: rgba(176,38,255,.55); border-radius: 8px; }
::-webkit-scrollbar-track { background: rgba(255,255,255,.04); }

/* ---------- optional hero banner ---------- */
.lens-hero { text-align: center; padding: 1.4rem 0 .6rem 0; }
.lens-hero p { color: #cdbdf2; font-size: 1.1rem; margin: .2rem 0 0 0; }
.lens-badge { display: inline-block; padding: .3rem 1rem; border-radius: 999px; border: 1px solid __NEON__; color: #f1e6ff;
  background: rgba(176,38,255,.15); box-shadow: 0 0 18px -4px __NEON__; font-size: .85rem; margin-bottom: .6rem; }

/* hides the tiny empty gap this style block would otherwise leave */
[data-testid="stElementContainer"]:has(#lens-space-marker), .element-container:has(#lens-space-marker) { display: none; }

/* phones: smaller, fainter planets so text stays readable */
@media (max-width: 768px) {
  .stApp { background-position: 90% 64%, 0 0, 0 0, 0 0, 0 0; }
  [data-testid="stAppViewContainer"]::before { width: 60vw; opacity: .55; }
  [data-testid="stAppViewContainer"]::after { width: 16vw; top: 70vh; left: 5vw; opacity: .6; }
}
@media (prefers-reduced-motion: reduce) {
  .stApp::before, .stApp::after, body::before,
  [data-testid="stAppViewContainer"]::before, [data-testid="stAppViewContainer"]::after { animation: none; }
}
"""


def apply_space_theme() -> None:
    """Inject the space theme. Call once, right after st.set_page_config()."""
    css = (
        _CSS.replace("__NEON_SOFT__", NEON_SOFT)
        .replace("__NEON__", NEON)
        .replace("__INK__", INK)
        .replace("__ORB__", PLANET_ORB)
        .replace("__RINGED__", PLANET_RINGED)
        .replace("__MOON__", PLANET_MOON)
        .replace("__STARS_SMALL__", _stars(190, 7, 0, ["#ffffff", "#f1e6ff", "#d9c2ff"]))
        .replace("__STARS_BIG__", _stars(60, 21, 3, ["#ffffff", "#e3c8ff", "#c77dff"]))
    )
    css = "\n".join(line.strip() for line in css.splitlines() if line.strip())
    st.markdown(f"<style>{css}</style><i id='lens-space-marker'></i>", unsafe_allow_html=True)


def space_hero(title: str, subtitle: str, badge: str = "URL threat scanner") -> None:
    """Optional centered banner. Use it instead of st.title() if you like."""
    st.markdown(
        f"<div class='lens-hero'><span class='lens-badge'>{html.escape(badge)}</span>"
        f"<h1>{html.escape(title)}</h1><p>{html.escape(subtitle)}</p></div>",
        unsafe_allow_html=True,
    )
