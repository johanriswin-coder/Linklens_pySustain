"""
scanner.py - QR-code and message (SMS) checking for LinkLens.

This file ADDS two abilities on top of analyzer.py without changing it:

  1. analyze_message(text)      - paste a whole SMS / WhatsApp / e-mail text. We
       (a) look for scam wording ("account will be blocked", "share your OTP", fake
           delivery fees, prize bait ...),
       (b) pull every link out of the message and run each one through the existing
           analyzer.analyze(), and
       (c) check that the company the message *claims* to be from matches where the
           links actually go.
     The result is one risk percentage plus a list of reasons.

  2. analyze_qr_image(bytes)    - read the QR code(s) in a picture, then judge what is
     inside: a web link (-> analyze), a UPI payment request, Wi-Fi login, phone/SMS
     shortcut, crypto payment, or plain text (-> analyze_message).

Nothing here opens a link or downloads a page. The QR is only *decoded* (read), and
the optional live checks are the same DNS / certificate / WHOIS lookups analyzer.py
already does.

Every result dict has the same keys analyze() returns (url, risk, level, headline,
advice, findings, passed, notes ...) so the existing drawing code can show them.
"""
from __future__ import annotations

import io
import ipaddress
import re
from urllib.parse import parse_qs, urlsplit

from analyzer import BRANDS, SUSPICIOUS_TLDS, Finding, analyze, parse

MAX_MESSAGE_LENGTH = 5000          # characters
MAX_LINKS = 5                      # links analysed per message (each live check can take a few seconds)
MAX_IMAGE_BYTES = 8 * 1024 * 1024  # 8 MB upload limit for QR pictures
MAX_IMAGE_PIXELS = 40_000_000      # refuse "decompression bomb" images
MAX_DISPLAY = 600                  # characters of QR content shown on screen

_SEV_ORDER = {"high": 0, "medium": 1, "low": 2}


# --------------------------------------------------------------------------- #
# Small shared helpers
# --------------------------------------------------------------------------- #
def _normalize(text: str) -> str:
    """Unify line breaks and blank out control characters (1 char -> 1 char, so
    character positions used for highlighting stay valid)."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u2028\u2029]", " ", text)
    return text.strip()


def _one_line(text: str, limit: int | None = None) -> str:
    """Single-line version for on-screen display. The page injects this into an HTML
    block, where a blank line would break the block, so newlines become a visible
    arrow. It is 1 char -> 1 char, so highlight positions stay valid."""
    out = text.replace("\n", "\u21b5").replace("\t", " ")
    if limit and len(out) > limit:
        out = out[:limit] + "\u2026"
    return out


def _noisy_or(weights) -> int:
    """Same maths as analyzer._combine: independent warning signs compound, never above 99%."""
    survive = 1.0
    for w in weights:
        survive *= 1.0 - w
    return int(round(min(max((1.0 - survive) * 100, 3), 99)))


def _spans(text: str, pattern: str, negation: bool = False) -> list:
    out = []
    for m in re.finditer(pattern, text, re.I):
        if m.end() > m.start() and not (negation and _negated(text, m.start())):
            out.append((m.start(), m.end()))
    return out


_NEG = re.compile(
    r"\b(?:do not|don'?t|dont|never|not|won'?t|shouldn'?t|should not|cannot|can'?t)\b[^.!?\n]{0,25}$", re.I)


def _negated(text: str, pos: int) -> bool:
    """True for 'Do not share your OTP' / 'We will never ask you to share ...':
    real bank texts warn you NOT to do the thing, and must not be flagged for it."""
    return bool(_NEG.search(text[max(0, pos - 40):pos]))


def _words(text: str, spans: list, n: int = 5) -> str:
    seen = list(dict.fromkeys(text[a:b].lower() for a, b in spans))[:n]
    return ", ".join(f'"{s}"' for s in seen)


def _f(id_: str, title: str, detail: str, severity: str, weight: float, spans) -> Finding:
    return Finding(id_, title, detail, severity, weight, "message", spans=list(spans or []))


# --------------------------------------------------------------------------- #
# Finding links inside free text
# --------------------------------------------------------------------------- #
_COMMON_TLDS = {
    "com", "net", "org", "in", "co", "io", "info", "biz", "me", "ly", "gl", "to", "app",
    "link", "live", "online", "site", "store", "shop", "club", "vip", "pw", "ws", "cc",
    "tv", "us", "uk", "dev", "page", "bank", "pay", "life", "world", "website", "tech",
    "fun", "one", "pro", "ai", "ru", "cn", "de", "fr", "br", "au", "ca", "jp", "sg",
    "ae", "pk", "bd", "lk", "np", "ng", "za", "ph", "vn", "tr", "ir", "kr", "nl",
}
_TLD_ALT = "|".join(sorted(_COMMON_TLDS | SUSPICIOUS_TLDS, key=len, reverse=True))

# 1) anything://...   2) www.something   3) bare domain such as bit.ly/x or sbi-kyc.top/login
# 4) bare IPv4 address. (The TLD must be lower-case so "Thanks.In a minute" isn't a link.)
_LINK_RE = re.compile(
    r"""
      \b[a-z][a-z0-9+.\-]{1,15}://[^\s<>"'`]+
    | \bwww\.[^\s<>"'`]+
    | (?<![@\w.\-/])(?:[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.)+(?-i:""" + _TLD_ALT + r""")(?![\w\-])(?::\d{2,5})?(?:[/?#][^\s<>"'`]*)?
    | (?<![\w.\-/])(?:\d{1,3}\.){3}\d{1,3}(?::\d{2,5})?(?:/[^\s<>"'`]*)?
    """,
    re.I | re.X,
)
_TRAIL = ".,;:!?)]}>'\""


def extract_links(text: str) -> list:
    """Return [(link_text, start, end)] for every link-looking thing in `text`."""
    out = []
    for m in _LINK_RE.finditer(text):
        s, e = m.start(), m.end()
        while e > s and text[e - 1] in _TRAIL:
            e -= 1
        link = text[s:e]
        if len(link) < 4:
            continue
        if re.fullmatch(r"[\d.]+(?::\d+)?(?:/.*)?", link):      # looks like an IP: must be a real one
            try:
                ipaddress.ip_address(re.split(r"[:/]", link)[0])
            except ValueError:
                continue
        out.append((link, s, e))
    return out


# --------------------------------------------------------------------------- #
# Message checks: text -> Finding | None
# --------------------------------------------------------------------------- #
_SECRET = (r"(?:otp|one[- ]time (?:password|pin|passcode)|verification code|security code|cvv|cvc|"
           r"(?:upi |m|atm |net ?banking |card )?pin|password|passcode)")
_ASK_SHARE = (r"\b(?:send|share|provide|give|tell|reply with|read out|forward|disclose|dictate)\b"
              r"[^.!?\n]{0,30}?\b" + _SECRET + r"\b")
_ASK_ENTER = (r"\b(?:confirm|verify|update|enter|submit|provide|share|send)\b[^.!?\n]{0,30}?\b"
              r"(?:password|passcode|card (?:number|details)|debit card|credit card|bank details|"
              r"account number|cvv|upi pin|mpin|atm pin|seed phrase|recovery phrase|private key)\b")


def check_secrets(text: str):
    hits = _spans(text, _ASK_SHARE, negation=True) + _spans(text, _ASK_ENTER, negation=True)
    if hits:
        return _f(
            "ask_secret", "Asks for an OTP, PIN, password or card details",
            "Real banks and companies never ask you to send or read out an OTP, PIN, CVV or "
            "password, by message or by phone. Anyone who asks is trying to take over your account "
            "or money.", "high", 0.60, hits)


_LEGAL = (r"\b(?:arrest(?:ed)?|warrant|legal action|digital arrest|money laundering|"
          r"case (?:has been |is |was )?(?:registered|filed|booked)|fir|prosecut\w+|"
          r"court (?:notice|summons|case)|cyber ?crime (?:branch|cell|police)|narcotics|"
          r"illegal (?:items|parcel|activity))\b")


def check_legal_threat(text: str):
    hits = _spans(text, _LEGAL)
    if hits:
        return _f(
            "legal_threat", "Threatens arrest or legal action",
            f"The message uses frightening legal words ({_words(text, hits)}). Scammers pose as police, "
            "customs or courts to scare people into paying or sharing details. Real agencies do not "
            "do this by text message.", "high", 0.30, hits)


_T_NOUN = (r"(?:account|a/c|card|sim|kyc|upi|wallet|connection|electricity|power(?: supply)?|"
           r"service|number|profile|id|membership|subscription|policy)")
_T_VERB = (r"(?:blocked|suspended|deactivated|disabled|terminated|disconnected|frozen|restricted|"
           r"locked|closed|cancelled|canceled|expired)")
_ACCOUNT_THREAT = (rf"\b{_T_NOUN}\b[^.!?\n]{{0,40}}?\b(?:will be|has been|have been|is|was|stands?|gets?|"
                   rf"may be|shall be|to be)\s+{_T_VERB}\b|\b(?:will be|shall be)\s+{_T_VERB}\b")


def check_account_threat(text: str):
    hits = _spans(text, _ACCOUNT_THREAT)
    if hits:
        return _f(
            "account_threat", "Warns that something will be blocked or shut off",
            "\"Your account / SIM / electricity will be blocked\" is the most common scam opening. It "
            "creates panic so you click before thinking. If it is real, you can confirm it by opening "
            "the official app yourself.", "medium", 0.22, hits)


_KYC = (r"\bkyc\b[^.!?\n]{0,30}\b(?:update|verify|verification|expire[sd]?|pending|mandatory|suspend\w*|"
        r"incomplete|not (?:updated|verified))\b"
        r"|\b(?:pan|aadh?aar)\b[^.!?\n]{0,30}\b(?:update|verify|verification|link|linked|expire[sd]?|pending|"
        r"mandatory|suspend\w*)\b"
        r"|\b(?:update|verify|complete|renew)\b[^.!?\n]{0,25}\b(?:kyc|pan|aadh?aar)\b")


def check_kyc(text: str):
    hits = _spans(text, _KYC)
    if hits:
        return _f(
            "kyc", "Demands a KYC / PAN / Aadhaar update",
            "\"Update your KYC or PAN or your account will close\" is a very widespread fraud. Banks "
            "do KYC updates inside their official app or at a branch, not through a link in a message.",
            "high", 0.28, hits)


_URGENT = (r"\b(?:urgent(?:ly)?|immediate(?:ly)?|act now|right away|asap|last (?:chance|warning|reminder)|"
           r"final (?:notice|warning|reminder)|expires? (?:today|tonight|soon)|within \d+ ?(?:hours?|hrs?)|"
           r"before (?:midnight|today)|today only|hurry|don'?t (?:delay|ignore)|time[- ]sensitive|"
           r"limited time|(?:blocked|suspended|closed|disconnected) (?:today|tonight|within))\b")


def check_urgency(text: str):
    hits = _spans(text, _URGENT)
    if len(hits) >= 2:
        return _f("urgency", "Pressures you to act fast",
                  f"The message pushes a deadline ({_words(text, hits)}). Scammers rush you so you "
                  "don't stop to check.", "medium", 0.15, hits)
    if hits:
        return _f("urgency", "Contains urgent wording",
                  f"The message says {_words(text, hits)}. Alone this is common, but combined with other "
                  "signs it is a pressure tactic.", "low", 0.07, hits)


_PRIZE = (r"\b(?:you(?:'ve| have)? (?:won|been selected|been chosen|are selected|are eligible)|"
          r"congratulations?|lucky (?:winner|draw|customer|user)|winner|lottery|jackpot|prize|"
          r"free (?:gift|iphone|recharge|data|cash|laptop|coupon)|claim (?:your|now|the|it)|kbc)\b")
_PRIZE_MILD = r"\b(?:cashback|voucher|redeem|bonus|gift card|reward points?|coupon)\b"


def check_prize(text: str):
    hits = _spans(text, _PRIZE)
    if hits:
        many = len({text[a:b].lower() for a, b in hits}) >= 2      # several different bait phrases
        return _f("prize", "Dangles a prize, lottery or free gift",
                  f"The message uses bait words ({_words(text, hits)}). You cannot win a contest you never "
                  "entered, and \"claiming\" the prize is how scammers collect fees and details.",
                  "high" if many else "medium", 0.40 if many else 0.20, hits)
    mild = _spans(text, _PRIZE_MILD)
    if mild:
        return _f("prize_mild", "Mentions rewards or vouchers",
                  f"The message mentions {_words(text, mild)}. This is normal in genuine offers, but "
                  "it is also how scam links are made to look attractive.", "low", 0.07, mild)


_FEE_ALTS = [
    r"\b(?:processing|clearance|customs|redelivery|re-delivery|delivery|handling|registration|release|admin|"
    r"verification|activation|advance|insurance|tax|gst|service) (?:fee|fees|charge|charges|payment|duty)\b",
    r"\bpay (?:a |an |the )?(?:small |nominal |minimal |token )?(?:fee|fine|charge|amount|penalty|deposit)\b",
    r"\bpay (?:rs\.?|inr|\u20b9|\$)\s?\d",
    r"(?<![a-z])(?:rs\.?|inr|\u20b9)\s?\d[\d,]*\s?(?:only )?(?:to (?:release|receive|claim|unblock|reactivate|avoid)|fee|charge)",
    r"\bpending (?:payment|dues?|amount|bill)\b",
    r"\b(?:unpaid|overdue) (?:bill|dues?|amount|fine|challan)\b",
    r"\bchallan\b",
]


def check_fee(text: str):
    hits = _spans(text, "|".join(_FEE_ALTS))
    if hits:
        return _f("fee", "Asks you to pay a fee, fine or pending amount",
                  f"The message talks about a payment ({_words(text, hits)}). Fake \"customs fee\", "
                  "\"redelivery fee\" and \"e-challan\" messages are a favourite way to get card or UPI "
                  "details. Check any bill or fine on the official site or app, not through a message link.",
                  "medium", 0.22, hits)


_DELIVERY = (r"\b(?:package|parcel|shipment|courier|consignment|order)\b[^.!?\n]{0,60}?\b(?:on hold|held|"
             r"could not be delivered|couldn'?t be delivered|undelivered|delivery (?:failed|attempt)|"
             r"failed delivery|address (?:is |was )?(?:incomplete|invalid|wrong|missing)|incomplete address|"
             r"unable to deliver|returned to sender|returned|stuck|customs)\b"
             r"|\b(?:reschedule|re-?schedule|redeliver|re-?deliver|confirm (?:your )?(?:delivery|address))\w*")


def check_delivery(text: str):
    hits = _spans(text, _DELIVERY)
    if hits:
        return _f("delivery", "Looks like a fake delivery notice",
                  "\"Your parcel is on hold / address incomplete\" texts are mass-sent to everyone, "
                  "whether or not they are expecting anything. Track real parcels only in the courier's "
                  "own app or on the shop's order page.", "medium", 0.18, hits)


_MONEY_ALTS = [
    r"\bwork from home\b", r"\bpart[- ]?time (?:job|work)\b", r"\bonline job\b", r"\bdata entry job\b",
    r"\bearn (?:up ?to |upto )?(?:(?<![a-z])rs\.?|inr|\u20b9|\$)?\s?\d[\d,]*",
    r"(?<![a-z])(?:rs\.?|inr|\u20b9)\s?\d[\d,]*\s?(?:/|per|a|each)\s?(?:day|daily|hour|week)\b",
    r"\bguaranteed (?:returns?|profit|income)\b", r"\bdouble your money\b", r"\bdaily (?:income|payout|salary)\b",
    r"\binvestment (?:plan|opportunity|scheme)\b", r"\b(?:trading|stock) (?:tips|group|signals)\b",
    r"\bcrypto (?:investment|trading)\b", r"\bhiring (?:now|urgently)\b",
    r"\bno (?:experience|investment) (?:needed|required)\b",
]


def check_money_making(text: str):
    hits = _spans(text, "|".join(_MONEY_ALTS))
    if hits:
        return _f("money_pitch", "Looks like a get-rich, job or investment pitch",
                  f"The message promises easy money ({_words(text, hits)}). Unrequested \"earn daily from "
                  "home\" and \"guaranteed returns\" offers are the usual start of task, job and investment scams.",
                  "medium", 0.25, hits)


def check_apk(text: str):
    hits = _spans(text, r"\.apk\b|\bapk\b")
    if hits:
        return _f("apk", "Tells you to install an .apk file",
                  "Installing an app file sent in a message bypasses the Play Store's safety checks. "
                  "Fake \"KYC\", \"challan\" and \"bank\" apps are used to read your SMS and empty your account.",
                  "high", 0.35, hits)


def check_remote_access(text: str):
    hits = _spans(text, r"\b(?:anydesk|any desk|teamviewer|team viewer|quick ?support|airdroid|rustdesk|ultraviewer)\b")
    if hits:
        return _f("remote_access", "Asks you to install a remote-control app",
                  "Remote-access apps let someone see and control your phone or computer. Scammers talk "
                  "victims into installing them, then drain bank accounts. No genuine company needs this by message.",
                  "high", 0.50, hits)


def check_contact(text: str):
    hits = _spans(text, r"\b(?:call|contact|whatsapp|dial|text|message|msg|reach)\b[^.!?\n]{0,30}?"
                        r"(?:\+\d{1,3}[\s-]?)?\d[\d\s-]{8,13}\d")
    if hits:
        return _f("contact", "Pushes you to call or message a phone number",
                  "Scammers include a number so they can talk you through handing over details, outside "
                  "the reach of link scanners. Look the number up on the company's official website or "
                  "the back of your card instead of using the one in the message.", "low", 0.08, hits)


def check_greeting(text: str):
    m = re.match(r"\s*(?:dear|hello|hi|hey|greetings)[, ]+\s*(?:valued |respected )?(?:customer|user|sir|madam|"
                 r"sir/madam|sir or madam|member|client|account holder|winner|beneficiary)\b", text, re.I)
    if m:
        return _f("greeting", "Generic greeting instead of your name",
                  "Mass-sent scam messages say \"Dear customer\" because the sender does not know who you are. "
                  "Your bank or shop normally uses your name.", "low", 0.06, [(m.start(), m.end())])


def check_shouting(text: str):
    letters = [c for c in text if c.isalpha()]
    if len(letters) >= 25 and sum(c.isupper() for c in letters) / len(letters) >= 0.6:
        return _f("shouting", "Written mostly in capital letters",
                  "ALL-CAPS messages are designed to feel urgent. Genuine notifications are usually written normally.",
                  "low", 0.05, [])


# (id, label shown when the check passes, function)
MESSAGE_CHECKS = [
    ("secrets", "Doesn't ask you to share an OTP, PIN or password", check_secrets),
    ("legal", "No threat of arrest or legal action", check_legal_threat),
    ("account", "No \"account will be blocked\" warning", check_account_threat),
    ("kyc", "No KYC / PAN / Aadhaar update demand", check_kyc),
    ("urgency", "No artificial urgency", check_urgency),
    ("prize", "No prize, lottery or free-gift bait", check_prize),
    ("fee", "Doesn't demand a fee, fine or pending payment", check_fee),
    ("delivery", "Not a fake delivery notice", check_delivery),
    ("money", "Not a get-rich, job or investment pitch", check_money_making),
    ("apk", "Doesn't push an .apk install", check_apk),
    ("remote", "Doesn't ask for a remote-control app", check_remote_access),
    ("contact", "Doesn't push you to call or message a number", check_contact),
    ("greeting", "Doesn't use a generic \"Dear customer\" greeting", check_greeting),
    ("shouting", "Normal tone (not shouting)", check_shouting),
]

# Extra words people actually write for a brand (the key in BRANDS is often a domain-style label).
_BRAND_ALIASES = {"hdfcbank": ["hdfc"], "icicibank": ["icici"], "sbi": ["sbi", "state bank of india"]}


def check_brand_mismatch(text: str, link_items: list):
    """The message names a company, but none of its links go to that company's real domain."""
    domains = []
    for it in link_items:
        try:
            p = parse(it["text"])
        except ValueError:
            continue
        domains.append((p, p.registered or p.host))
    if not domains:
        return None
    for brand, real in BRANDS.items():
        words = [brand] + _BRAND_ALIASES.get(brand, [])
        mentions = _spans(text, r"\b(?:" + "|".join(re.escape(w) for w in words) + r")\b")
        if not mentions:
            continue
        if any(p.registered in real or any(p.host.endswith("." + r) for r in real) for p, _ in domains):
            continue                                   # at least one link really goes to the brand
        shown = ", ".join(dict.fromkeys(d for _, d in domains))[:120]
        return _f(
            "brand_mismatch", f"Claims to be {brand.title()} but links somewhere else",
            f"The message mentions {brand.title()}, but none of its links go to {brand.title()}'s real "
            f"website ({sorted(real)[0]}). They go to: {shown}. Real companies link to their own domain.",
            "high", 0.30, mentions[:3])
    return None


# --------------------------------------------------------------------------- #
# Wording of the verdict for each kind of thing we check
# --------------------------------------------------------------------------- #
_VERDICTS = {
    "message": (
        ("danger", "Do not trust this message",
         "This has the hallmarks of a scam message. Don't click its links, don't call numbers in it, and "
         "never share OTPs, PINs or passwords. If it claims to be from a bank or company, contact them "
         "using the number on their official website or the back of your card."),
        ("caution", "Be careful with this message",
         "Some warning signs showed up. Don't click links or reply from the message itself; check with "
         "the sender or company through an official channel first."),
        ("safe", "No major warning signs",
         "Nothing here matches common scam patterns. No check is perfect, though: stay alert if you are "
         "asked for passwords, OTPs or payments you weren't expecting."),
    ),
    "payment": (
        ("danger", "Do not pay with this QR code",
         "This payment QR has strong warning signs. Don't approve it in your UPI app, and never enter your "
         "UPI PIN to \"receive\" money: the PIN is only ever needed to send it."),
        ("caution", "Check before you pay",
         "Read the payee name and amount your UPI app shows before approving. You only scan a QR to pay "
         "someone, never to receive a refund or prize."),
        ("safe", "No major warning signs",
         "Nothing unusual in this payment QR. Still check the payee name in your UPI app before approving."),
    ),
    "other": (
        ("danger", "Do not use this QR code",
         "This QR code has strong warning signs. Don't act on it."),
        ("caution", "Be careful with this QR code",
         "Some warning signs showed up. Only continue if you trust where you found this code."),
        ("safe", "No major warning signs",
         "Nothing unusual in this QR code's content. QR stickers can be pasted over genuine ones, so be "
         "cautious with codes in public places."),
    ),
}


def _verdict(kind: str, risk: int):
    tier = 0 if risk >= 55 else 1 if risk >= 25 else 2
    return _VERDICTS[kind][tier]


def _package(kind: str, display: str, findings: list, passed: list, notes: list) -> dict:
    """Build a result dict shaped like analyzer.analyze()'s, from our own findings."""
    risk = _noisy_or([f.weight for f in findings])
    level, headline, advice = _verdict(kind, risk)
    findings = sorted(findings, key=lambda f: (_SEV_ORDER[f.severity], -f.weight))
    return {
        "url": display, "risk": risk, "level": level, "headline": headline, "advice": advice,
        "findings": [{"id": f.id, "title": f.title, "detail": f.detail, "severity": f.severity,
                      "spans": [list(s) for s in f.spans]} for f in findings],
        "passed": passed, "alternatives": None, "notes": notes,
        "live": {"requested": False, "ran": False},
    }


# --------------------------------------------------------------------------- #
# 1. Whole-message analysis
# --------------------------------------------------------------------------- #
def analyze_message(raw: str, live: bool = True) -> dict:
    text = _normalize(raw)
    if not text:
        raise ValueError("Paste a message to check.")
    if len(text) > MAX_MESSAGE_LENGTH:
        raise ValueError(f"That message is too long (limit is {MAX_MESSAGE_LENGTH} characters).")

    found: list[Finding] = []
    passed: list[str] = []
    notes: list[str] = []

    for _id, label, fn in MESSAGE_CHECKS:
        result = fn(text)
        if result:
            found.append(result)
        else:
            passed.append(label)

    done = {f.id: f for f in found}
    if "delivery" in done and "fee" in done:                 # the classic "parcel on hold, pay a small fee" template
        found.append(_f(
            "parcel_fee_combo", "Fake parcel notice plus a fee demand",
            "A delivery problem followed by a request to pay a small fee is the textbook parcel scam: the "
            "fee page exists only to capture your card or UPI details.", "high", 0.25,
            done["delivery"].spans + done["fee"].spans))

    # --- the links inside the message, each judged by the existing analyzer ---
    unique: dict[str, list] = {}
    for link, a, b in extract_links(text):
        unique.setdefault(link, []).append((a, b))
    link_items = []
    for i, (link, spans) in enumerate(unique.items()):
        if i >= MAX_LINKS:
            notes.append(f"Only the first {MAX_LINKS} links were analysed; {len(unique) - MAX_LINKS} more skipped.")
            break
        try:
            result = analyze(link, live=live)
        except ValueError as err:                      # static, safe message from analyzer.parse()
            notes.append(f"Link {i + 1} couldn't be analysed: {err}")
            continue
        link_items.append({"text": link, "spans": spans, "result": result})

    if not link_items:
        notes.append("No links were found in this message, so only its wording was checked.")
    else:
        pressure = any(f.weight >= 0.15 for f in found)     # avoids flagging "apple" in a casual chat
        mismatch = check_brand_mismatch(text, link_items) if pressure else None
        if mismatch:
            found.append(mismatch)
        else:
            passed.append("Company named in the message matches where its links go")

    # one card per risky link, highlighted in the message itself (weight 0: its risk is counted below)
    for it in link_items:
        r = it["result"]
        if r["level"] != "safe":
            top = "; ".join(f["title"] for f in r["findings"][:3])
            word = "dangerous" if r["level"] == "danger" else "suspicious"
            found.append(Finding(
                "risky_link", f"Link looks {word} ({r['risk']}% risk)",
                f"{top}. Open the link-by-link report below for every reason.",
                "high" if r["level"] == "danger" else "medium", 0.0, "message", spans=it["spans"]))

    worst_link = max((it["result"]["risk"] for it in link_items), default=0)
    risk = _noisy_or([f.weight for f in found] + ([worst_link / 100] if worst_link else []))
    level, headline, advice = _verdict("message", risk)
    found.sort(key=lambda f: (_SEV_ORDER[f.severity], -f.weight))
    link_items.sort(key=lambda it: -it["result"]["risk"])

    return {
        "kind": "message",
        "text": _one_line(text),
        "risk": risk, "level": level, "headline": headline, "advice": advice,
        "findings": [{"id": f.id, "title": f.title, "detail": f.detail, "severity": f.severity,
                      "spans": [list(s) for s in f.spans]} for f in found],
        "links": link_items,
        "passed": passed, "notes": notes,
    }


# --------------------------------------------------------------------------- #
# 2. QR codes
# --------------------------------------------------------------------------- #
def decode_qr(data: bytes) -> list[str]:
    """Read every QR code in an image and return their text. Only *reads*; opens nothing."""
    try:
        import cv2
        import numpy as np
        from PIL import Image, ImageOps
    except ImportError as err:                         # pragma: no cover
        raise RuntimeError("QR scanning needs extra packages. Run: pip install opencv-python-headless Pillow") from err

    try:
        img = Image.open(io.BytesIO(data))
        if img.width * img.height > MAX_IMAGE_PIXELS:
            raise ValueError("That picture is too large. Try a smaller photo or screenshot.")
        img = ImageOps.exif_transpose(img).convert("RGB")
    except ValueError:
        raise
    except Exception:
        raise ValueError("That file isn't a picture I can read. Upload a PNG or JPG of the QR code.")
    if max(img.size) > 2400:
        img.thumbnail((2400, 2400))

    bgr = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    attempts = [
        bgr, gray,
        cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC),
        cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 10),
        cv2.resize(gray, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA),
    ]
    detector = cv2.QRCodeDetector()
    results: list[str] = []
    for image in attempts:
        try:
            ok, decoded, _, _ = detector.detectAndDecodeMulti(image)
            if ok:
                results += [d for d in decoded if d]
        except cv2.error:
            pass
        if not results:
            try:
                value, _, _ = detector.detectAndDecode(image)
                if value:
                    results.append(value)
            except cv2.error:
                pass
        if results:
            break
    return list(dict.fromkeys(results))


def _param_span(payload: str, key: str):
    m = re.search(rf"[?&]{key}=([^&]*)", payload, re.I)
    return [(m.start(1), m.end(1))] if m and m.end(1) > m.start(1) else []


_SCAMMY_PAYEE = (r"refund|cashback|reward|prize|lottery|helpdesk|help desk|customer (?:care|support|service)|"
                 r"kyc|official|claim")


def _upi(payload: str) -> dict:
    try:
        q = {k.lower(): v[0] for k, v in parse_qs(urlsplit(payload).query).items()}
    except ValueError:
        q = {}
    pa, pn, am, cu = q.get("pa", ""), q.get("pn", ""), q.get("am", ""), (q.get("cu") or "INR").upper()
    findings, passed = [], []

    if am:
        findings.append(_f(
            "upi_amount", f"Asks you to pay {am} {cu}",
            "Scanning this code and approving it in your UPI app SENDS money. You never need to scan a QR "
            "code or enter your UPI PIN to receive money. If someone said this code will refund, pay or "
            "reward you, it is a scam.", "medium", 0.25, _param_span(payload, "am")))
    else:
        findings.append(_f(
            "upi_request", "This QR code is a payment request",
            "Scanning it opens your UPI app to pay the payee shown. Only continue if you meant to pay "
            "this person or shop. Receiving money never needs a scan.", "low", 0.10, [(0, len(payload))]))

    if pn and re.search(_SCAMMY_PAYEE, pn + " " + pa, re.I):
        findings.append(_f(
            "upi_payee", "Payee name looks like an official or reward account",
            "The payee name or UPI ID includes words like refund, reward or support. Scammers name accounts "
            "this way to look official.", "medium", 0.25, _param_span(payload, "pn") or _param_span(payload, "pa")))
    elif pn:
        passed.append("Payee name has no refund / reward / support wording")
    if not pn:
        findings.append(_f(
            "upi_no_name", "No payee name in the QR code",
            "Without a name you can't tell who you are paying. Check the name your UPI app shows before approving.",
            "low", 0.08, []))
    notes = ["LinkLens can't verify who owns a UPI ID. Always read the payee name your UPI app shows before you approve."]
    return _package("payment", _one_line(payload, MAX_DISPLAY), findings, passed, notes)


def _special(low: str, payload: str):
    """QR contents that are not web links. Returns (kind, label, result) or None."""
    disp = _one_line(payload, MAX_DISPLAY)
    if low.startswith("upi:"):
        return "payment", "UPI payment request", _upi(payload)
    if low.startswith(("tel:", "sms:", "smsto:", "mmsto:")):
        what = "Starts a phone call" if low.startswith("tel:") else "Prepares a text message"
        f = _f("phone_action", what,
               "Scanning will dial a number or pre-fill a text for you to send. Scam QR codes use this for "
               "premium-rate calls and paid texts. Check the number before you confirm.",
               "medium", 0.20, [(0, len(payload))])
        return "other", "Phone / SMS shortcut", _package("other", disp, [f], [], [])
    if low.startswith("mailto:"):
        f = _f("email_action", "Opens an email draft",
               "Scanning will start an email to the address inside. Only send something if you trust who it is to.",
               "low", 0.08, [(0, len(payload))])
        return "other", "E-mail shortcut", _package("other", disp, [f], [], [])
    if low.startswith("wifi:"):
        ssid = re.search(r"S:((?:\\.|[^;])*)", payload, re.I)
        kind = re.search(r"T:([^;]*)", payload, re.I)
        name = ssid.group(1) if ssid else "unknown"
        fs = [_f("wifi_join", f"Joins the Wi-Fi network \"{name}\"",
                 "Scanning will connect your phone to this network. Fake Wi-Fi networks can watch or tamper "
                 "with your traffic. Join only if you trust the place that displayed the code.",
                 "low", 0.12, [(0, len(payload))])]
        if kind and kind.group(1).strip().lower() in ("nopass", ""):
            fs.append(_f("wifi_open", "The network has no password",
                         "Open networks offer no encryption, so others nearby can read what you send.",
                         "medium", 0.25, [(0, len(payload))]))
        return "other", "Wi-Fi login", _package("other", disp, fs, [], [])
    if low.startswith(("bitcoin:", "ethereum:", "litecoin:", "monero:")):
        f = _f("crypto_pay", "Cryptocurrency payment request",
               "Crypto payments cannot be reversed. Scammers use QR codes to collect payments for fake "
               "investments, giveaways and \"recovery\" services. Only pay someone you know and trust.",
               "medium", 0.25, [(0, len(payload))])
        return "other", "Crypto payment request", _package("other", disp, [f], [], [])
    return None


_DANGEROUS_PREFIXES = ("javascript:", "data:", "vbscript:", "file:", "blob:")


def analyze_qr_payload(payload: str, live: bool = True) -> dict:
    """Judge the text found inside one QR code."""
    p = _normalize(payload)
    low = p.lower()
    display = _one_line(p, MAX_DISPLAY)

    special = _special(low, p)
    if special:
        kind, label, result = special
        return {"kind": kind, "label": label, "display": display, "result": result}

    if low.startswith(_DANGEROUS_PREFIXES):
        try:
            return {"kind": "link", "label": "Web link", "display": display,
                    "result": analyze(p, live=False)}
        except ValueError:
            pass

    links = extract_links(p)
    if len(links) == 1 and links[0][1] == 0 and len(p) - links[0][2] <= 1:    # the whole code IS one link
        try:
            return {"kind": "link", "label": "Web link", "display": display,
                    "result": analyze(links[0][0], live=live)}
        except ValueError:
            pass

    if not links and " " not in p and "\n" not in p and re.match(r"^[a-z][a-z0-9+.\-]*:", low):
        f_note = "LinkLens has no specific checks for this type of QR content, so nothing was flagged."
        return {"kind": "other", "label": "Other content", "display": display,
                "result": _package("other", display, [], ["Not a web link or payment request"], [f_note])}

    result = analyze_message(p, live=live)
    result["notes"].insert(0, "This QR code holds text rather than a single link, so it was checked like a message.")
    return {"kind": "message", "label": "Text / message", "display": display, "result": result}


def analyze_qr_image(data: bytes, live: bool = True) -> list[dict]:
    """Decode every QR code in the picture and analyse each one."""
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("That picture is larger than 8 MB. Try a smaller photo or screenshot.")
    payloads = decode_qr(data)
    if not payloads:
        raise ValueError("I couldn't find a QR code in that picture. Try a sharper, closer shot with the whole "
                         "code in frame, good lighting, and no glare.")
    return [analyze_qr_payload(p, live=live) for p in payloads[:5]]
