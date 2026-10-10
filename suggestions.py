"""
suggestions.py - "safer places to get this" for risky links.

When a link scores as risky, LinkLens tries to work out what the person was
after and points them to verified official sites instead. It uses three signals,
strongest first:

  1. Brand impersonation: the link pretends to be PayPal -> suggest the real PayPal.
  2. What the person typed in the optional "what were you trying to find?" box.
  3. Words inside the link itself (track, download, movie, kyc ...).

The directory below is a hand-curated list, NOT a live lookup. Keep every entry
to an official, well-known address, and run `python test_suggestions.py` after
editing: it checks that each brand entry really belongs to that brand and that
LinkLens itself rates every suggested address as low risk.
"""
from __future__ import annotations

import re

MIN_RISK = 25        # only suggest alternatives for "caution" and "danger" links
MAX_SITES = 3

_GEN_SOFT = ["download", "install", "setup", "software", "crack", "keygen", "apk", "exe"]
_GEN_SHIP = ["track", "tracking", "package", "parcel", "delivery", "shipment", "courier", "shipping"]
_GEN_BANK = ["bank", "banking", "balance", "kyc", "netbanking", "debit card", "credit card"]
_GEN_CRYPTO = ["crypto", "bitcoin", "ethereum", "wallet", "airdrop", "token", "nft", "exchange"]
_GEN_SHOP = ["shop", "shopping", "deal", "deals", "discount", "sale", "buy", "order", "gift card"]
_GEN_WATCH = ["movie", "movies", "watch", "series", "stream", "streaming", "episode", "episodes"]
_GEN_JOBS = ["job", "jobs", "career", "careers", "internship", "hiring", "vacancy", "recruitment", "offer letter"]
_GEN_LEARN = ["course", "courses", "learn", "learning", "certificate", "tutorial", "lecture", "lectures"]
_GEN_HEALTH = ["health", "symptom", "symptoms", "medicine", "vaccine", "disease"]


def _s(name, url, blurb, keywords, category, brand=None):
    return {"name": name, "url": url, "blurb": blurb, "keywords": keywords,
            "category": category, "brand": brand}


DIRECTORY = [
    # ---- brands (the "brand" key must match a key in analyzer.BRANDS) ----
    _s("PayPal", "https://www.paypal.com", "Send, receive and manage payments. Log in only from the official site.", ["paypal"], "payments", "paypal"),
    _s("Google", "https://www.google.com", "Search, plus sign-in for Gmail, Drive and your Google Account.", ["google"], "accounts", "google"),
    _s("Microsoft", "https://www.microsoft.com", "Windows, Office, Outlook and your Microsoft account.", ["microsoft", "office", "windows"], "accounts", "microsoft"),
    _s("Apple", "https://www.apple.com", "Apple ID, iCloud, devices and support.", ["apple", "icloud", "iphone", "apple id"], "accounts", "apple"),
    _s("Amazon", "https://www.amazon.com", "Shop and track your Amazon orders.", ["amazon"] + _GEN_SHOP, "shopping", "amazon"),
    _s("Facebook", "https://www.facebook.com", "Your Facebook account and pages.", ["facebook"], "social", "facebook"),
    _s("Instagram", "https://www.instagram.com", "Your Instagram account.", ["instagram"], "social", "instagram"),
    _s("WhatsApp", "https://www.whatsapp.com", "Download WhatsApp and get official help.", ["whatsapp"], "social", "whatsapp"),
    _s("Netflix", "https://www.netflix.com", "Watch shows and movies with your Netflix account.", ["netflix"] + _GEN_WATCH, "streaming", "netflix"),
    _s("LinkedIn", "https://www.linkedin.com", "Your professional profile and messages.", ["linkedin"], "social", "linkedin"),
    _s("GitHub", "https://github.com", "Code hosting, repositories and open-source projects.", ["github", "repo", "repository", "source code", "open source"], "dev", "github"),
    _s("Dropbox", "https://www.dropbox.com", "Store and share files. Open shared files from inside your own account.", ["dropbox", "shared file", "file transfer"], "cloud", "dropbox"),
    _s("Paytm", "https://paytm.com", "Payments, recharges and wallet.", ["paytm", "upi", "recharge"], "payments", "paytm"),
    _s("PhonePe", "https://www.phonepe.com", "UPI payments and recharges.", ["phonepe", "upi", "recharge"], "payments", "phonepe"),
    _s("HDFC Bank", "https://www.hdfcbank.com", "Official HDFC Bank site for net banking and support.", ["hdfc", "hdfcbank"] + _GEN_BANK, "banking", "hdfcbank"),
    _s("ICICI Bank", "https://www.icicibank.com", "Official ICICI Bank site for net banking and support.", ["icici", "icicibank"] + _GEN_BANK, "banking", "icicibank"),
    _s("State Bank of India", "https://sbi.co.in", "Official SBI site for banking services and support.", ["sbi", "state bank"] + _GEN_BANK, "banking", "sbi"),
    _s("Binance", "https://www.binance.com", "Crypto exchange. Always type the address yourself before logging in.", ["binance"] + _GEN_CRYPTO, "crypto", "binance"),
    _s("Coinbase", "https://www.coinbase.com", "Crypto exchange and wallet.", ["coinbase"] + _GEN_CRYPTO, "crypto", "coinbase"),
    _s("MetaMask", "https://metamask.io", "The official wallet download page. Never share your recovery phrase.", ["metamask"] + _GEN_CRYPTO, "crypto", "metamask"),
    _s("Steam", "https://store.steampowered.com", "Buy and manage games on Steam.", ["steam", "game", "games", "gaming"], "gaming", "steam"),
    _s("Discord", "https://discord.com", "Download Discord and manage your account.", ["discord", "nitro"], "social", "discord"),
    _s("DHL", "https://www.dhl.com", "Official DHL shipment tracking.", ["dhl"] + _GEN_SHIP, "shipping", "dhl"),
    _s("FedEx", "https://www.fedex.com", "Official FedEx shipment tracking.", ["fedex"] + _GEN_SHIP, "shipping", "fedex"),

    # ---- shipping ----
    _s("UPS", "https://www.ups.com", "Official UPS shipment tracking.", ["ups"] + _GEN_SHIP, "shipping"),
    _s("USPS", "https://www.usps.com", "Official US Postal Service tracking and mail services.", ["usps", "postal"] + _GEN_SHIP, "shipping"),
    _s("India Post", "https://www.indiapost.gov.in", "Official India Post tracking and services.", ["india post", "speed post"] + _GEN_SHIP, "shipping"),

    # ---- software downloads ----
    _s("Google Chrome", "https://www.google.com/chrome/", "Download Chrome straight from Google.", ["chrome", "browser"] + _GEN_SOFT, "software"),
    _s("Mozilla Firefox", "https://www.mozilla.org/firefox/", "Download Firefox straight from Mozilla.", ["firefox", "mozilla", "browser"] + _GEN_SOFT, "software"),
    _s("VLC media player", "https://www.videolan.org/vlc/", "The official free VLC download.", ["vlc", "media player", "video player"] + _GEN_SOFT, "software"),
    _s("Python", "https://www.python.org/downloads/", "Official Python installers.", ["python", "pip"] + _GEN_SOFT, "software"),
    _s("7-Zip", "https://www.7-zip.org", "The official free archive tool.", ["7zip", "7-zip", "unzip", "winrar", "archive"] + _GEN_SOFT, "software"),

    # ---- government and tax ----
    _s("Income Tax Department (India)", "https://www.incometax.gov.in", "File returns and check refunds on the official portal.", ["income tax", "itr", "pan", "tax refund", "refund", "tax"], "gov"),
    _s("IRS (United States)", "https://www.irs.gov", "Official US tax information and refund status.", ["irs", "tax refund", "refund", "tax", "taxes"], "gov"),
    _s("UIDAI (Aadhaar)", "https://uidai.gov.in", "Official Aadhaar services.", ["aadhaar", "aadhar", "uidai"], "gov"),
    _s("Passport Seva", "https://www.passportindia.gov.in", "Official passport applications and tracking (India).", ["passport"], "gov"),
    _s("India.gov.in", "https://www.india.gov.in", "National portal linking to official government services.", ["government", "scheme", "subsidy", "certificate"], "gov"),
    _s("USA.gov", "https://www.usa.gov", "Official guide to US government services.", ["government", "benefits", "citizen"], "gov"),

    # ---- health ----
    _s("World Health Organization", "https://www.who.int", "Global health guidance from the WHO.", ["who", "outbreak"] + _GEN_HEALTH, "health"),
    _s("CDC", "https://www.cdc.gov", "US public health information.", ["cdc"] + _GEN_HEALTH, "health"),
    _s("NHS", "https://www.nhs.uk", "Trusted UK health advice and symptom guides.", ["nhs"] + _GEN_HEALTH, "health"),
    _s("MedlinePlus", "https://medlineplus.gov", "Plain-language information on drugs, conditions and tests.", ["drug", "medical"] + _GEN_HEALTH, "health"),

    # ---- learning ----
    _s("Coursera", "https://www.coursera.org", "Courses and certificates from universities and companies.", ["coursera", "free course"] + _GEN_LEARN, "learning"),
    _s("edX", "https://www.edx.org", "University courses and certificates.", ["edx"] + _GEN_LEARN, "learning"),
    _s("Khan Academy", "https://www.khanacademy.org", "Free lessons and practice.", ["khan", "lesson", "study", "math"] + _GEN_LEARN, "learning"),
    _s("NPTEL", "https://nptel.ac.in", "Free engineering and science courses from the IITs and IISc.", ["nptel", "engineering", "certification"] + _GEN_LEARN, "learning"),

    # ---- jobs ----
    _s("LinkedIn Jobs", "https://www.linkedin.com/jobs/", "Job listings from verified company pages.", ["linkedin"] + _GEN_JOBS + ["work from home"], "jobs"),
    _s("Indeed", "https://www.indeed.com", "Job search and company reviews.", ["indeed"] + _GEN_JOBS, "jobs"),
    _s("Naukri", "https://www.naukri.com", "Job search for India.", ["naukri"] + _GEN_JOBS, "jobs"),

    # ---- crypto info ----
    _s("CoinMarketCap", "https://coinmarketcap.com", "Crypto prices and market data (information only).", ["coinmarketcap", "price", "coin"] + _GEN_CRYPTO, "crypto"),

    # ---- shopping ----
    _s("Flipkart", "https://www.flipkart.com", "Shop and track Flipkart orders.", ["flipkart"] + _GEN_SHOP, "shopping"),

    # ---- streaming and video ----
    _s("YouTube", "https://www.youtube.com", "Official videos, channels, music and live streams.", ["youtube", "video", "videos", "song", "songs"] + _GEN_WATCH, "streaming"),
    _s("Prime Video", "https://www.primevideo.com", "Watch movies and series with Amazon Prime.", ["prime video"] + _GEN_WATCH, "streaming"),

    # ---- email and files ----
    _s("Gmail", "https://mail.google.com", "Open your mailbox directly instead of through a link.", ["gmail", "email", "mailbox", "inbox", "webmail", "password expired"], "email"),
    _s("Outlook", "https://outlook.live.com", "Open your Outlook mailbox directly.", ["outlook", "email", "mailbox", "inbox", "webmail"], "email"),
    _s("Google Drive", "https://drive.google.com", "Open shared files from inside your own Drive.", ["drive", "shared file", "document", "pdf", "spreadsheet", "docs"], "cloud"),
    _s("OneDrive", "https://onedrive.live.com", "Open shared files from inside your own OneDrive.", ["onedrive", "shared file", "document"], "cloud"),

    # ---- reference and research ----
    _s("Wikipedia", "https://www.wikipedia.org", "A good starting point for general facts and sources.", ["wikipedia", "wiki", "encyclopedia", "facts"], "reference"),
    _s("Google Scholar", "https://scholar.google.com", "Find research papers and citations.", ["scholar", "paper", "papers", "research", "journal", "thesis", "citation"], "research"),
    _s("arXiv", "https://arxiv.org", "Free research preprints.", ["arxiv", "preprint", "paper", "research"], "research"),
    _s("IEEE Xplore", "https://ieeexplore.ieee.org", "Papers, journals and standards from IEEE.", ["ieee", "paper", "journal", "conference", "standard"], "research"),
    _s("Stack Overflow", "https://stackoverflow.com", "Answers to programming questions.", ["stackoverflow", "stack overflow", "error", "bug", "code", "programming"], "dev"),

    # ---- travel ----
    _s("IRCTC", "https://www.irctc.co.in", "Official Indian Railways ticket booking.", ["irctc", "train", "ticket", "tickets", "railway", "pnr", "tatkal"], "travel"),
    _s("Google Flights", "https://www.google.com/travel/flights", "Compare flights, then book on the airline's own site.", ["flight", "flights", "airline", "airfare"], "travel"),
]

_PRIZE_WORDS = ("prize", "lottery", "winner", "reward", "gift", "claim")


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text))


def _hits(keywords, text: str, tokens: set[str]) -> list[str]:
    found = []
    for k in keywords:
        if " " in k or "-" in k or len(k) >= 5:
            if k in text:
                found.append(k)
        elif k in tokens:       # short words must match a whole word ("who" != "whole")
            found.append(k)
    return found


def _display(url: str) -> str:
    return re.sub(r"^https?://", "", url).rstrip("/")


def suggest(url: str, risk: int, finding_ids: set[str], brand: str | None, intent: str = ""):
    """Return {headline, reason, sites, tips} or None when the link isn't risky enough."""
    if risk < MIN_RISK:
        return None

    url_l = (url or "").lower()
    intent_l = (intent or "").strip().lower()[:200]
    url_tokens, intent_tokens = _tokens(url_l), _tokens(intent_l)

    scored = []
    for order, e in enumerate(DIRECTORY):
        score, tag = 0, None
        if brand and e["brand"] == brand:
            score, tag = 100, "The real site of the brand this link imitates"
        ih = _hits(e["keywords"], intent_l, intent_tokens)
        uh = _hits(e["keywords"], url_l, url_tokens)
        if ih:
            score += 30 * len(ih)
            tag = tag or f"Matches \u201c{ih[0]}\u201d in what you typed"
        if uh:
            score += 10 * len(uh)
            tag = tag or f"Matches \u201c{uh[0]}\u201d in the link"
        if "risky_file" in finding_ids and e["category"] == "software":
            score += 12
            tag = tag or "The link tried to make you download a file"
        if score >= 10:
            scored.append((-score, order, e, tag, bool(ih)))
    scored.sort(key=lambda t: (t[0], t[1]))
    top = scored[:MAX_SITES]
    if brand and top and top[0][2]["brand"] == brand:
        top = top[:1]       # the link imitates one specific brand: point only to the real one

    sites = [{"name": e["name"], "url": e["url"], "display": _display(e["url"]),
              "why": e["blurb"], "tag": tag} for _, _, e, tag, _ in top]

    if brand and top and top[0][2]["brand"] == brand:
        name = top[0][2]["name"]
        reason = (f"This link is pretending to be {name}. If you wanted the real {name}, "
                  "use the verified address below and type it yourself.")
    elif top and any(t[4] for t in top):
        reason = "Based on what you told us you were looking for, these verified sites can help."
    elif top:
        reason = "Based on words in the link, you may have been after one of these verified sites."
    elif intent_l:
        reason = ("We couldn't match what you typed to a verified site yet. "
                  "Try naming the service or organisation you wanted.")
    else:
        reason = ("We couldn't tell what you were looking for. Type it in the optional box "
                  "above and check again, and we'll suggest verified sites.")

    tips = [
        "Don't click links from messages. Type the official address yourself or use a saved bookmark.",
        "Search for the organisation's name and pick the result with its official domain, or use its official app.",
        "If it came from someone you know, ask them through a different channel whether they sent it.",
    ]
    if "shortener" in finding_ids:
        tips.insert(0, "This link is shortened, so the destination is hidden. Ask the sender for the full address.")
    if any(w in url_l or w in intent_l for w in _PRIZE_WORDS):
        tips.insert(0, "Unexpected prizes and rewards are almost always scams. Real contests never ask you to pay or log in to claim.")

    return {"headline": "Safer places to get what you need", "reason": reason,
            "sites": sites, "tips": tips[:4]}
