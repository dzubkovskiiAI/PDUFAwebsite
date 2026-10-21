"""Command line: python -m pipeline <command>

  check     test the API key, model name and web search
  edgar     scan recent 8-Ks for PDUFA dates
  web       model-driven web search by topic
  outcomes  look up decisions for goal dates that have passed
  publish   write site/data and the calendar feed
  all       edgar, web, outcomes, then publish
  approve ID / reject ID   record a human review decision
"""
import argparse
import datetime as dt
import os

from . import cite, config, edgar, extract, llm, outcomes, publish as pub, scope, store, validate, web_discovery

EVENTS = os.path.join(config.DATA_DIR, "events.json")
STATE = os.path.join(config.DATA_DIR, "state.json")
OVERRIDES = os.path.join(config.DATA_DIR, "overrides.json")


def _now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cmd_edgar(args, events, cl, today):
    state = store.load(STATE)
    seen = set(state.get("edgar_seen", []))
    start = (today - dt.timedelta(days=args.days)).isoformat()
    hits = {}
    for q in ('"PDUFA"', '"target action date"'):
        for h in edgar.search(q, start, today.isoformat()):
            hits.setdefault(h["url"], h)
    todo = [h for u, h in hits.items() if u not in seen][:args.max_docs]
    print(f"EDGAR: {len(hits)} filings found, {len(todo)} new to read")
    for h in todo:
        try:
            text = edgar.fetch_text(h["url"])
            sn = edgar.snippets(text) if scope.mentions(text) else []     # skip filings about other diseases
            raws = extract.extract(cl, h, sn) if sn else []
        except Exception as ex:                      # one bad filing must not stop the run
            print(f"  skipped {h['url']}: {ex}")
            continue
        seen.add(h["url"])
        for raw in raws:
            c = validate.clean(raw, today, raw.get("source_name"), raw.get("published"))
            if c:
                action, e = store.upsert(events, c, _now())
                print(f"  {action}: {e['drug']} ({e['company']}) {e['date']}")
    state["edgar_seen"] = sorted(seen)
    store.save(STATE, state)


def cmd_web(args, events, cl, today):
    topics = web_discovery.topics(args.indication)
    if not topics:
        print(f"No tracked indication matches '{args.indication}'")
    for t in topics:
        known = "; ".join(e["drug"] for e in events.values())
        print(f"Web: {t['label']} / {t['query'].split(': ')[1][:50]}")
        try:
            found = web_discovery.discover(cl, t["query"], today.isoformat(), known)
        except Exception as ex:
            print(f"  skipped topic: {ex}")
            continue
        for raw in found:
            c = validate.clean(raw, today)
            if not c:
                continue
            status, final = cite.check(c["source"]["url"], c["drug"], c["date"])
            if status == "mismatch":
                print(f"  dropped: the cited page does not mention {c['drug']}: {c['source']['url']}")
                continue
            if final != c["source"]["url"]:                 # follow redirects to the real page
                if config.is_aggregator(final):
                    continue
                c["source"]["url"], c["source"]["type"] = final, config.classify_source(final)
            c["source"]["checked"] = status
            action, e = store.upsert(events, c, _now())
            print(f"  {action}: {e['drug']} ({e['company']}) {e['date']} [page check: {status}]")


def cmd_outcomes(args, events, cl, today):
    for e in outcomes.due(events, today)[:args.max_outcomes]:
        try:
            res = outcomes.apply(e, outcomes.check(cl, e), _now())
        except Exception as ex:
            print(f"Outcome skipped for {e['drug']}: {ex}")
            continue
        print(f"Outcome: {e['drug']} -> {res}")


def cmd_check():
    """Quick test of the key, the model name and web search, before a long run."""
    print(f"Provider: {config.PROVIDER}   Model: {config.MODEL}")
    cl = llm.client()
    print("1. Plain call:", llm.ask(cl, "Reply with the single word OK.", "Say OK.").strip()[:60] or "(empty reply)")
    reply = llm.ask(cl, "Answer in one short sentence.", "Using web search, name one FDA drug approval announced in the last month.", web=True)
    print("2. Web search call:", reply.strip()[:300] or "(empty reply: search may not be available on this key or model)")
    print("If both lines show sensible text, you are ready.")


def cmd_publish(args, events, today):
    payload = pub.publish(events, store.load(OVERRIDES), today, _now())
    print(f"Published {payload['meta']['count']} events")


def _stage(name, fn, *a):
    """A failing stage is reported loudly but does not stop the others or the publish step."""
    try:
        fn(*a)
    except Exception as ex:
        print(f"WARNING: the {name} stage failed and was skipped: {ex}")


def main():
    ap = argparse.ArgumentParser(prog="pipeline")
    ap.add_argument("command", choices=["check", "edgar", "web", "outcomes", "publish", "all", "approve", "reject"])
    ap.add_argument("event_id", nargs="?")
    ap.add_argument("--days", type=int, default=120, help="how far back EDGAR is searched")
    ap.add_argument("--indication", help="limit web search to one tracked indication, e.g. Melanoma")
    ap.add_argument("--max-docs", type=int, default=60)
    ap.add_argument("--max-outcomes", type=int, default=15)
    args = ap.parse_args()
    today = dt.date.today()
    events = store.load(EVENTS)

    if args.command == "check":
        cmd_check()
        return
    if args.command in ("approve", "reject"):
        ov = store.load(OVERRIDES)
        ov[args.event_id] = {"review": "verified" if args.command == "approve" else "rejected", "ts": _now()}
        store.save(OVERRIDES, ov)
        print(f"{args.command}d {args.event_id}")
        return
    if args.command in ("edgar", "web", "outcomes", "all"):
        cl = llm.client()
        if args.command in ("edgar", "all"):
            _stage("edgar", cmd_edgar, args, events, cl, today)
            store.save(EVENTS, events)
        if args.command in ("web", "all"):
            _stage("web", cmd_web, args, events, cl, today)
            store.save(EVENTS, events)
        if args.command in ("outcomes", "all"):
            _stage("outcomes", cmd_outcomes, args, events, cl, today)
            store.save(EVENTS, events)
    if args.command in ("publish", "all"):
        cmd_publish(args, events, today)


if __name__ == "__main__":
    main()
