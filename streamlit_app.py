"""
streamlit_app.py - LinkLens as a Streamlit app (pure Python, no JavaScript).

How Streamlit works, in one line: it re-runs this file from top to bottom every time
the user interacts with the page. So the flow below is simply:
    1. draw the form  ->  2. if the user submitted, call analyze()  ->  3. draw the result

All the real logic lives in analyzer.py and suggestions.py (shared with the Flask version).

Run locally:   streamlit run streamlit_app.py
"""
import html
import math

import streamlit as st
import streamlit.components.v1 as components

from analyzer import analyze

st.set_page_config(page_title="LinkLens", page_icon="🔍", layout="centered")

LEVEL_COLOR = {"safe": "#3DE0A0", "caution": "#FFD60A", "danger": "#FF4D6D"}
SEV_COLOR = {"high": "#FF4D6D", "medium": "#FF9F1C", "low": "#62C4FF"}
SEV_BG = {"high": "rgba(255,77,109,.26)", "medium": "rgba(255,159,28,.24)", "low": "rgba(98,196,255,.20)"}
SEV_RANK = {"high": 3, "medium": 2, "low": 1}

EXAMPLES = {
    "fake PayPal": "http://paypa1-secure-login.xyz/verify/account/update",
    "raw IP": "http://185.220.101.4:8080/login.php",
    "@ trick": "https://paypal.com@evil-site.top/",
    "hidden redirect": "http://x8f3k29dkq1z.click/a?next=https://evil.com",
    "github.com": "https://github.com/anthropics",
}

# Small bits of styling on top of the dark-blue/yellow theme in .streamlit/config.toml
st.markdown(
    """
    <style>
      #MainMenu, footer { visibility: hidden; }
      h1 { letter-spacing: -0.01em; }
      .pct { font-size: 5.2rem; font-weight: 700; line-height: 1; margin-top: 8px; }
      .pct small { font-size: 1.4rem; font-weight: 500; color: #94A5D2; margin-left: 6px; }
      [data-testid="stFormSubmitButton"] button p { color: #050B1F; font-weight: 700; }
      [data-testid="stFormSubmitButton"] button { box-shadow: 0 0 22px rgba(255,214,10,.35); }
      .ll-card-text { color: #B5C2EA; margin: 2px 0 8px; }
      .ll-code { font-family: ui-monospace, Menlo, Consolas, monospace; color: #FFD60A;
                 background: rgba(255,214,10,.09); border: 1px solid rgba(255,214,10,.35);
                 padding: 1px 8px; border-radius: 5px; margin-right: 6px; overflow-wrap: anywhere; }
    </style>
    """,
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------- #
# Helpers (plain Python: easy to explain and to test)
# --------------------------------------------------------------------------- #
def safe(text: str) -> str:
    """Escape text that came from the analysed URL before it goes into HTML.
    (The URL is attacker-controlled, so we never let it be interpreted as markup.)"""
    return html.escape(str(text)).replace("$", "&#36;")


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
                f'color:#E6ECFF;padding:2px 1px;border-radius:3px">{text}</mark>'
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
        '<div style="font-family:ui-monospace,Menlo,Consolas,monospace;font-size:1.1rem;line-height:2.1;'
        'overflow-wrap:anywhere;background:#0B1736;border:1px solid #213574;border-radius:12px;padding:18px">'
        + "".join(parts) + "</div>"
    )


def pie_html(risk: int, color: str) -> str:
    """The risk pie chart as an inline SVG (drawn with plain trigonometry, no chart library).
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
        return (f'<text x="{x:.1f}" y="{y:.1f}" fill="{fill}" text-anchor="middle" '
                f'dominant-baseline="central" font-size="17" font-weight="700">{text}</text>')

    labels = ""
    if risk >= 12:
        labels += label(end / 2, f"{risk}%", "#050B1F")
    if risk <= 88:
        labels += label(end + (360 - end) / 2, f"{100 - risk}%", "#C9D6FF")

    return f"""<!doctype html><html><head><style>
      html, body {{ margin: 0; background: transparent; font-family: system-ui, sans-serif; color: #C9D6FF; }}
      .wrap {{ display: flex; flex-direction: column; align-items: center; gap: 10px; padding: 6px; }}
      svg {{ width: 100%; max-width: 250px; height: auto; overflow: visible; filter: drop-shadow(0 0 16px {color}88); }}
      .lg {{ display: flex; gap: 16px; font-size: 14px; flex-wrap: wrap; justify-content: center; }}
      .lg i {{ display: inline-block; width: 12px; height: 12px; border-radius: 3px; margin-right: 6px; vertical-align: -1px; }}
    </style></head><body><div class="wrap">
      <svg viewBox="0 0 200 200" role="img" aria-label="Pie chart: {risk}% risk, {100 - risk}% no sign of threat">
        <circle cx="100" cy="100" r="{R}" fill="#14275C" stroke="#2B428F" stroke-width="1.5"/>
        <path d="{path}" fill="{color}" stroke="#050B1F" stroke-width="2" stroke-linejoin="round"/>
        {labels}
      </svg>
      <div class="lg"><span><i style="background:{color}"></i>Risk {risk}%</span>
      <span><i style="background:#14275C;border:1px solid #3A55B0"></i>No sign of threat {100 - risk}%</span></div>
    </div></body></html>"""


@st.cache_data(ttl=600, show_spinner=False)
def run_check(url: str, live: bool, intent: str) -> dict:
    """Cache results for 10 minutes so repeated checks of the same link are instant."""
    return analyze(url, live=live, intent=intent)


def pick_example(url: str) -> None:
    """Button callback: fill the box and ask the main flow to run the check."""
    st.session_state["url"] = url
    st.session_state["auto_run"] = True


# --------------------------------------------------------------------------- #
# Result drawing
# --------------------------------------------------------------------------- #
def render(d: dict) -> None:
    color = LEVEL_COLOR[d["level"]]

    left, right = st.columns([1, 1.4])
    with left:
        components.html(pie_html(d["risk"], color), height=330)
    with right:
        st.markdown(f'<div class="pct" style="color:{color}">{d["risk"]}<small>% risk</small></div>',
                    unsafe_allow_html=True)
        st.subheader(d["headline"])
        st.write(d["advice"])

    alt = d["alternatives"]
    if alt:
        st.markdown(f"### {alt['headline']}")
        st.caption(alt["reason"])
        if alt["sites"]:
            for col, s in zip(st.columns(len(alt["sites"])), alt["sites"]):
                with col, st.container(border=True):
                    st.markdown(f"**{s['name']}**  ✅ Verified")
                    st.write(s["why"])
                    st.caption(s["tag"])
                    st.code(s["display"], language=None)
                    st.link_button("Open official site", s["url"])
        for tip in alt["tips"]:
            st.markdown(f"- {tip}")
        st.caption("Addresses come from a hand-curated list of official sites, not a live lookup. "
                   "Type the address yourself or use a bookmark rather than clicking it from a message.")

    st.markdown("### Where the problems are")
    st.caption("Numbers match the list below." if d["findings"] else "Nothing in this link needed highlighting.")
    st.markdown(highlight_url(d["url"], d["findings"]), unsafe_allow_html=True)
    if d["findings"]:
        st.markdown(
            '<span style="color:#FF4D6D">■ High</span> &nbsp; <span style="color:#FF9F1C">■ Medium</span> '
            '&nbsp; <span style="color:#62C4FF">■ Low</span>', unsafe_allow_html=True)

    st.markdown(f"### Every problem found ({len(d['findings'])})" if d["findings"] else "### Every problem found")
    if not d["findings"]:
        st.success("No problems found with this link.")
    for n, f in enumerate(d["findings"], 1):
        with st.container(border=True):
            sev_color = SEV_COLOR[f["severity"]]
            st.markdown(
                f'<b style="font-size:1.05rem">{n}. {safe(f["title"])}</b> &nbsp;'
                f'<span style="color:{sev_color};border:1px solid {sev_color};border-radius:999px;'
                f'padding:1px 9px;font-size:.78rem">{f["severity"].title()}</span>'
                f'<div class="ll-card-text">{safe(f["detail"])}</div>',
                unsafe_allow_html=True)
            snippets = list(dict.fromkeys(d["url"][a:b] for a, b in f["spans"]))[:6]
            if snippets:
                st.markdown("Found in: " + "".join(f'<span class="ll-code">{safe(s)}</span>' for s in snippets),
                            unsafe_allow_html=True)

    with st.expander(f"{len(d['passed'])} checks passed"):
        st.markdown("\n".join(f"- {p}" for p in d["passed"]))
    for note in d["notes"]:
        st.caption(note)
    st.caption("This is an automated estimate based on how the link is written and, if enabled, public domain "
               "records. It can miss threats and can flag harmless links. A low score is not a guarantee.")


# --------------------------------------------------------------------------- #
# Page
# --------------------------------------------------------------------------- #
st.title("Is this link safe to open?")
st.caption("Paste any link. We inspect the address itself, without opening the page, "
           "and mark every problem directly inside it.")

if "url" not in st.session_state:
    st.session_state["url"] = ""

with st.form("check"):
    st.text_input("Link to check", key="url", placeholder="Paste a link, e.g. http://paypa1-login.xyz/verify")
    st.text_input("What were you trying to find? (optional)", key="intent",
                  placeholder="e.g. track my parcel, download VLC, book a train ticket")
    live = st.checkbox("Also look up the domain (DNS, certificate, age)", value=True)
    submitted = st.form_submit_button("Check link", type="primary")

st.caption("Try an example:")
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
    st.divider()
    render(st.session_state["result"])
