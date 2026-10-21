"""Shared settings. Everything the pipeline treats as policy lives here."""
import os
import re
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
SITE_DIR = os.path.join(ROOT, "site")


def load_env(path=None):
    """Read KEY=VALUE lines from .env. Real environment variables always win."""
    path = path or os.path.join(ROOT, ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip().strip('"').strip("'")
            if v:
                os.environ.setdefault(k.strip(), v)


def pick_provider(env):
    """Gemini if a Gemini key is present, else Claude. PDUFA_PROVIDER overrides."""
    provider = (env.get("PDUFA_PROVIDER") or ("gemini" if (env.get("GEMINI_API_KEY") or env.get("GOOGLE_API_KEY")) else "anthropic")).lower()
    default_model = "gemini-2.5-flash" if provider == "gemini" else "claude-sonnet-5-5"
    return provider, env.get("PDUFA_MODEL") or default_model


load_env()
PROVIDER, MODEL = pick_provider(os.environ)
# Seconds to wait before each Gemini call, to stay under free-tier rate limits.
CALL_DELAY = float(os.environ.get("PDUFA_CALL_DELAY") or (4 if PROVIDER == "gemini" else 0))
# Optional: also copy the published files here (for example a Google Drive for Desktop folder).
EXPORT_DIR = os.environ.get("PDUFA_EXPORT_DIR", "")

# SEC requires a descriptive User-Agent with contact details, e.g. "Acme Pharma BI jane@acme.com"
SEC_USER_AGENT = os.environ.get("SEC_USER_AGENT", "")

AREAS = ["onc", "imm", "obe", "endo", "cardio", "neuro", "psych", "inf",
         "heme", "rare", "nephro", "oph", "diag", "other"]

# Catalyst calendars and trading sites. Never searched, never cited.
AGGREGATORS = [
    "pdufa.bio", "biopharmcatalyst.com", "marketbeat.com", "catalystalert.io",
    "assyro.com", "dansfera.com", "biopharmawatch.com", "midgardfinance.com",
    "fdatracker.com", "rttnews.com",
]

PRESS_WIRES = ["businesswire.com", "prnewswire.com", "globenewswire.com",
               "accessnewswire.com", "newsfilecorp.com"]

PRIMARY_TYPES = {"sec", "fda", "ema", "press_release"}


def host(url):
    try:
        return urlparse(url).hostname.lower().removeprefix("www.")
    except Exception:
        return ""


def _is(h, domain):
    return h == domain or h.endswith("." + domain)


def is_aggregator(url):
    h = host(url)
    return any(_is(h, d) for d in AGGREGATORS)


def classify_source(url):
    """sec / fda / ema / press_release are primary. Everything else is secondary."""
    h = host(url)
    if _is(h, "sec.gov"):
        return "sec"
    if _is(h, "fda.gov"):
        return "fda"
    if _is(h, "ema.europa.eu"):
        return "ema"
    if any(_is(h, w) for w in PRESS_WIRES):
        return "press_release"
    path = urlparse(url).path.lower()
    if re.match(r"^(investor|investors|ir)\.", h) or "/investor-relations" in path or "/investors/" in path:
        return "press_release"
    return "secondary"
