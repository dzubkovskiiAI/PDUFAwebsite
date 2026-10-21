"""Model-driven web search for company announcements that EDGAR will not catch."""
from . import config, llm, scope

PASSES = [
    "new drug or biologic applications (NDA or BLA) accepted for review",
    "supplemental applications (sNDA or sBLA) for a new indication, population, line of therapy or formulation",
]


def topics(only=None):
    """Two searches per tracked indication. `only` limits to one label, e.g. "Melanoma"."""
    out = []
    for ind in scope.INDICATIONS:
        if only and only.lower() not in ind["label"].lower():
            continue
        for p in PASSES:
            out.append({"label": ind["label"], "query": f"{ind['search']}: {p}"})
    return out


SYS = f"""You research FDA PDUFA target action dates for a pharma team. Use web search.
Report a date only if a company press release, SEC filing or FDA page that you retrieved states it.
If you land on a news or stock site that reprints a company announcement, search for the company's own announcement and cite that instead. If you cannot find it, cite what you found.
Never use catalyst calendars or trading sites. Never guess or compute dates: if the source gives only a month or a quarter, report that precision.
Reply with ONLY a JSON array, with no prose and no code fences, of at most 6 objects with keys: drug, company, indication, area, condition, date, source_url, source_name, evidence.
date is YYYY-MM-DD, YYYY-MM or YYYY-Q# (for example 2027-Q1). area is one of: {", ".join(config.AREAS)}.
evidence is a paraphrase under 20 words, not a quotation. Return [] if you find nothing."""


def discover(cl, query, today_iso, known):
    prompt = (f"Find FDA PDUFA target action dates on or after {today_iso} for: {query}. "
              f"Prefer announcements from the last 12 months. Skip drugs already tracked: {known}.")
    arr = llm.parse_json(llm.ask(cl, SYS, prompt, web=True, max_tokens=2000), "[", "]")
    return [x for x in arr if isinstance(x, dict)] if isinstance(arr, list) else []
