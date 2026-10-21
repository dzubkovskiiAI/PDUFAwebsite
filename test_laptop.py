import datetime as dt
import re
import pytest

from pipeline import cite, config, llm, publish, store, validate

TODAY = dt.date(2026, 10, 19)
TS = "2026-10-19T06:00:00Z"


class Resp:
    def __init__(self, text, status=200, url="https://www.businesswire.com/news/x", ctype="text/html"):
        self.text, self.status_code, self.url, self.headers = text, status, url, {"content-type": ctype}


PAGE = ("Examplimab news release. " * 80 + " The FDA set a PDUFA target action date of March 14, 2027 for Examplimab.")


# ---- page check ----
def test_date_patterns_match_common_formats():
    pats = cite.date_patterns("2027-03-14")
    for text in ["March 14, 2027", "Mar. 14, 2027", "14 March 2027", "2027-03-14", "3/14/2027", "03/14/2027"]:
        assert any(re.search(p, text, re.I) for p in pats), text
    assert any(re.search(p, "first quarter of 2027", re.I) for p in cite.date_patterns("2027-Q1"))
    assert any(re.search(p, "February 2027", re.I) for p in cite.date_patterns("2027-02"))


def test_check_statuses():
    ok = lambda u: Resp(PAGE)
    assert cite.check("https://x.com/a", "Examplimab", "2027-03-14", getter=ok)[0] == "ok"
    weak = lambda u: Resp(PAGE.replace("March 14, 2027", "sometime"))
    assert cite.check("https://x.com/a", "Examplimab", "2027-03-14", getter=weak)[0] == "weak"
    other = lambda u: Resp("A long page about something else entirely. " * 80)
    assert cite.check("https://x.com/a", "Examplimab", "2027-03-14", getter=other)[0] == "mismatch"
    assert cite.check("https://x.com/a", "Examplimab", "2027-03-14", getter=lambda u: Resp("", status=404))[0] == "unreachable"
    assert cite.check("https://x.com/a", "Examplimab", "2027-03-14", getter=lambda u: Resp("tiny js shell"))[0] == "unreachable"
    assert cite.check("https://x.com/a", "Examplimab", "2027-03-14", getter=lambda u: Resp(PAGE, ctype="application/pdf"))[0] == "unreachable"

    def boom(u):
        raise ConnectionError("down")
    assert cite.check("https://x.com/a", "Examplimab", "2027-03-14", getter=boom)[0] == "unreachable"


def test_redirects_are_resolved():
    redirect = lambda u: Resp(PAGE, url="https://www.businesswire.com/real-release")
    status, final = cite.check("https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc", "Examplimab", "2027-03-14", getter=redirect)
    assert status == "ok" and final == "https://www.businesswire.com/real-release"


# ---- trust only counts pages that were confirmed ----
def _cand(url, checked, published="2026-09-01"):
    return validate.clean({"drug": "Examplimab", "company": "ExampleBio", "indication": "EGFR NSCLC", "condition": "NSCLC",
                           "date": "2027-03-14", "source_url": url, "checked": checked}, TODAY, "src", published)


def test_unconfirmed_primary_source_does_not_build_trust():
    ev = {}
    _, e = store.upsert(ev, _cand("https://www.businesswire.com/a", "weak"), TS)
    assert e["review"] == "unverified"
    _, e = store.upsert(ev, _cand("https://www.sec.gov/b", "ok", "2026-09-02"), TS)
    assert e["review"] == "primary"
    _, e = store.upsert(ev, _cand("https://www.prnewswire.com/c", "ok", "2026-09-03"), TS)
    assert e["review"] == "verified"


# ---- provider and .env ----
def test_provider_choice():
    assert config.pick_provider({"GEMINI_API_KEY": "k"}) == ("gemini", "gemini-2.5-flash")
    assert config.pick_provider({"ANTHROPIC_API_KEY": "k"}) == ("anthropic", "claude-sonnet-5-5")
    assert config.pick_provider({"GEMINI_API_KEY": "k", "PDUFA_PROVIDER": "anthropic"})[0] == "anthropic"
    assert config.pick_provider({"GEMINI_API_KEY": "k", "PDUFA_MODEL": "gemini-x"})[1] == "gemini-x"
    assert config.pick_provider({"GEMINI_API_KEY": "k", "PDUFA_MODEL": ""})[1] == "gemini-2.5-flash"


def test_env_file_loader(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text('# comment\nGEMINI_API_KEY="abc123"\nSEC_USER_AGENT=Jane Doe jane@x.com\nEMPTY=\nALREADY=fromfile\n')
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    monkeypatch.delenv("EMPTY", raising=False)
    monkeypatch.setenv("ALREADY", "fromenv")
    config.load_env(str(f))
    import os
    assert os.environ["GEMINI_API_KEY"] == "abc123" and os.environ["SEC_USER_AGENT"] == "Jane Doe jane@x.com"
    assert "EMPTY" not in os.environ and os.environ["ALREADY"] == "fromenv"      # real environment wins


# ---- Gemini call path with a fake client ----
class FakeModels:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def generate_content(self, model, contents, config):
        self.calls.append((model, contents, config))
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return type("R", (), {"text": r})()


class FakeClient:
    def __init__(self, replies):
        self.models = FakeModels(replies)


def test_gemini_ask_uses_search_tool_and_retries(monkeypatch):
    pytest.importorskip("google.genai")
    monkeypatch.setattr(config, "PROVIDER", "gemini")
    monkeypatch.setattr(config, "MODEL", "gemini-test")
    monkeypatch.setattr(config, "CALL_DELAY", 0)
    sleeps = []
    monkeypatch.setattr(llm.time, "sleep", lambda s: sleeps.append(s))
    cl = FakeClient([RuntimeError("429 RESOURCE_EXHAUSTED"), '[{"drug":"A"}]'])
    out = llm.ask(cl, "system text", "prompt text", web=True)
    assert out == '[{"drug":"A"}]' and sleeps == [20]
    model, contents, cfg = cl.models.calls[0]
    assert model == "gemini-test" and contents == "prompt text"
    assert cfg.tools and cfg.tools[0].google_search is not None and cfg.system_instruction == "system text"
    cl2 = FakeClient(["plain"])
    llm.ask(cl2, "s", "p", web=False)
    assert cl2.models.calls[0][2].tools is None


def test_gemini_non_transient_error_is_raised(monkeypatch):
    pytest.importorskip("google.genai")
    monkeypatch.setattr(config, "PROVIDER", "gemini")
    monkeypatch.setattr(config, "CALL_DELAY", 0)
    with pytest.raises(RuntimeError, match="API key not valid"):
        llm.ask(FakeClient([RuntimeError("400 API key not valid")]), "s", "p")


def test_missing_gemini_key_message(monkeypatch):
    monkeypatch.setattr(config, "PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match=".env"):
        llm.client()


# ---- export folder ----
def test_export_dir_copy(tmp_path, monkeypatch):
    export = tmp_path / "drive"
    export.mkdir()
    monkeypatch.setattr(config, "EXPORT_DIR", str(export))
    ev = {}
    store.upsert(ev, _cand("https://www.sec.gov/a", "ok"), TS)
    publish.publish(ev, {}, TODAY, TS, site_dir=str(tmp_path / "site"))
    assert sorted(p.name for p in export.iterdir()) == ["by_indication.json", "events.csv", "events.json", "pdufa.ics"]


# ---- explorer feed ----
def test_by_indication_feed(tmp_path):
    import json
    ev = {}
    store.upsert(ev, _cand("https://www.sec.gov/a", "ok"), TS)                       # NSCLC, 2027-03-14, upcoming
    store.upsert(ev, validate.clean({"drug": "Oldmab", "company": "OldCo", "indication": "metastatic prostate cancer",
                                     "condition": "Prostate Cancer", "date": "2026-10-10", "source_url": "https://www.sec.gov/o"},
                                    TODAY, "s", "2026-09-01"), TS)                   # goal date passed, no outcome yet
    publish.publish(ev, {}, TODAY, TS, site_dir=str(tmp_path / "site"))
    feed = json.loads((tmp_path / "site" / "data" / "by_indication.json").read_text())
    assert feed["schema_version"] == 1 and len(feed["indications"]) == 9
    by = {r["label"]: r for r in feed["indications"]}
    nsclc = by["Non-Small Cell Lung Cancer"]
    assert nsclc["upcoming"] == 1 and nsclc["next_decision"]["date"] == "2027-03-14" and nsclc["next_decision"]["precision"] == "day"
    prostate = by["Prostate Cancer"]
    assert prostate["upcoming"] == 0 and prostate["awaiting_outcome"] == 1 and prostate["next_decision"] is None
    assert by["Melanoma"]["upcoming"] == 0 and by["Melanoma"]["events"] == []          # every indication is listed
    meta = json.loads((tmp_path / "site" / "data" / "events.json").read_text())["meta"]
    assert meta["schema_version"] == 1
