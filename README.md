# PDUFA tracker

A static website of FDA decision dates by therapeutic area and condition, filled by a pipeline
that reads only primary sources: SEC filings, company press releases and FDA pages.
It does not use pdufa.bio or any other catalyst calendar. Those domains are blocked in code
(`pipeline/config.py`).

```
site/            the website (plain HTML, no build step). Reads site/data/events.js
data/            events.json (full store with history), overrides.json (human reviews), state.json
pipeline/        the code that finds, checks and publishes dates
scripts/seed.py  builds the starting data from documents read by hand
tests/           pytest suite for the rules that matter
.github/         daily refresh and deploy to GitHub Pages
```

## How a date gets onto the site

1. **EDGAR scan** (`python -m pipeline edgar`). Full-text search of recent 8-Ks and 6-Ks (foreign companies file 6-Ks) for "PDUFA" and
   "target action date". Only the paragraphs around those words are sent to Claude, which returns
   structured dates. Each filing is processed once.
2. **Web search** (`python -m pipeline web`). For each of the nine tracked indications, Claude runs two
   searches (new applications, then label expansions) for company announcements that EDGAR misses.
   Aggregators are blocked. Test one indication first: `python -m pipeline web --indication Melanoma`.
3. **Validation.** A result is dropped if it has no source link, cites an aggregator, has an invalid
   date, or is long past. Month and quarter dates are never turned into a made-up day.
4. **Merge** (`pipeline/store.py`). Results are matched to existing events by company, drug and
   indication (early-stage and advanced-stage disease never merge). A newer source that gives a
   different date moves the date and writes a history entry. An older conflicting source is kept as a
   visible conflict.
5. **Trust level.** *Verified*: two separate primary channels (SEC, FDA, company release) give the
   same date, or a person approved it. *Single primary source*: one. *Unverified*: news coverage only.
6. **Outcomes** (`python -m pipeline outcomes`). When a goal date passes, Claude looks for the
   decision. Only a primary source can change a status.
7. **Publish** (`python -m pipeline publish`) writes `site/data/events.js`, `events.json` and `pdufa.ics`.

## Scope: nine indications

`pipeline/scope.py` lists what is tracked: Alzheimer's Disease, Arthritis, Breast Cancer, Colorectal
Cancer, Melanoma, Non-Small Cell Lung Cancer, Obesity, Pancreatic Cancer, Prostate Cancer. The names
match the trials app so rows can be joined on them. Anything else is dropped before it is stored, and
filings that never mention these diseases are not sent to the model. Small cell lung cancer is excluded.
If the model gives an indication and a condition that point at two different tracked diseases, the result
is dropped instead of guessed. To widen scope, add an entry to `INDICATIONS`; nothing else changes.
Rows already stored for other diseases stay in `data/events.json` and are simply not published.

## Use it from Google Sheets or Apps Script

The pipeline publishes three feeds next to the website (replace USER and REPO):

| File | Use |
|---|---|
| `https://USER.github.io/REPO/data/events.json` | Full data with sources and history. For Apps Script. |
| `https://USER.github.io/REPO/data/by_indication.json` | One summary row per tracked indication (counts, next decision, events). For the indication explorer. |
| `https://USER.github.io/REPO/data/events.csv` | One flat row per event. For Sheets without any script. |
| `https://USER.github.io/REPO/pdufa.ics` | Calendar of exact dates that have a company, SEC or FDA source. |

1. **No code:** in a Sheet, `=IMPORTDATA("https://USER.github.io/REPO/data/events.csv")`.
2. **Apps Script:** paste `integrations/google/Code.gs` into Extensions > Apps Script, set `DATA_URL`,
   run `refreshPdufa`, then `installDailyTrigger`. Other scripts can call
   `getPdufaForIndication("Melanoma")`.
3. **Google Calendar:** Other calendars > From URL > paste the `.ics` link. Google refreshes
   subscribed calendars on its own schedule, which can be many hours.
4. These links work only if the site is public. For a private repository, put a token in Script
   Properties and send it in the request header (see the comment in `Code.gs`).

## Run it on your laptop with a Gemini key (nothing public)

1. Get a key at aistudio.google.com (Get API key). Install Python 3.12 or newer.
2. In the project folder: `python -m venv .venv`, activate it
   (Mac or Linux `source .venv/bin/activate`; Windows `.venv\Scripts\activate.bat`),
   then `pip install -r requirements.txt`.
3. Copy `.env.example` to `.env` and fill in `GEMINI_API_KEY` and `SEC_USER_AGENT`
   (your own name and email). `.env` is ignored by git, so the key is not uploaded by accident.
4. `python -m pytest -q` (all tests should pass), then `python -m pipeline check`
   (tests the key, the model name and web search).
5. First small run: `python -m pipeline web --indication Melanoma`, then `python -m pipeline publish`.
   Open `site/index.html` by double-clicking it.
6. Full run: `python -m pipeline all`. On the free tier expect 15 to 40 minutes because of rate limits.
7. Review rows, then approve or reject: `python -m pipeline approve ID` / `reject ID`, and publish again.

Gemini notes: its API cannot exclude domains server-side, so aggregators such as pdufa.bio are removed
in code after the search, and every cited page is opened and checked (`pipeline/cite.py`). A page that
cannot be confirmed is kept but shown as "page not confirmed" and never counts toward Verified.
Model names change; if `check` says the model is not found, set `PDUFA_MODEL` in `.env` to a current
Flash model from the AI Studio model list. Free-tier inputs may be used by Google to improve its models;
this project sends only public filings, web pages and drug names.

To feed Google Sheets without making anything public, set `PDUFA_EXPORT_DIR` in `.env` to a folder inside
Google Drive for Desktop. Each publish copies `events.json`, `events.csv` and `pdufa.ics` there, and
`integrations/google/Code.gs` (with `SOURCE = 'drive'`) reads the file. Or import `events.csv` by hand.

Back up the `data` folder: it holds the history and your reviews.

## Put it online for teammates (GitHub Pages, refreshed on a schedule)

1. Push this folder to a GitHub repository.
2. Settings > Pages > Source: GitHub Actions.
3. Settings > Actions > General > Workflow permissions: Read and write.
4. Settings > Secrets and variables > Actions: add secret `GEMINI_API_KEY` (or `ANTHROPIC_API_KEY` for
   Claude) and secret `SEC_USER_AGENT` (a secret is hidden in the run logs, a variable is not).
5. Actions tab > "Refresh data and deploy site" > Run workflow. It then runs on the schedule in
   `.github/workflows/refresh.yml`.

**Who can open it.** A GitHub Pages site is reachable by anyone who has the link. The content is only
public-source dates and your list of tracked indications. If you need to limit it to teammates, put the
`site/` folder behind a login instead, for example Cloudflare Pages with Cloudflare Access (email
one-time codes for your company domain). Know the trade-off: a login also blocks other programs, so the
indication explorer then needs a service token to read the data feeds.

## Feeding the indication explorer

Read `by_indication.json` (or `events.json`) from the site address. Rows use the same indication names
as the trials app, so join on `label`. `schema_version` is 1; it will change if a field is ever renamed.

```javascript
// In a browser app. GitHub Pages normally allows other sites to read these files.
const feed = await (await fetch("https://USER.github.io/REPO/data/by_indication.json")).json();
const row = feed.indications.find(r => r.label === "Melanoma");
// row.upcoming, row.awaiting_outcome, row.decided, row.next_decision.drug, row.next_decision.date, row.events[]
```

In Apps Script, `getPdufaSummary("Melanoma")` in `integrations/google/Code.gs` does the same with
`UrlFetchApp`. Show `trust` next to any date you display, and treat `unverified` rows as leads.

## Choosing the model (cost lever)

The default model is `claude-sonnet-5-5`. To cut cost, add a repository variable named `PDUFA_MODEL`
(Settings > Secrets and variables > Actions > Variables) with the value `claude-haiku-4-5-20251001`.
Compare it with the default on the same 20 known decisions before trusting it, because a cheaper model
can misread filings more often. Web search is billed per search on top of tokens, so running weekly instead
of daily saves more than any model switch.

## If a run goes wrong

Each stage (edgar, web, outcomes) fails on its own. A broken stage prints `WARNING: the ... stage failed`
in the Actions log, and the other stages and the publish step still run. Open the run log and search for
"WARNING" or "skipped" after every early run.

## Known limits

- **Not yet run against live sources.** The code was tested with fixtures and mocked model answers.
  The EDGAR full-text search endpoint is not formally documented by the SEC; if its JSON changes,
  fix `edgar.parse_hit`. The first real run needs a human look at what it produced.
- **Models can misread filings.** That is why results start unverified or single-source, every row
  links its source, and a reviewer can approve or reject. Spot-check before sharing widely.
- **"Verified" means channels agree**, not that the company is right. SEC and a press release from
  the same issuer are two channels, not two independent opinions.
- **Coverage.** Companies not registered with the SEC (Roche, for example) never appear in EDGAR and are found only by web search. Companies often name only a quarter. Private companies may say nothing. Ex-US
  regulators (EMA and others) are not included yet.
- **Cost and time.** A full run makes dozens of model calls, 13 of them with web search. Start weekly,
  then move to daily once you trust the output.
- **Seed data.** `scripts/seed.py` holds 7 rows read from documents during development; two rely on
  news sources and show as Unverified. Delete `data/events.json` and re-run the pipeline to start clean.
