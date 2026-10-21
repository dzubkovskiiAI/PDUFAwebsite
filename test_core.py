import datetime as dt
import json

from pipeline import config, edgar, llm, model, outcomes, publish, scope, store, validate

TODAY = dt.date(2026, 10, 19)
TS = "2026-10-19T06:00:00Z"


def cand(drug="Examplimab", company="ExampleBio", ind="EGFR NSCLC", date="2027-03-14",
         url="https://www.sec.gov/Archives/edgar/data/1/2/x.htm", published="2026-09-01", area="onc", cond="NSCLC"):
    raw = {"drug": drug, "company": company, "indication": ind, "area": area, "condition": cond,
           "date": date, "source_url": url, "evidence": "Company states the goal date."}
    return validate.clean(raw, TODAY, "Test source", published)


# ---- dates ----
def test_parse_when_precisions():
    assert model.parse_when("2026-10-09")[0] == "day"
    assert model.parse_when("2026-12")[1:] == (dt.date(2026, 12, 1), dt.date(2026, 12, 31))
    assert model.parse_when("2026-Q4")[1:] == (dt.date(2026, 10, 1), dt.date(2026, 12, 31))
    assert model.parse_when("2026-13") is None
    assert model.parse_when("2026-02-30") is None
    assert model.parse_when("soon") is None


# ---- source policy ----
def test_aggregators_rejected():
    assert cand(url="https://www.pdufa.bio/ticker/X") is None
    assert cand(url="https://app.biopharmcatalyst.com/x") is None


def test_source_classification():
    assert config.classify_source("https://www.sec.gov/a") == "sec"
    assert config.classify_source("https://www.fda.gov/b") == "fda"
    assert config.classify_source("https://www.businesswire.com/c") == "press_release"
    assert config.classify_source("https://investor.insmed.com/d") == "press_release"
    assert config.classify_source("https://www.zacks.com/e") == "secondary"
    assert config.classify_source("https://stocktitan.net/f") == "secondary"


def test_bad_candidates_dropped():
    assert cand(date="2024-01-01") is None          # long past
    assert cand(date="Q4") is None
    assert validate.clean({"drug": "", "date": "2027-01", "source_url": "https://x.com"}, TODAY) is None
    assert validate.clean({"drug": "A", "date": "2027-01", "source_url": "ftp://x"}, TODAY) is None
    assert cand()["area"] == "onc" and cand()["condition"] == "Non-Small Cell Lung Cancer"   # set by scope, not by the model


# ---- merging and trust ----
def test_new_then_trust_levels():
    ev = {}
    action, e = store.upsert(ev, cand(), TS)
    assert action == "new" and e["review"] == "primary"
    # same date from a second primary channel -> verified
    c2 = cand(url="https://www.businesswire.com/news/1", published="2026-09-02")
    action, e = store.upsert(ev, c2, TS)
    assert action == "source_added" and e["review"] == "verified" and len(ev) == 1


def test_secondary_only_is_unverified():
    ev = {}
    _, e = store.upsert(ev, cand(url="https://www.zacks.com/stock/news/1"), TS)
    assert e["review"] == "unverified"


def test_same_host_does_not_double_count():
    ev = {}
    store.upsert(ev, cand(url="https://www.sec.gov/Archives/a.htm"), TS)
    _, e = store.upsert(ev, cand(url="https://www.sec.gov/Archives/b.htm", published="2026-09-02"), TS)
    assert e["review"] == "primary"


def test_newer_source_moves_date_and_records_history():
    ev = {}
    store.upsert(ev, cand(date="2027-03-14", published="2026-09-01"), TS)
    c = cand(date="2027-06-14", url="https://www.businesswire.com/news/2", published="2026-12-01")
    # still validly in the future relative to TODAY
    action, e = store.upsert(ev, c, TS)
    assert action == "updated" and e["date"] == "2027-06-14"
    assert e["history"][-1]["field"] == "date" and e["history"][-1]["old"] == "2027-03-14"


def test_older_conflicting_source_is_kept_as_conflict():
    ev = {}
    store.upsert(ev, cand(date="2027-03-14", published="2026-09-01"), TS)
    c = cand(date="2027-02-01", url="https://www.businesswire.com/news/3", published="2026-05-01")
    action, e = store.upsert(ev, c, TS)
    assert action == "conflict" and e["date"] == "2027-03-14" and e["conflicts"][0]["date"] == "2027-02-01"


def test_different_indications_stay_separate():
    ev = {}
    store.upsert(ev, cand(drug="Giredestrant", company="Roche", ind="Early breast cancer", cond="Breast Cancer"), TS)
    store.upsert(ev, cand(drug="Giredestrant + everolimus", company="Roche",
                          ind="ER-positive advanced breast cancer metastatic", cond="Breast Cancer", url="https://www.sec.gov/z.htm"), TS)
    assert len(ev) == 2


# ---- outcomes ----
def _pending(ev):
    _, e = store.upsert(ev, cand(date="2026-10-01"), TS)
    return e


def test_due_and_apply_primary_only():
    ev = {}
    e = _pending(ev)
    assert outcomes.due(ev, TODAY) == [e]
    # a secondary source cannot change status
    r = outcomes.apply(e, {"status": "approved", "source_url": "https://www.zacks.com/x"}, TS)
    assert r == "no_primary_source" and e["status"] == "pending"
    # a primary source can
    r = outcomes.apply(e, {"status": "approved", "decision_date": "2026-09-28",
                           "source_url": "https://www.fda.gov/news/x", "evidence": "FDA approved it."}, TS)
    assert r == "approved" and e["status"] == "approved" and e["history"][-1]["field"] == "status"
    assert outcomes.due(ev, TODAY) == []


def test_extension_updates_date_with_history():
    ev = {}
    e = _pending(ev)
    r = outcomes.apply(e, {"status": "extended", "new_goal_date": "2027-01-01",
                           "source_url": "https://www.businesswire.com/n"}, TS)
    assert r == "extended" and e["date"] == "2027-01-01" and e["history"][-1]["old"] == "2026-10-01"


def test_recheck_throttle():
    ev = {}
    e = _pending(ev)
    e["outcome_checked"] = "2026-10-18T00:00:00Z"
    assert outcomes.due(ev, TODAY) == []


# ---- parsing helpers ----
def test_parse_json_variants():
    assert llm.parse_json('```json\n[{"a":1}]\n```', "[", "]") == [{"a": 1}]
    assert llm.parse_json('Here: [{"a":1},{"b":2}] done', "[", "]") == [{"a": 1}, {"b": 2}]
    assert llm.parse_json('[{"a":1},{"b":2', "[", "]") == [{"a": 1}]      # truncated
    assert llm.parse_json('{"status":"ok"}', "{", "}") == {"status": "ok"}
    assert llm.parse_json("no json", "[", "]") is None


def test_edgar_parse_hit_and_snippets():
    hit = {"_id": "0001193125-26-396690:anab-ex99_1.htm",
           "_source": {"ciks": ["0001370053"], "display_names": ["AnaptysBio, Inc.  (ANAB)  (CIK 0001370053)"],
                       "file_date": "2026-09-21", "form": "8-K"}}
    h = edgar.parse_hit(hit)
    assert h["url"] == "https://www.sec.gov/Archives/edgar/data/1370053/000119312526396690/anab-ex99_1.htm"
    assert h["company"] == "AnaptysBio, Inc." and h["published"] == "2026-09-21"
    text = "x" * 2000 + " The FDA set a PDUFA action date of February 2027. " + "y" * 2000
    sn = edgar.snippets(text)
    assert len(sn) == 1 and "PDUFA" in sn[0]
    assert edgar.snippets("nothing relevant here") == []


# ---- publishing ----
def test_publish_files_and_overrides(tmp_path):
    ev = {}
    _, a = store.upsert(ev, cand(date="2026-11-20"), TS)
    _, b = store.upsert(ev, cand(drug="Zzz", company="Other Co", ind="metastatic prostate cancer", cond="Prostate Cancer", date="2026-12-01",
                                 url="https://www.zacks.com/n"), TS)
    _, c = store.upsert(ev, cand(drug="Rejectme", company="Bad Co", ind="pancreatic cancer", cond="Pancreatic Cancer", date="2026-12-05"), TS)
    payload = publish.publish(ev, {c["id"]: {"review": "rejected"}, b["id"]: {"review": "verified"}},
                              TODAY, TS, site_dir=str(tmp_path))
    ids = {e["id"]: e for e in payload["events"]}
    assert c["id"] not in ids and ids[b["id"]]["review"] == "verified"
    assert (tmp_path / "data" / "events.js").read_text().startswith("window.PDUFA_DATA = ")
    json.loads((tmp_path / "data" / "events.json").read_text())
    ics = (tmp_path / "pdufa.ics").read_text()
    assert "PDUFA: Examplimab" in ics and "PDUFA: Zzz" in ics and "Rejectme" not in ics


# ---- scope: the nine tracked indications ----
def test_scope_labels_match_the_trials_app():
    assert [i["label"] for i in scope.INDICATIONS] == [
        "Alzheimer's Disease", "Arthritis", "Breast Cancer", "Colorectal Cancer", "Melanoma",
        "Non-Small Cell Lung Cancer", "Obesity", "Pancreatic Cancer", "Prostate Cancer"]


def test_scope_classification():
    c = lambda *t: (scope.classify(*t) or {}).get("label")
    assert c("Stage III colon cancer") == "Colorectal Cancer"
    assert c("locally advanced rectal cancer") == "Colorectal Cancer"
    assert c("EGFR-mutated NSCLC") == "Non-Small Cell Lung Cancer"
    assert c("non-small cell lung cancer after prior therapy") == "Non-Small Cell Lung Cancer"
    assert c("extensive-stage small cell lung cancer") is None            # SCLC is out of scope
    assert c("psoriatic arthritis") == "Arthritis" and c("axial spondyloarthritis") == "Arthritis"
    assert c("chronic weight management in adults with overweight") == "Obesity"
    assert c("metastatic pancreatic adenocarcinoma") == "Pancreatic Cancer"
    assert c("exocrine pancreatic insufficiency") is None                 # not pancreatic cancer
    assert c("multiple myeloma") is None and c("hypertension") is None


def test_out_of_scope_candidates_dropped():
    assert cand(ind="relapsed multiple myeloma", cond="Multiple myeloma") is None
    assert cand(ind="plaque psoriasis", cond="Psoriasis") is None
    assert cand(ind="stage III colon cancer", cond="NSCLC") is None         # two tracked indications disagree
    assert cand(ind="EGFR exon 20 insertion mutations", cond="NSCLC") is not None   # condition alone can decide


def test_filing_prefilter():
    assert scope.mentions("PDUFA date for our breast cancer drug")
    assert not scope.mentions("PDUFA date for our gene therapy for hearing loss")


def test_unpublished_out_of_scope_rows_stay_in_store(tmp_path):
    ev = {}
    store.upsert(ev, {"drug": "Mezigdomide", "company": "BMS", "indication": "multiple myeloma", "area": "onc",
                      "condition": "Multiple myeloma", "date": "2027-05-13",
                      "source": {"url": "https://www.sec.gov/a", "name": "x", "type": "sec", "published": None,
                                 "date": "2027-05-13", "evidence": ""}}, TS)
    payload = publish.publish(ev, {}, TODAY, TS, site_dir=str(tmp_path))
    assert len(ev) == 1 and payload["events"] == []


# ---- spreadsheet feed ----
def test_csv_feed(tmp_path):
    ev = {}
    store.upsert(ev, cand(drug="=HYPERLINK(\"x\")"), TS)
    publish.publish(ev, {}, TODAY, TS, site_dir=str(tmp_path))
    rows = (tmp_path / "data" / "events.csv").read_text().splitlines()
    assert rows[0].startswith("id,indication,drug,company,detail,goal_date,precision,status")
    assert "Non-Small Cell Lung Cancer" in rows[1] and ",day," in rows[1]
    assert "'=HYPERLINK" in rows[1]                                         # formula neutralised
