"""Turn a raw model answer into a clean candidate, or reject it."""
import datetime as dt

from . import config, model, scope


def clean(raw, today, source_name=None, published=None):
    if not isinstance(raw, dict):
        return None
    drug = str(raw.get("drug", "")).strip()
    url = str(raw.get("source_url", "")).strip()
    if not drug or not url.startswith(("http://", "https://")):
        return None
    if config.is_aggregator(url):
        return None
    parsed = model.parse_when(raw.get("date"))
    if not parsed:
        return None
    _, _, end = parsed
    if end < today - dt.timedelta(days=30):      # long past: the outcome check owns those
        return None
    a, b = scope.classify(raw.get("indication")), scope.classify(raw.get("condition"))
    if a and b and a["label"] != b["label"]:         # the model contradicted itself: do not guess
        return None
    ind = a or b
    if ind is None:                                  # not one of the tracked indications
        return None
    when = raw["date"]
    return {
        "drug": drug,
        "company": str(raw.get("company") or "Not stated").strip(),
        "indication": str(raw.get("indication") or "").strip(),
        "area": ind["area"],
        "condition": ind["label"],
        "date": when,
        "source": {
            "url": url,
            "name": str(source_name or raw.get("source_name") or config.host(url)),
            "type": config.classify_source(url),
            "published": published or raw.get("published"),
            "date": when,
            "evidence": str(raw.get("evidence", ""))[:220],
            "checked": raw.get("checked"),
        },
    }
