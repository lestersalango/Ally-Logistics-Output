# Carrier Lane Scorecard — submission

A Databricks medallion pipeline (bronze → silver → gold) that answers: for October 2026 (US Eastern pickup date), per carrier × lane, how many Delivered loads, what revenue, cost and margin, and how many loads were hauled while unauthorized or by a carrier not in FMCSA.

## Final totals

| Gold rows | Loads | Revenue | Carrier cost | Gross margin | Margin % | Unauthorized | Unverified |
|---|---|---|---|---|---|---|---|
| 758 | 1,366 | 4,004,780.61 | 3,360,830.64 | 643,949.97 | 16.08 % | 154 | 20 |

These totals were reproduced exactly by an independent plain-Python check (`tools/reference_totals.py`).

## Start here

| File | What it is |
|---|---|
| `docs/reports/carrier_scorecard_summary.pdf` | 3-page summary: what was done, data problems, proof of quality, dashboard |
| `docs/reports/notebook_run_2026-11-18.html` | The notebook **with its outputs** from a job run (open in a browser) |
| `src/carrier_lane_scorecard.py` | The notebook source (Databricks format): profiling, bronze, silver (incremental MERGE), gold, 15 data-quality checks, talking points |

## Everything else

| Path | Contents |
|---|---|
| `carrier_scorecard_exercise/` | The exercise as given: problem brief, data dictionary, the two CSVs |
| `resources/carrier_lane_scorecard.job.json` | Lakeflow job: serverless, daily 06:00 ET (paused), 1 retry, timeout, failure and slow-run emails |
| `src/serving/carrier_lane_scorecard.lvdash.json` | AI/BI dashboard definition (screenshot: `docs/reports/dashboard_2026-11-18.png`) |
| `tools/reference_totals.py` | Independent check of the totals (no Spark) |
| `tools/new_feed/loads_2026-11-19.csv` | Test change feed used to prove the incremental MERGE (later removed from the tables) |
| `tools/build_dashboard.py`, `tools/build_summary_pdf.py` | Generate the dashboard JSON and the summary PDF |
| `docs/runbook.md` | How to run, monitor, recover and remove it |
| `requirements-dev.txt` | Pinned local Python packages (for the tools only) |

## Run it

1. Upload the two CSVs to a Unity Catalog volume folder `<catalog>/<schema>/<volume>/raw/`.
2. Import `src/carrier_lane_scorecard.py` as a notebook, set the `catalog`, `schema` and `volume` widgets, and run all on serverless.
3. Optional local check: `pip install -r requirements-dev.txt`, then `python tools/reference_totals.py`.

The full commands are in `docs/runbook.md`.
