"""SEC EDGAR full-text search over 8-K filings, then fetch only the PDUFA excerpts.

Note: the full-text search endpoint is not formally documented by the SEC. If its
JSON shape changes, parse_hit() is the one function to fix. SEC fair-access rules
apply: send a real User-Agent and stay under 10 requests per second.
"""
import re
import time

import requests
from bs4 import BeautifulSoup

from . import config

FTS_URL = "https://efts.sec.gov/LATEST/search-index"
KEY = re.compile(r"PDUFA|target action date|goal date|user fee goal", re.I)


def _get(url, params=None):
    if not config.SEC_USER_AGENT:
        raise RuntimeError("Set SEC_USER_AGENT to a descriptive name and email before calling SEC.")
    time.sleep(0.15)
    r = requests.get(url, params=params, timeout=30, headers={
        "User-Agent": config.SEC_USER_AGENT, "Accept-Encoding": "gzip, deflate"})
    r.raise_for_status()
    return r


def parse_hit(h):
    src = h["_source"]
    adsh, _, fname = h["_id"].partition(":")
    cik = str(int(src["ciks"][0]))
    name = re.sub(r"\s*\(.*$", "", src["display_names"][0]).strip()
    return {
        "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{adsh.replace('-', '')}/{fname}",
        "company": name, "published": src.get("file_date"), "form": src.get("form"),
    }


def search(query, start, end, forms="8-K,6-K", max_pages=3):
    hits = []
    for page in range(max_pages):
        data = _get(FTS_URL, {"q": query, "dateRange": "custom", "startdt": start,
                              "enddt": end, "forms": forms, "from": page * 100}).json()
        batch = data.get("hits", {}).get("hits", [])
        hits += [parse_hit(h) for h in batch]
        if len(batch) < 100:
            break
    return hits


def fetch_text(url):
    return BeautifulSoup(_get(url).text, "html.parser").get_text(" ", strip=True)


def snippets(text, width=500, limit=6):
    """Windows of text around PDUFA mentions, merged when they overlap."""
    spans = []
    for m in KEY.finditer(text):
        a, b = max(0, m.start() - width), min(len(text), m.end() + width)
        if spans and a <= spans[-1][1]:
            spans[-1][1] = b
        else:
            spans.append([a, b])
    return [text[a:b] for a, b in spans[:limit]]
