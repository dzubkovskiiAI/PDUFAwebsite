"""Open the page a result cites and check that it really supports the date.

Models can cite a page they never read. A source only counts toward trust when this check passes.
  ok           the page names the drug, mentions a PDUFA/action date, and shows the date itself
  weak         the page names the drug but the date or PDUFA wording is missing
  mismatch     the page loads but never mentions the drug (result is dropped)
  unreachable  the page could not be read: blocked, a PDF, or too little text (JavaScript-only sites)
"""
import re

import requests
from bs4 import BeautifulSoup

from . import config, model, store

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]
PDUFA_WORDS = re.compile(r"PDUFA|target action date|action date|goal date|decision date", re.I)


def date_patterns(when):
    p = model.parse_when(when)
    if not p:
        return []
    kind, start, _ = p
    mn, y = MONTHS[start.month - 1], start.year
    ab = mn[:3]
    if kind == "day":
        d = start.day
        return [rf"{mn}\s+{d}(?:st|nd|rd|th)?,?\s+{y}", rf"{ab}\.?\s+{d}(?:st|nd|rd|th)?,?\s+{y}",
                rf"{d}(?:st|nd|rd|th)?\s+{mn}\s+{y}", rf"{y}-{start.month:02d}-{d:02d}",
                rf"{start.month}/{d}/{y}", rf"{start.month:02d}/{d:02d}/{y}"]
    if kind == "month":
        return [rf"{mn}\s+{y}", rf"{ab}\.?\s+{y}", rf"{y}-{start.month:02d}"]
    q = (start.month - 1) // 3 + 1
    word = ["first", "second", "third", "fourth"][q - 1]
    return [rf"{word}\s+quarter\s+(?:of\s+)?{y}", rf"Q{q}\s*{y}", rf"{q}Q\s*{y}", rf"Q{q}\s*'?{str(y)[2:]}"]


def _get(url):
    h = config.host(url)
    ua = config.SEC_USER_AGENT if h.endswith("sec.gov") and config.SEC_USER_AGENT else "Mozilla/5.0 (compatible; pdufa-tracker)"
    return requests.get(url, headers={"User-Agent": ua}, timeout=25, allow_redirects=True)


def check(url, drug, when, getter=None):
    """Return (status, final_url). Redirects are followed, so grounding redirect links resolve."""
    try:
        r = (getter or _get)(url)
        if r.status_code >= 400 or "pdf" in r.headers.get("content-type", "").lower():
            return "unreachable", url
        text = BeautifulSoup(r.text, "html.parser").get_text(" ", strip=True)
    except Exception:
        return "unreachable", url
    final = r.url or url
    if len(text) < 1500:                       # likely a JavaScript shell, so we cannot judge it
        return "unreachable", final
    tokens = store.toks(drug)
    if tokens and not any(t in text.lower() for t in tokens):
        return "mismatch", final
    if PDUFA_WORDS.search(text) and any(re.search(p, text, re.I) for p in date_patterns(when)):
        return "ok", final
    return "weak", final
