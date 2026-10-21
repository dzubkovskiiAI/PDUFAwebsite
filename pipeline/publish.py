"""Write the files the website serves: events.json, events.js and a calendar feed."""
import csv
import datetime as dt
import io
import json
import os
import shutil

from . import config, model, scope

CAL_OK = {"verified", "primary"}


def _ics(events, today):
    def esc(s):
        return str(s).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//PDUFA tracker//EN", "CALSCALE:GREGORIAN"]
    for e in events:
        p = model.parse_when(e["date"])
        if e["status"] != "pending" or e["review"] not in CAL_OK or not p or p[0] != "day" or p[1] < today:
            continue
        d = p[1]
        lines += ["BEGIN:VEVENT", f"UID:{e['id']}@pdufa-tracker", f"DTSTAMP:{today:%Y%m%d}T000000Z",
                  f"DTSTART;VALUE=DATE:{d:%Y%m%d}", f"DTEND;VALUE=DATE:{d + dt.timedelta(days=1):%Y%m%d}",
                  f"SUMMARY:{esc('PDUFA: ' + e['drug'] + ' (' + e['company'] + ')')}",
                  f"DESCRIPTION:{esc(e['condition'] + ': ' + e['indication'] + '. Source: ' + e['sources'][0]['url'])}",
                  "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


SCHEMA_VERSION = 1


def _by_indication(events, today, now):
    """One summary row per tracked indication, shaped like a row in the indication explorer."""
    rows = []
    for ind in scope.INDICATIONS:
        mine = [e for e in events if e["condition"] == ind["label"]]
        parsed = {e["id"]: model.parse_when(e["date"]) for e in mine}
        pending = [e for e in mine if e["status"] == "pending"]
        upcoming = sorted((e for e in pending if parsed[e["id"]][2] >= today),
                          key=lambda e: (parsed[e["id"]][1], parsed[e["id"]][0] != "day"))
        overdue = [e for e in pending if parsed[e["id"]][2] < today]

        def brief(e):
            prim = [x for x in e["sources"] if x["type"] in config.PRIMARY_TYPES]
            src = (prim or e["sources"])[0]
            return {"id": e["id"], "drug": e["drug"], "company": e["company"], "detail": e["indication"],
                    "date": e["date"], "precision": parsed[e["id"]][0], "status": e["status"],
                    "trust": e["review"], "source_url": src["url"], "source_type": src["type"]}

        rows.append({
            "label": ind["label"], "area": ind["area"],
            "upcoming": len(upcoming), "awaiting_outcome": len(overdue),
            "decided": len(mine) - len(pending),
            "next_decision": brief(upcoming[0]) if upcoming else None,
            "events": [brief(e) for e in sorted(mine, key=lambda e: e["date"])],
        })
    return {"schema_version": SCHEMA_VERSION, "generated_at": now, "indications": rows}


CSV_COLS = ["id", "indication", "drug", "company", "detail", "goal_date", "precision", "status",
            "decided", "trust", "source_url", "source_type", "last_checked"]


def _cell(v):
    v = "" if v is None else str(v)
    return "'" + v if v[:1] in ("=", "+", "-", "@") else v      # stop spreadsheet formula injection


def _csv(events):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(CSV_COLS)
    for e in events:
        p = model.parse_when(e["date"])
        prim = [s for s in e["sources"] if s["type"] in config.PRIMARY_TYPES]
        src = (prim or e["sources"])[0]
        w.writerow([_cell(x) for x in [e["id"], e["condition"], e["drug"], e["company"], e["indication"],
                                       e["date"], p[0] if p else "", e["status"], e.get("decided") or "",
                                       e["review"], src["url"], src["type"], (e.get("last_checked") or "")[:10]]])
    return buf.getvalue()


def publish(events, overrides, today, now, site_dir=None):
    site_dir = site_dir or config.SITE_DIR
    out = []
    for e in events.values():
        o = overrides.get(e["id"], {})
        if o.get("review") == "rejected":
            continue
        ind = scope.classify(e["condition"], e["indication"])
        if ind is None:                         # kept in the data file, hidden from the site
            continue
        pe = dict(e)
        pe["condition"], pe["area"] = ind["label"], ind["area"]
        if o.get("review") == "verified":
            pe["review"], pe["reviewed"] = "verified", True
        out.append(pe)
    out.sort(key=lambda e: (e["date"], e["drug"]))
    payload = {"meta": {"schema_version": SCHEMA_VERSION, "generated_at": now, "count": len(out),
                        "scope": scope.meta()}, "events": out}
    os.makedirs(os.path.join(site_dir, "data"), exist_ok=True)
    text = json.dumps(payload, indent=1, ensure_ascii=False)
    with open(os.path.join(site_dir, "data", "events.json"), "w", encoding="utf-8") as f:
        f.write(text)
    with open(os.path.join(site_dir, "data", "events.js"), "w", encoding="utf-8") as f:
        f.write("window.PDUFA_DATA = " + text + ";\n")
    with open(os.path.join(site_dir, "data", "by_indication.json"), "w", encoding="utf-8") as f:
        json.dump(_by_indication(out, today, now), f, indent=1, ensure_ascii=False)
    with open(os.path.join(site_dir, "data", "events.csv"), "w", encoding="utf-8", newline="") as f:
        f.write(_csv(out))
    with open(os.path.join(site_dir, "pdufa.ics"), "w", encoding="utf-8", newline="") as f:
        f.write(_ics(out, today))
    export = config.EXPORT_DIR
    if export and os.path.isdir(export):
        for rel in ("data/events.json", "data/by_indication.json", "data/events.csv", "pdufa.ics"):
            shutil.copy(os.path.join(site_dir, rel), os.path.join(export, os.path.basename(rel)))
    return payload
