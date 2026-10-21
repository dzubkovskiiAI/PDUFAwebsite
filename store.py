"""The canonical event store: matching, merging, history and trust levels."""
import json
import os
import re

from . import config, model

STOP = {"therapeutics", "pharmaceuticals", "pharmaceutical", "pharma", "inc", "corp",
        "corporation", "company", "bio", "biosciences", "biopharma", "oncology",
        "holdings", "limited", "ltd", "and", "with", "plus", "injection", "tablets",
        "stated"}


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def toks(s):
    return {t for t in norm(s).split() if len(t) >= 4 and t not in STOP}


GENERIC = {"cancer", "disease", "patients", "adults", "treatment", "after", "prior", "previously",
           "treated", "locally", "positive", "negative", "mutation", "mutated", "carcinoma",
           "tumor", "tumors", "syndrome", "first", "line", "therapy"}
EARLY = {"early", "adjuvant", "neoadjuvant", "perioperative", "resectable"}
LATE = {"advanced", "metastatic", "unresectable", "recurrent", "refractory", "relapsed"}


def _stage(t):
    e, l = bool(t & EARLY), bool(t & LATE)
    return "early" if e and not l else "late" if l and not e else "any"


def same_indication(a, b):
    """Loose match on two indication strings. Early-stage and late-stage never match."""
    ta, tb = toks(a), toks(b)
    if not ta or not tb:
        return True
    sa, sb = _stage(ta), _stage(tb)
    if "any" not in (sa, sb) and sa != sb:
        return False
    return bool((ta - GENERIC - EARLY - LATE) & (tb - GENERIC - EARLY - LATE))


def load(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False, sort_keys=True)


def find_match(events, c):
    ct, dtok = toks(c["company"]), toks(c["drug"])
    for e in events.values():
        ect = toks(e["company"])
        if ct and ect and not (ct & ect):
            continue
        if not (dtok & toks(e["drug"])):
            continue
        if not same_indication(c.get("indication", ""), e.get("indication", "")):
            continue
        return e
    return None


def refresh_review(e):
    """verified = two primary channels agree. primary = one. unverified = none."""
    hosts = {}
    for s in e["sources"]:
        if (s["type"] in config.PRIMARY_TYPES and s.get("date") == e["date"]
                and (s.get("checked") or "ok") == "ok"):
            hosts.setdefault(config.host(s["url"]), s)
    n = len(hosts)
    e["review"] = "verified" if n >= 2 else "primary" if n == 1 else "unverified"


def upsert(events, c, ts):
    """Merge one candidate. Returns (action, event)."""
    src = c["source"]
    e = find_match(events, c)
    if e is None:
        e = {
            "id": model.slug(c["company"], c["drug"], c.get("indication", "")),
            "drug": c["drug"], "company": c["company"], "area": c["area"],
            "condition": c["condition"], "indication": c.get("indication", ""),
            "date": c["date"], "status": "pending", "decided": None,
            "status_sources": [], "review": "unverified", "sources": [src],
            "date_source_published": src.get("published") or "",
            "history": [{"ts": ts, "field": "created", "new": c["date"], "source": src["url"]}],
            "conflicts": [], "first_seen": ts, "last_checked": ts,
        }
        events[e["id"]] = e
        refresh_review(e)
        return "new", e

    e["last_checked"] = ts
    action = "unchanged"
    if all(s["url"] != src["url"] for s in e["sources"]):
        e["sources"].append(src)
        action = "source_added"
    if c["date"] != e["date"]:
        newer = (src.get("published") or "") > (e.get("date_source_published") or "")
        if newer:
            e["history"].append({"ts": ts, "field": "date", "old": e["date"], "new": c["date"], "source": src["url"]})
            e["date"] = c["date"]
            e["date_source_published"] = src.get("published") or ""
            action = "updated"
        elif not any(x["date"] == c["date"] and x["source"] == src["url"] for x in e["conflicts"]):
            e["conflicts"].append({"date": c["date"], "source": src["url"]})
            action = "conflict"
    refresh_review(e)
    return action, e
