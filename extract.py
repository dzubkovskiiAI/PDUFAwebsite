"""Ask the model to read PDUFA excerpts from a filing and return structured dates."""
from . import config, llm, scope

SYS = f"""You read excerpts from an SEC filing or company announcement and extract FDA PDUFA target action dates.
Report a date only if the excerpt states it. Never infer or compute a date. If only a month or a quarter is stated, use that precision.
company is the drug's sponsor, meaning the company that submitted the application. It can differ from the filer when the filer is a royalty holder or partner.
Reply with ONLY a JSON array, with no prose and no code fences. Each object has keys: drug, company, indication, area, condition, date, evidence.
date is YYYY-MM-DD, YYYY-MM or YYYY-Q#. area is one of: {", ".join(config.AREAS)}.
condition is a short disease name such as NSCLC or Colorectal cancer. evidence is a paraphrase under 20 words, not a quotation.
Only report applications for these indications and skip every other disease: {scope.describe()}.
Return [] if the excerpts contain no in-scope PDUFA date."""


def extract(cl, hit, excerpts):
    body = "\n---\n".join(excerpts)
    text = llm.ask(cl, SYS, f"Filer: {hit['company']}\nFiled: {hit['published']}\nURL: {hit['url']}\n\nExcerpts:\n---\n{body}")
    arr = llm.parse_json(text, "[", "]")
    out = []
    for raw in arr if isinstance(arr, list) else []:
        if isinstance(raw, dict):
            raw["source_url"] = hit["url"]
            raw["source_name"] = f"SEC filing, {hit['company']} ({hit['published']})"
            raw["published"] = hit["published"]
            raw["checked"] = "ok"          # we fetched this filing and read it ourselves
            out.append(raw)
    return out
