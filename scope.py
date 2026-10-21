"""The nine indications this tracker covers. Edit INDICATIONS to widen or narrow the scope.

Labels match the names used in the trials app, so rows can be joined on "label".
"""
import re

INDICATIONS = [
    {"label": "Alzheimer's Disease", "area": "neuro",
     "terms": [r"alzheimer"],
     "search": "Alzheimer's disease"},
    {"label": "Arthritis", "area": "imm",
     "terms": [r"arthritis", r"spondyloarthritis", r"ankylosing", r"\bgout\b"],
     "search": "arthritis (rheumatoid, psoriatic, juvenile idiopathic, axial spondyloarthritis, gout, osteoarthritis)"},
    {"label": "Breast Cancer", "area": "onc",
     "terms": [r"breast"],
     "search": "breast cancer"},
    {"label": "Colorectal Cancer", "area": "onc",
     "terms": [r"colorectal", r"colon cancer", r"colon carcinoma", r"rectal cancer", r"colon and rectal", r"\bcrc\b"],
     "search": "colorectal cancer (colon and rectal)"},
    {"label": "Melanoma", "area": "onc",
     "terms": [r"melanoma"],
     "search": "melanoma"},
    {"label": "Non-Small Cell Lung Cancer", "area": "onc",
     "terms": [r"non-?\s?small[- ]cell", r"nsclc", r"lung cancer"],
     "exclude": r"(?<!non-)(?<!non )small[- ]cell lung|\bsclc\b",     # small cell lung cancer is out of scope
     "search": "non-small cell lung cancer"},
    {"label": "Obesity", "area": "obe",
     "terms": [r"obesity", r"overweight", r"weight management", r"weight loss"],
     "search": "obesity and chronic weight management"},
    {"label": "Pancreatic Cancer", "area": "onc",
     "terms": [r"pancreatic cancer", r"pancreatic adenocarcinoma", r"pancreatic ductal", r"\bpdac\b", r"pancreatic neuroendocrine"],
     "search": "pancreatic cancer"},
    {"label": "Prostate Cancer", "area": "onc",
     "terms": [r"prostate"],
     "search": "prostate cancer"},
]

for _i in INDICATIONS:
    _i["_re"] = re.compile("|".join(_i["terms"]), re.I)
    _i["_ex"] = re.compile(_i["exclude"], re.I) if _i.get("exclude") else None


def classify(*texts):
    """Return the indication dict that matches the text, or None if out of scope."""
    t = " ".join(str(x or "") for x in texts)
    for i in INDICATIONS:
        if i["_re"].search(t) and not (i["_ex"] and i["_ex"].search(t)):
            return i
    return None


def mentions(text):
    """Cheap pre-filter for long documents: does any in-scope term appear at all?"""
    return any(i["_re"].search(text) for i in INDICATIONS)


def describe():
    return "; ".join(f"{i['label']} ({i['search']})" for i in INDICATIONS)


def meta():
    return [{"label": i["label"], "area": i["area"]} for i in INDICATIONS]
