"""
analyzer.py - LinkLens URL risk engine.

Takes a URL string, runs a set of independent checks, and returns:
  * every problem found (with severity + plain-language explanation)
  * a risk percentage (0-100)
  * a verdict (safe / caution / danger) with advice
  * the exact character ranges of the URL each problem refers to (for highlighting)

IMPORTANT: this module never downloads the page. The optional "live" checks only
do a DNS lookup, a TLS handshake (to read the certificate) and, if the
`python-whois` package is installed, a WHOIS lookup.

Each check is a small function: ParsedURL -> Finding | None. To add a new check,
write the function and add it to the CHECKS list near the bottom.
"""
from __future__ import annotations

import datetime as dt
import ipaddress
import math
import re
import socket
import ssl
import time
from collections import Counter
from dataclasses import dataclass, field
from urllib.parse import unquote, urlsplit

from suggestions import suggest

try:  # optional dependency: pip install python-whois
    import whois  # type: ignore
except ImportError:  # pragma: no cover
    whois = None

LIVE_TIMEOUT = 4  # seconds, per network operation
MAX_URL_LENGTH = 2048

# --------------------------------------------------------------------------- #
# Reference data (prototype-sized - replace with proper feeds later)
# --------------------------------------------------------------------------- #
SHORTENERS = {
    "bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "is.gd", "buff.ly",
    "rebrand.ly", "cutt.ly", "shorturl.at", "tiny.cc", "rb.gy", "lnkd.in",
    "s.id", "t.ly", "bl.ink",
}

SUSPICIOUS_TLDS = {
    "zip", "mov", "tk", "ml", "ga", "cf", "gq", "xyz", "top", "click", "country",
    "kim", "work", "support", "rest", "cam", "icu", "buzz", "loan", "monster",
    "sbs", "cyou", "quest",
}

MULTI_PART_SUFFIXES = {
    "co.uk", "org.uk", "ac.uk", "gov.uk", "com.au", "net.au", "org.au", "co.in",
    "net.in", "org.in", "ac.in", "gov.in", "edu.in", "co.jp", "com.br", "com.cn",
    "co.za", "com.sg", "com.mx", "co.nz",
}

# brand label -> set of domains that genuinely belong to it
BRANDS = {
    "paypal": {"paypal.com", "paypal.me"},
    "google": {"google.com", "google.co.in", "gstatic.com", "youtube.com"},
    "microsoft": {"microsoft.com", "live.com", "office.com", "microsoftonline.com", "outlook.com"},
    "apple": {"apple.com", "icloud.com"},
    "amazon": {"amazon.com", "amazon.in", "amazon.co.uk", "amazon.de"},
    "facebook": {"facebook.com", "fb.com"},
    "instagram": {"instagram.com"},
    "whatsapp": {"whatsapp.com", "whatsapp.net"},
    "netflix": {"netflix.com"},
    "linkedin": {"linkedin.com"},
    "github": {"github.com", "github.io", "githubusercontent.com"},
    "dropbox": {"dropbox.com"},
    "paytm": {"paytm.com"},
    "phonepe": {"phonepe.com"},
    "hdfcbank": {"hdfcbank.com"},
    "icicibank": {"icicibank.com"},
    "sbi": {"sbi.co.in", "onlinesbi.sbi", "sbi.bank.in"},
    "binance": {"binance.com"},
    "coinbase": {"coinbase.com"},
    "metamask": {"metamask.io"},
    "steam": {"steampowered.com", "steamcommunity.com"},
    "discord": {"discord.com", "discord.gg"},
    "dhl": {"dhl.com"},
    "fedex": {"fedex.com"},
}

SENSITIVE_WORDS = [
    "login", "signin", "sign-in", "verify", "verification", "account", "update",
    "secure", "security", "banking", "confirm", "password", "wallet", "billing",
    "suspended", "unlock", "invoice", "payment", "refund", "prize", "gift",
    "reward", "claim", "recover", "validate", "authenticate",
]

RISKY_EXTENSIONS = {
    "exe", "scr", "msi", "bat", "cmd", "com", "vbs", "js", "jar", "ps1", "apk",
    "dmg", "iso", "docm", "xlsm", "pptm", "lnk", "hta",
}

NON_WEB_SCHEMES = {
    "javascript", "data", "vbscript", "file", "blob", "about",
    "mailto", "tel", "sms", "ftp",
}
DANGEROUS_SCHEMES = {"javascript", "data", "vbscript", "file", "blob"}

# --------------------------------------------------------------------------- #
# Data classes
# --------------------------------------------------------------------------- #
@dataclass
class Finding:
    id: str
    title: str
    detail: str
    severity: str   # "high" | "medium" | "low"
    weight: float   # 0..1, how strongly this finding suggests a threat
    part: str       # which part of the URL to highlight (default for `spans`)
    spans: list | None = None   # [(start, end)] character ranges inside ParsedURL.url
    meta: dict | None = None    # extra facts for later stages, e.g. {"brand": "paypal"}


@dataclass
class ParsedURL:
    raw: str
    url: str
    scheme: str
    userinfo: str
    host: str
    port: int | None
    path: str
    query: str
    fragment: str
    subdomain: str
    domain: str     # registrable label, e.g. "paypal"
    suffix: str     # e.g. "com" or "co.uk"
    is_ip: bool
    obfuscated_ip: bool
    assumed_scheme: bool
    spans: dict = field(default_factory=dict)   # part name -> (start, end) in url

    @property
    def registered(self) -> str:
        return f"{self.domain}.{self.suffix}" if self.suffix else self.domain


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
def _split_host(host: str) -> tuple[str, str, str]:
    labels = host.split(".")
    if len(labels) < 2:
        return "", host, ""
    last_two = ".".join(labels[-2:])
    if last_two in MULTI_PART_SUFFIXES and len(labels) >= 3:
        return ".".join(labels[:-3]), labels[-3], last_two
    return ".".join(labels[:-2]), labels[-2], labels[-1]


def parse(raw: str) -> ParsedURL:
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("Enter a URL to check.")
    if len(raw) > MAX_URL_LENGTH:
        raise ValueError(f"That URL is too long (limit is {MAX_URL_LENGTH} characters).")
    if re.search(r"\s", raw):
        raise ValueError("URLs can't contain spaces. Check for a copy-paste error.")

    assumed = False
    url = raw
    if "://" not in raw:
        m = re.match(r"^([a-zA-Z][a-zA-Z0-9+.\-]*):", raw)
        if m and m.group(1).lower() in NON_WEB_SCHEMES:
            return ParsedURL(raw, raw, m.group(1).lower(), "", "", None, "", "", "",
                             "", "", "", False, False, False)
        url = "https://" + raw
        assumed = True

    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise ValueError("That doesn't look like a valid URL.")

    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise ValueError("That URL has no website address in it.")

    userinfo, _, _ = parts.netloc.rpartition("@")

    is_ip = False
    try:
        ipaddress.ip_address(host)
        is_ip = True
    except ValueError:
        pass
    obfuscated = (not is_ip) and bool(
        re.fullmatch(r"\d+", host)
        or re.fullmatch(r"0x[0-9a-f]+", host)
        or re.fullmatch(r"(0x[0-9a-f]+|\d+)(\.(0x[0-9a-f]+|\d+)){1,3}", host)
    )

    if is_ip or obfuscated:
        sub, domain, suffix = "", host, ""
    else:
        sub, domain, suffix = _split_host(host)

    # Character offsets of each part inside `url`, used to highlight problems.
    spans: dict[str, tuple[int, int]] = {}
    scheme_end = url.find("://")
    auth_start = scheme_end + 3
    spans["scheme"] = (0, scheme_end)
    stop = re.search(r"[/?#]", url[auth_start:])
    auth_end = auth_start + (stop.start() if stop else len(url) - auth_start)
    authority = url[auth_start:auth_end]
    at = authority.rfind("@")
    if at >= 0:
        spans["userinfo"] = (auth_start, auth_start + at + 1)
    host_start = auth_start + at + 1
    hostport = authority[at + 1:]
    pm = re.search(r":(\d*)$", hostport)
    host_len = pm.start() if pm else len(hostport)
    if pm and pm.group(1):
        spans["port"] = (host_start + pm.start(), host_start + len(hostport))
    spans["host"] = (host_start, host_start + len(hostport[:host_len].rstrip(".")))
    if not (is_ip or obfuscated):
        pos = host_start
        if sub:
            spans["subdomain"] = (pos, pos + len(sub))
            pos += len(sub) + 1
        spans["domain"] = (pos, pos + len(domain))
        if suffix:
            spans["suffix"] = (pos + len(domain) + 1, pos + len(domain) + 1 + len(suffix))
    if parts.path:
        spans["path"] = (auth_end, auth_end + len(parts.path))
    q_at = auth_end + len(parts.path)
    if parts.query and url[q_at:q_at + 1] == "?":
        spans["query"] = (q_at + 1, q_at + 1 + len(parts.query))
    if parts.fragment and url.find("#", auth_end) >= 0:
        spans["fragment"] = (url.find("#", auth_end) + 1, len(url))

    return ParsedURL(
        raw=raw, url=url, scheme=parts.scheme.lower(), userinfo=userinfo, host=host,
        port=port, path=parts.path, query=parts.query, fragment=parts.fragment,
        subdomain=sub, domain=domain, suffix=suffix, is_ip=is_ip,
        obfuscated_ip=obfuscated, assumed_scheme=assumed, spans=spans,
    )


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _shannon(s: str) -> float:
    if not s:
        return 0.0
    n = len(s)
    return -sum(c / n * math.log2(c / n) for c in Counter(s).values())


def _levenshtein(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


_LEET = str.maketrans({"0": "o", "1": "l", "3": "e", "4": "a", "5": "s", "7": "t", "$": "s", "@": "a"})


def _unleet(s: str) -> str:
    return s.translate(_LEET).replace("rn", "m").replace("vv", "w")


def _host_find(p: ParsedURL, needle: str):
    h0, _ = p.spans.get("host", (0, 0))
    i = p.host.find(needle)
    return [(h0 + i, h0 + i + len(needle))] if i >= 0 else None


def _regex_spans(p: ParsedURL, pattern: str, start_key: str = "host"):
    start = p.spans.get(start_key, (0, 0))[0]
    return [(start + m.start(), start + m.end())
            for m in re.finditer(pattern, p.url[start:], re.I) if m.end() > m.start()]


# --------------------------------------------------------------------------- #
# Checks: ParsedURL -> Finding | None
# --------------------------------------------------------------------------- #
def check_https(p: ParsedURL):
    if p.scheme == "http":
        return Finding(
            "no_https", "Connection is not encrypted",
            "The link starts with http://, so anything typed on the page (passwords, card "
            "numbers) can be read or changed in transit. Real login and payment pages use https://.",
            "medium", 0.20, "scheme")


def check_credentials(p: ParsedURL):
    if p.userinfo:
        return Finding(
            "userinfo", "Link hides its real destination behind an \"@\"",
            f"Everything before the \"@\" ({p.userinfo}) is ignored by the browser. This trick "
            f"makes a link look like it goes to one site while actually opening {p.host}.",
            "high", 0.40, "userinfo")


def check_ip_host(p: ParsedURL):
    if p.obfuscated_ip:
        return Finding(
            "obfuscated_ip", "Website address is a disguised IP number",
            "The address is written as a raw number (decimal, hex or octal) instead of a name. "
            "This is only done to hide where a link really goes.",
            "high", 0.50, "host")
    if p.is_ip:
        return Finding(
            "ip_host", "Uses a raw IP address instead of a website name",
            "Legitimate services almost always use a domain name. Links that point straight at "
            "an IP address are common in phishing and malware delivery.",
            "high", 0.35, "host")


def check_punycode(p: ParsedURL):
    if p.is_ip:
        return None
    if any(ord(c) > 127 for c in p.host) or "xn--" in p.host:
        return Finding(
            "idn", "Domain uses look-alike (international) characters",
            "Characters from other alphabets can look identical to Latin letters (for example a "
            "Cyrillic \"a\"), letting attackers imitate a trusted site. This is called a homograph attack.",
            "medium", 0.30, "host")


def check_shortener(p: ParsedURL):
    if p.registered in SHORTENERS or p.host in SHORTENERS:
        return Finding(
            "shortener", "Link shortener hides the real destination",
            f"{p.registered} redirects to another site, so you can't see where this link ends up "
            "before you click.",
            "medium", 0.25, "domain")


def check_tld(p: ParsedURL):
    tld = p.suffix.split(".")[-1] if p.suffix else ""
    if tld in SUSPICIOUS_TLDS:
        extra = (" .zip and .mov are also file extensions, which makes links easy to mistake "
                 "for downloads.") if tld in {"zip", "mov"} else ""
        return Finding(
            "tld", f"Uses a high-abuse domain ending (.{tld})",
            f"The .{tld} ending is cheap or free to register and shows up disproportionately in "
            f"spam and phishing campaigns.{extra}",
            "medium", 0.20, "suffix")


def check_brand(p: ParsedURL):
    if p.is_ip or p.obfuscated_ip or not p.suffix:
        return None
    tokens = [t for t in re.split(r"[.\-_]", p.host) if t]
    squashed = re.sub(r"[^a-z0-9]", "", p.host)
    for brand, real in BRANDS.items():
        if p.registered in real or any(p.host.endswith("." + r) for r in real):
            continue  # this really is the brand's own domain
        # 1. brand name used on a domain the brand doesn't own
        if brand in tokens or (len(brand) >= 5 and brand in squashed):
            part = "domain" if brand in p.domain else "subdomain"
            return Finding(
                "brand_impersonation", f"Pretends to be {brand.title()}",
                f"The address contains \"{brand}\" but the site is run from {p.registered}, "
                f"not from {brand.title()}'s real domain ({sorted(real)[0]}). This is the classic "
                "phishing pattern.",
                "high", 0.50, part, spans=_host_find(p, brand), meta={"brand": brand})
        # 2. look-alike spelling (paypa1, gooogle, micros0ft ...)
        if len(p.domain) >= 4:
            for cand in [p.domain] + p.domain.split("-"):
                if cand == brand or len(cand) < 4:
                    continue
                if len(brand) >= 5 and _unleet(cand) == brand:
                    close = True
                elif len(brand) >= 6 and _levenshtein(cand, brand) == 1:
                    close = True
                else:
                    close = False
                if close:
                    return Finding(
                        "typosquat", f"Look-alike spelling of {brand.title()}",
                        f"\"{cand}\" is one character away from \"{brand}\". Attackers register "
                        "near-identical names hoping you won't notice the difference.",
                        "high", 0.45, "domain",
                        spans=[(p.spans["domain"][0] + p.domain.find(cand),
                                p.spans["domain"][0] + p.domain.find(cand) + len(cand))],
                        meta={"brand": brand})
    return None


def check_subdomains(p: ParsedURL):
    n = len(p.subdomain.split(".")) if p.subdomain else 0
    if n >= 3:
        return Finding(
            "many_subdomains", "Unusually long chain of subdomains",
            f"The address has {n} subdomain levels ({p.subdomain}). Attackers pile on subdomains "
            "so a trusted-looking name appears first while the real domain is hidden at the end.",
            "low", 0.12, "subdomain")


def check_hyphens(p: ParsedURL):
    n = p.domain.removeprefix("xn--").count("-")
    if n >= 2 and not p.is_ip:
        return Finding(
            "hyphens", "Domain name is stuffed with hyphens",
            f"\"{p.domain}\" contains {n} hyphens. Phishing domains often chain words together "
            "(e.g. bank-secure-login) to look official.",
            "low", 0.12 if n >= 3 else 0.08, "domain")


def check_random_domain(p: ParsedURL):
    if p.is_ip or p.obfuscated_ip:
        return None
    label = p.domain
    letters = sum(c.isalpha() for c in label)
    digits = sum(c.isdigit() for c in label)
    if len(label) >= 10 and letters and digits / len(label) >= 0.3 and _shannon(label) >= 3.2:
        return Finding(
            "random_domain", "Domain name looks randomly generated",
            f"\"{label}\" is a jumble of letters and digits, typical of throw-away domains made "
            "by malware or bulk phishing kits.",
            "medium", 0.20, "domain")


def check_port(p: ParsedURL):
    if p.port not in (None, 80, 443):
        return Finding(
            "port", f"Uses an unusual port ({p.port})",
            "Normal websites use the standard web ports. Non-standard ports are common for "
            "temporary phishing pages and command-and-control servers.",
            "medium", 0.15, "port")


def _long_spans(p: ParsedURL):
    found = [p.spans[k] for k in ("path", "query") if k in p.spans]
    return found or None


def check_length(p: ParsedURL):
    n = len(p.url)
    if n > 200:
        return Finding("long_url", "Extremely long URL",
                       f"The link is {n} characters long. Very long links are often used to bury "
                       "the suspicious part where you won't see it.", "medium", 0.15, "path", spans=_long_spans(p))
    if n > 100:
        return Finding("long_url", "Unusually long URL",
                       f"The link is {n} characters long, which is longer than most legitimate links.",
                       "low", 0.08, "path", spans=_long_spans(p))


def _keyword_spans(p: ParsedURL, hits):
    pattern = "|".join(re.escape(h) for h in sorted(hits, key=len, reverse=True))
    return _regex_spans(p, pattern) or None


def check_keywords(p: ParsedURL):
    haystack = f"{p.host}{p.path}?{p.query}".lower()
    hits = [w for w in SENSITIVE_WORDS if w in haystack]
    if len(hits) >= 2:
        return Finding(
            "keywords", "Contains pressure / credential words",
            f"The link includes {', '.join(repr(h) for h in hits[:6])}. Phishing links lean on "
            "words that make you log in, verify or act quickly.",
            "medium", min(0.08 * len(hits), 0.24), "path", spans=_keyword_spans(p, hits))
    if len(hits) == 1:
        return Finding(
            "keywords", "Contains a credential-related word",
            f"The link includes '{hits[0]}'. On its own this is common and harmless, but it "
            "adds a little weight when combined with other warning signs.",
            "low", 0.05, "path", spans=_keyword_spans(p, hits))


def check_file_extension(p: ParsedURL):
    last = p.path.rsplit("/", 1)[-1]
    if "." in last:
        ext = last.rsplit(".", 1)[-1].lower()
        if ext in RISKY_EXTENSIONS:
            return Finding(
                "risky_file", f"Link points to a downloadable .{ext} file",
                f"Opening this link would download \"{last}\". Executable and macro-enabled files "
                "are the most common way malware reaches a device.",
                "high", 0.40, "path",
                spans=[(p.spans["path"][0] + p.path.rfind(last),
                        p.spans["path"][0] + p.path.rfind(last) + len(last))])


def check_redirect_param(p: ParsedURL):
    base = p.spans.get("query", (0, 0))[0]
    offset = 0
    for pair in p.query.split("&"):
        key, sep, value = pair.partition("=")
        if sep and re.match(r"^(https?:)?//", unquote(value).strip(), re.I):
            return Finding(
                "redirect_param", "Contains another link inside it",
                f"The parameter \"{key}\" holds a full web address. Attackers abuse this to bounce "
                "you through a trusted site and on to a malicious one.",
                "medium", 0.18, "query", spans=[(base + offset, base + offset + len(pair))])
        offset += len(pair) + 1


def check_encoding(p: ParsedURL):
    rest = f"{p.host}{p.path}?{p.query}"
    encoded = len(re.findall(r"%[0-9a-fA-F]{2}", rest))
    if "%25" in rest or "%00" in rest or "%" in p.host:
        return Finding(
            "double_encoding", "Contains suspicious character encoding",
            "Double-encoded or null characters are used to slip past filters and confuse "
            "security software.", "medium", 0.20, "path",
            spans=(_regex_spans(p, r"%25|%00") + ([p.spans["host"]] if "%" in p.host else [])) or None)
    if encoded >= 6:
        return Finding(
            "heavy_encoding", "Heavily encoded URL",
            f"The link has {encoded} percent-encoded characters, which can disguise what it really says.",
            "low", 0.08, "path", spans=_regex_spans(p, r"%[0-9a-f]{2}") or None)


def check_double_slash(p: ParsedURL):
    if "//" in p.path:
        return Finding(
            "double_slash", "Contains \"//\" inside the path",
            "A doubled slash after the domain is unusual and sometimes used in redirect tricks.",
            "low", 0.06, "path",
            spans=[(p.spans["path"][0] + m.start(), p.spans["path"][0] + m.end())
                   for m in re.finditer("//", p.path)])


# (id, label shown when the check passes, function)
CHECKS = [
    ("https", "Uses an encrypted (https) connection", check_https),
    ("userinfo", "No hidden \"@\" redirect trick", check_credentials),
    ("ip", "Uses a proper domain name, not an IP number", check_ip_host),
    ("idn", "No look-alike international characters", check_punycode),
    ("shortener", "Not a link shortener", check_shortener),
    ("tld", "Domain ending is not on the high-abuse list", check_tld),
    ("brand", "Doesn't imitate a well-known brand", check_brand),
    ("subdomains", "Normal number of subdomains", check_subdomains),
    ("hyphens", "Domain name isn't hyphen-stuffed", check_hyphens),
    ("random", "Domain name looks human-chosen", check_random_domain),
    ("port", "Uses a standard port", check_port),
    ("length", "URL length is normal", check_length),
    ("keywords", "No pressure or credential keywords", check_keywords),
    ("file", "Doesn't point at a risky file download", check_file_extension),
    ("redirect", "No link hidden inside the link", check_redirect_param),
    ("encoding", "No suspicious character encoding", check_encoding),
    ("slash", "Path structure looks normal", check_double_slash),
]


# --------------------------------------------------------------------------- #
# Live checks (optional, need network). Never fetches page content.
# --------------------------------------------------------------------------- #
def _is_public(ip: str) -> bool:
    a = ipaddress.ip_address(ip)
    return not (a.is_private or a.is_loopback or a.is_link_local or a.is_reserved
                or a.is_multicast or a.is_unspecified)


def _domain_age_days(domain: str):
    if whois is None:
        return None
    try:
        created = whois.whois(domain).creation_date
        if isinstance(created, list):
            created = min(created)
        if not created:
            return None
        if created.tzinfo:
            created = created.astimezone(dt.timezone.utc).replace(tzinfo=None)
        return (dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - created).days
    except Exception:
        return None


def live_checks(p: ParsedURL):
    """Returns (findings, passed_labels, notes, ran)."""
    findings, passed, notes = [], [], []
    port = p.port or (80 if p.scheme == "http" else 443)

    # Make sure *we* have internet, otherwise "doesn't resolve" would be a false alarm.
    try:
        socket.getaddrinfo("example.com", 443)
    except OSError:
        return [], [], ["Live checks skipped: the server has no internet access."], False

    # 1. DNS
    try:
        infos = socket.getaddrinfo(p.host, port, proto=socket.IPPROTO_TCP)
        ips = sorted({i[4][0] for i in infos})
    except socket.gaierror:
        findings.append(Finding(
            "no_dns", "Domain doesn't exist (or no longer resolves)",
            f"{p.host} has no DNS record. It may be mistyped, taken down, or a throw-away domain.",
            "medium", 0.20, "host"))
        return findings, passed, notes, True
    passed.append("Domain resolves in DNS")

    public_ips = [ip for ip in ips if _is_public(ip)]
    if not public_ips:
        findings.append(Finding(
            "private_ip", "Points to a private / internal address",
            f"{p.host} resolves to {ips[0]}, which is not reachable from the public internet. "
            "Links like this can be used to attack devices on your own network.",
            "medium", 0.25, "host"))
        notes.append("TLS check skipped: address is not public.")
        return findings, passed, notes, True

    # 2. TLS certificate (connect to the validated IP, not the hostname, to avoid DNS rebinding)
    if p.scheme == "https":
        try:
            ctx = ssl.create_default_context()
            with socket.create_connection((public_ips[0], port), timeout=LIVE_TIMEOUT) as sock:
                with ctx.wrap_socket(sock, server_hostname=p.host) as tls:
                    cert = tls.getpeercert()
            passed.append("TLS certificate is valid and matches the domain")
            issued = (time.time() - ssl.cert_time_to_seconds(cert["notBefore"])) / 86400
            expires = (ssl.cert_time_to_seconds(cert["notAfter"]) - time.time()) / 86400
            if issued < 7:
                findings.append(Finding(
                    "new_cert", "Security certificate was issued very recently",
                    f"The certificate is only {int(issued)} day(s) old. Brand-new certificates are "
                    "common on freshly created phishing sites (but also on legitimate renewals).",
                    "low", 0.10, "host"))
            if expires < 7:
                findings.append(Finding(
                    "expiring_cert", "Security certificate is about to expire",
                    f"The certificate expires in {max(int(expires), 0)} day(s).",
                    "low", 0.05, "host"))
        except ssl.SSLCertVerificationError as e:
            findings.append(Finding(
                "bad_cert", "Security certificate is invalid",
                f"The browser would refuse this site's certificate: {e.verify_message}. "
                "Never enter personal details on a page with a certificate warning.",
                "high", 0.40, "host"))
        except (ssl.SSLError, OSError) as e:
            notes.append(f"Couldn't complete a TLS handshake ({type(e).__name__}).")

    # 3. Domain age (optional dependency)
    if not p.is_ip and p.suffix:
        age = _domain_age_days(p.registered)
        if age is None:
            notes.append("Domain age not checked (install python-whois to enable).")
        elif age < 30:
            findings.append(Finding(
                "new_domain", "Domain was registered very recently",
                f"{p.registered} is only {age} day(s) old. Most phishing domains are used within "
                "days of being registered.", "high", 0.35, "domain"))
        elif age < 180:
            findings.append(Finding(
                "young_domain", "Domain is less than 6 months old",
                f"{p.registered} was registered {age} days ago. Newer domains have no track record.",
                "low", 0.12, "domain"))
        else:
            passed.append("Domain has been registered for a while")

    return findings, passed, notes, True


# --------------------------------------------------------------------------- #
# Scoring + packaging
# --------------------------------------------------------------------------- #
def _combine(findings: list[Finding]) -> int:
    """Noisy-OR: independent warning signs compound but never exceed 100%."""
    survive = 1.0
    for f in findings:
        survive *= 1.0 - f.weight
    return int(round(min(max((1.0 - survive) * 100, 3), 99)))


def _verdict(risk: int, findings: list[Finding]):
    if risk >= 55:
        return "danger", "Do not use this link", (
            "Multiple strong warning signs suggest this link is built to steal information or "
            "install malware. Don't open it, don't enter any details, and don't forward it. If it "
            "came from someone you know, ask them through a different channel whether they sent it.")
    if risk >= 25:
        return "caution", "Be careful with this link", (
            "Some warning signs showed up. Avoid entering passwords or payment details unless you "
            "can reach the same site by typing its official address yourself.")
    return "safe", "No major warning signs", (
        "Nothing in this link looks dangerous. No check is perfect, though: stay alert if the page "
        "asks for passwords or payments you weren't expecting.")


def analyze(raw_url: str, live: bool = True, intent: str = "") -> dict:
    p = parse(raw_url)
    findings: list[Finding] = []
    passed: list[str] = []
    notes: list[str] = []
    ran_live = False

    if p.scheme not in ("http", "https"):
        dangerous = p.scheme in DANGEROUS_SCHEMES
        findings.append(Finding(
            "non_web", "Not a normal website link",
            f"This uses the \"{p.scheme}:\" scheme, which "
            + ("can run code or load content directly in your browser without visiting a website."
               if dangerous else "opens an app or protocol instead of a website."),
            "high" if dangerous else "medium", 0.95 if dangerous else 0.30, "scheme",
            spans=[(0, len(p.url))]))
    else:
        for _id, label, fn in CHECKS:
            result = fn(p)
            if result:
                findings.append(result)
            else:
                passed.append(label)
        if live:
            lf, lp, notes, ran_live = live_checks(p)
            findings += lf
            passed += lp

    for f in findings:
        if f.spans is None:
            span = p.spans.get(f.part)
            f.spans = [span] if span and span[1] > span[0] else []

    risk = _combine(findings)
    level, headline, advice = _verdict(risk, findings)
    alternatives = suggest(
        url=p.url, risk=risk, finding_ids={f.id for f in findings},
        brand=next((f.meta["brand"] for f in findings if f.meta), None), intent=intent)
    order = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda f: (order[f.severity], -f.weight))

    if p.assumed_scheme:
        notes.insert(0, "No http:// or https:// was given, so https:// was assumed.")

    return {
        "url": p.url,
        "risk": risk,
        "level": level,
        "headline": headline,
        "advice": advice,
        "findings": [
            {"id": f.id, "title": f.title, "detail": f.detail, "severity": f.severity,
             "spans": [list(sp) for sp in f.spans]}
            for f in findings],
        "passed": passed,
        "alternatives": alternatives,
        "notes": notes,
        "live": {"requested": bool(live), "ran": ran_live},
    }
