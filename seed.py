"""Build data/events.json from a handful of rows read directly from documents.

Rows outside the nine tracked indications (myeloma, Arikayce) stay in the data file but are not published.

Run once to create the starting data:  python scripts/seed.py
Every row here cites the exact document it came from. Nothing is copied from an
aggregator. Rows backed only by news sites stay "unverified" until the pipeline
or a reviewer finds the company's own announcement.
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pipeline import config, publish, store  # noqa: E402

TS = "2026-10-19T00:00:00Z"
AACR = "https://www.aacr.org/blog/2026/10/05/fda-approvals-in-oncology-july-september-2026/"


def src(url, name, published, date, evidence):
    return {"url": url, "name": name, "type": config.classify_source(url),
            "published": published, "date": date, "evidence": evidence}


def cand(drug, company, ind, area, cond, date, source):
    return {"drug": drug, "company": company, "indication": ind, "area": area,
            "condition": cond, "date": date, "source": source}


ROWS = [
    cand("Zidesamtinib (NVL-520)", "Nuvalent", "ROS1-positive NSCLC after at least one prior ROS1 TKI", "onc", "Non-Small Cell Lung Cancer", "2026-09-18",
         src("https://www.sec.gov/Archives/edgar/data/1861560/000119312526073304/nuvl-ex99_1.htm",
             "Nuvalent 8-K, Exhibit 99.1", None, "2026-09-18",
             "Company says FDA accepted the NDA and set a September 18, 2026 PDUFA date.")),
    cand("Iberdomide + daratumumab + dexamethasone", "Bristol Myers Squibb", "Relapsed or refractory multiple myeloma", "onc", "Multiple myeloma", "2026-08-17",
         src("https://www.sec.gov/Archives/edgar/data/0000014272/000001427226000018/q22026earningspresentati.htm",
             "BMS Q2 2026 earnings slides (8-K)", None, "2026-08-17",
             "Slide lists an August 17, 2026 PDUFA date for iberdomide.")),
    cand("Mezigdomide", "Bristol Myers Squibb", "Multiple myeloma (indication not stated on the slide)", "onc", "Multiple myeloma", "2027-05-13",
         src("https://www.sec.gov/Archives/edgar/data/0000014272/000001427226000018/q22026earningspresentati.htm",
             "BMS Q2 2026 earnings slides (8-K)", None, "2027-05-13",
             "Slide lists a May 13, 2027 PDUFA date for mezigdomide.")),
    cand("Jemperli (dostarlimab)", "GSK", "Untreated stage II/III dMMR/MSI-H locally advanced rectal cancer", "onc", "Colorectal Cancer", "2027-02",
         src("https://www.sec.gov/Archives/edgar/data/0001370053/000119312526396690/anab-ex99_1.htm",
             "AnaptysBio 8-K, Exhibit 99.1 (royalty holder reporting GSK's filing)", "2026-09-21", "2027-02",
             "FDA set a February 2027 PDUFA date; a priority voucher could bring a decision sooner.")),
    cand("Arikayce (amikacin liposome inhalation suspension)", "Insmed", "MAC lung disease, full approval (sNDA)", "inf", "MAC lung disease", "2027-01-28",
         src("https://investor.insmed.com/2026-09-21-FDA-Grants-Priority-Review-to-Insmeds-sNDA-for-ARIKAYCE-R-amikacin-liposome-inhalation-suspension-for-Treatment-of-MAC-Lung-Disease-With-PDUFA-Target-Action-Date-Set-for-January-28,-2027",
             "Insmed press release", "2026-09-21", "2027-01-28",
             "Insmed says FDA granted priority review and set a January 28, 2027 target date.")),
    cand("Ivonescimab + platinum-doublet chemotherapy", "Summit Therapeutics",
         "EGFR-mutated locally advanced or metastatic non-squamous NSCLC after a third-generation EGFR-TKI", "onc", "Non-Small Cell Lung Cancer", "2026-11-14",
         src("https://www.zacks.com/stock/news/2826275/fda-accepts-smmt-s-application-seeking-approval-for-nsclc-drug",
             "Zacks (news report)", None, "2026-11-14",
             "Report says FDA accepted the BLA with a November 14, 2026 target date.")),
    cand("Zipalertinib", "Taiho Oncology / Cullinan Therapeutics",
         "EGFR exon 20 insertion NSCLC after platinum-based chemotherapy", "onc", "Non-Small Cell Lung Cancer", "2027-02-27",
         src("https://stocktitan.net/news/CGEM/u-s-food-and-drug-administration-accepts-new-drug-application-for-o7dz8md64r08.html",
             "Stock Titan (reprint of company release)", None, "2027-02-27",
             "Reprint says FDA accepted the NDA with a February 27, 2027 target date.")),
]

if __name__ == "__main__":
    events = {}
    for c in ROWS:
        store.upsert(events, c, TS)
    # Outcomes read from a secondary source: shown, but the review level stays honest.
    for e in events.values():
        if e["drug"].startswith(("Zidesamtinib", "Iberdomide")):
            e["status"], e["decided"] = "approved", "2026-Q3"
            e["status_sources"].append(src(AACR, "AACR: FDA approvals in oncology, Q3 2026", "2026-10-05", None,
                                           "AACR lists this approval during the third quarter of 2026."))
            e["history"].append({"ts": TS, "field": "status", "old": "pending", "new": "approved", "source": AACR})
    store.save(os.path.join(config.DATA_DIR, "events.json"), events)
    publish.publish(events, {}, dt.date(2026, 10, 19), TS)
    print(f"Seeded {len(events)} events")
