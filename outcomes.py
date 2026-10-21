"""After a goal date passes, look for what the FDA actually did."""
import datetime as dt

from . import config, llm, model

SYS = """You find out what the FDA decided for one drug application. Use web search.
Accept only a company press release, SEC filing or FDA page that you retrieved. Never use catalyst calendars or trading sites.
Reply with ONLY a JSON object, with no prose and no code fences, with keys: status, decision_date, new_goal_date, source_url, source_name, evidence.
status is "approved", "crl" (complete response letter), "extended" (goal date moved), "pending" (no decision yet) or "unknown".
decision_date and new_goal_date use YYYY-MM-DD, YYYY-MM or YYYY-Q#, or null. evidence is a paraphrase under 20 words, not a quotation."""


def due(events, today, recheck_days=3):
    out = []
    for e in events.values():
        parsed = model.parse_when(e["date"])
        if e["status"] != "pending" or not parsed or parsed[2] >= today:
            continue
        last = e.get("outcome_checked")
        if last and (today - dt.date.fromisoformat(last[:10])).days < recheck_days:
            continue
        out.append(e)
    return out


def check(cl, e):
    prompt = (f"Drug: {e['drug']}. Company: {e['company']}. Indication: {e['indication']}. "
              f"The FDA goal date was {e['date']}. What happened?")
    obj = llm.parse_json(llm.ask(cl, SYS, prompt, web=True), "{", "}")
    return obj if isinstance(obj, dict) else None


def apply(e, res, ts):
    """Record an outcome. Only primary sources can change a status."""
    e["outcome_checked"] = ts
    if not res:
        return "no_answer"
    url = str(res.get("source_url") or "")
    if not url.startswith("http") or config.is_aggregator(url) or config.classify_source(url) == "secondary":
        return "no_primary_source"
    src = {"url": url, "name": str(res.get("source_name") or config.host(url)),
           "type": config.classify_source(url), "published": None,
           "date": None, "evidence": str(res.get("evidence", ""))[:220]}
    status = res.get("status")
    if status in ("approved", "crl"):
        e["status"], e["decided"] = status, res.get("decision_date")
        e["status_sources"].append(src)
        e["history"].append({"ts": ts, "field": "status", "old": "pending", "new": status, "source": url})
        return status
    new = res.get("new_goal_date")
    if status == "extended" and model.parse_when(new) and new != e["date"]:
        e["history"].append({"ts": ts, "field": "date", "old": e["date"], "new": new, "source": url})
        e["date"] = new
        e["sources"].append({**src, "date": new})
        return "extended"
    return "no_change"
