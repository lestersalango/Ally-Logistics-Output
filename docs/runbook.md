# Runbook: Carrier Lane Scorecard

## What it does

One notebook turns the TMS load change feed and the FMCSA carrier census into `gold_carrier_lane_scorecard`: one row per carrier × lane for Delivered loads picked up in the report month (US Eastern), with revenue, cost, margin, and unauthorized and unverified load counts. The operations team uses it to see margin per carrier and lane and to spot carriers that hauled without authority.

Business rules: [data_dictionary.md](../carrier_scorecard_exercise/data_dictionary.md). Edge cases and expected totals: the "Profile the raw data" and "Interview talking points" sections of [the notebook](../src/carrier_lane_scorecard.py), and [the summary PDF](reports/carrier_scorecard_summary.pdf).

## Resources (dev only, no prod)

| Resource | Name | Link |
|---|---|---|
| Notebook (source of truth: [src/carrier_lane_scorecard.py](../src/carrier_lane_scorecard.py)) | `/Workspace/Users/lester.salango.pro@gmail.com/carrier_lane_scorecard` | [open](https://dbc-c4cb7bbd-1462.cloud.databricks.com/editor/notebooks/4023659587587009?o=7474656911982802) |
| Job (definition: [resources/carrier_lane_scorecard.job.json](../resources/carrier_lane_scorecard.job.json)) | `carrier_lane_scorecard`, id `697967429732215` | [open](https://dbc-c4cb7bbd-1462.cloud.databricks.com/jobs/697967429732215?o=7474656911982802) |
| Landing volume | `/Volumes/workspace/default/interview/raw/` | [open](https://dbc-c4cb7bbd-1462.cloud.databricks.com/explore/data/volumes/workspace/default/interview?o=7474656911982802) |
| Bronze | `workspace.default.bronze_loads`, `workspace.default.bronze_fmcsa_carriers` | [schema](https://dbc-c4cb7bbd-1462.cloud.databricks.com/explore/data/workspace/default?o=7474656911982802) |
| Silver | `workspace.default.silver_loads`, `workspace.default.silver_fmcsa_carriers` | same |
| Gold | `workspace.default.gold_carrier_lane_scorecard` | [open](https://dbc-c4cb7bbd-1462.cloud.databricks.com/explore/data/workspace/default/gold_carrier_lane_scorecard?o=7474656911982802) |
| Dashboard (built by [tools/build_dashboard.py](../tools/build_dashboard.py)) | `Carrier Lane Scorecard`, id `01f1e35942291816b926da78e98c569c`, warehouse `7dab9489683f6ff3` (Serverless Starter) | [published](https://dbc-c4cb7bbd-1462.cloud.databricks.com/dashboardsv3/01f1e35942291816b926da78e98c569c/published?o=7474656911982802) · [draft](https://dbc-c4cb7bbd-1462.cloud.databricks.com/dashboardsv3/01f1e35942291816b926da78e98c569c?o=7474656911982802) |

The notebook's widgets, which are also the job's parameters:

| Parameter | Default | Meaning |
|---|---|---|
| `catalog` / `schema` / `volume` | `workspace` / `default` / `interview` | Where files are read and tables written |
| `report_month` | `2026-10` | Month of the gold table (`YYYY-MM`, Eastern pickup date) |
| `reprocess_all_bronze` | `false` | `true` re-MERGEs every bronze row into silver (recovery) |
| `force_dq_failure` | `false` | `true` adds one failing check, to test the failure email |

## How to run it

All commands run from the project root with profile `DEFAULT`. In Git Bash, set `export MSYS_NO_PATHCONV=1` first so `/Users/...` and `/Volumes/...` paths aren't rewritten.

1. **Deploy a notebook change.** Edit `src/`, never the notebook in the UI:
   ```bash
   databricks workspace import "/Users/lester.salango.pro@gmail.com/carrier_lane_scorecard" --file src/carrier_lane_scorecard.py --format SOURCE --language PYTHON --overwrite --profile DEFAULT
   ```
2. **Deploy a job change** after editing the JSON. `reset` replaces all of the job's settings:
   ```bash
   databricks jobs reset --json "{\"job_id\": 697967429732215, \"new_settings\": $(cat resources/carrier_lane_scorecard.job.json)}" --profile DEFAULT
   ```
3. **Land new change-feed rows.** Use a **new file name** that starts with `loads` (for example `loads_2026-11-20.csv`). Never overwrite a file that is already there: `COPY INTO` skips files it has already loaded.
   ```bash
   databricks fs cp loads_2026-11-20.csv dbfs:/Volumes/workspace/default/interview/raw/loads_2026-11-20.csv --profile DEFAULT
   ```
   A new FMCSA snapshot replaces `fmcsa_carriers.csv` (use `--overwrite`). Ask first: it changes historical unauthorized counts.
4. **Run the job** (waits until it finishes):
   ```bash
   databricks jobs run-now 697967429732215 --profile DEFAULT
   ```
   With parameters, for example another month:
   ```bash
   databricks jobs run-now --json '{"job_id": 697967429732215, "job_parameters": {"report_month": "2026-11"}}' --profile DEFAULT
   ```
5. **Read the run summary** (the notebook's exit JSON). `get-run-output` takes the **task** run id, not the job run id:
   ```bash
   databricks jobs list-runs --job-id 697967429732215 --limit 1 --profile DEFAULT -o json
   ```
   ```bash
   databricks jobs get-run-output <TASK_RUN_ID> --profile DEFAULT -o json
   ```

### Dashboard

The dashboard reads gold through the warehouse, so it shows new data as soon as a job run finishes; it needs no refresh of its own. To change it, edit `tools/build_dashboard.py`, then rebuild the JSON and update the **same** dashboard. Never run `create` again, because that makes a new dashboard and URL. The body goes in a file because Windows rejects long command lines, and `--dataset-catalog` / `--dataset-schema` must be passed on every update:
```bash
.venv/Scripts/python tools/build_dashboard.py
```
```bash
.venv/Scripts/python -c "import json; d=json.load(open('src/serving/carrier_lane_scorecard.lvdash.json', encoding='utf-8')); json.dump({'serialized_dashboard': json.dumps(d)}, open('dashboard_update.json', 'w', encoding='utf-8'))"
```
```bash
databricks lakeview update 01f1e35942291816b926da78e98c569c --dataset-catalog workspace --dataset-schema default --json @dashboard_update.json --profile DEFAULT
```
```bash
databricks lakeview publish 01f1e35942291816b926da78e98c569c --warehouse-id 7dab9489683f6ff3 --profile DEFAULT
```

### Schedule

The job runs daily at 06:00 `America/New_York` and is **paused** for now. To unpause it (only with Lester's approval):
```bash
databricks jobs update 697967429732215 --json '{"new_settings": {"schedule": {"quartz_cron_expression": "0 0 6 * * ?", "timezone_id": "America/New_York", "pause_status": "UNPAUSED"}}}' --profile DEFAULT
```
To pause it again, run the same command with `"pause_status": "PAUSED"`. Also set `PAUSED` in the JSON file, so a later `reset` doesn't change it back.

## Service level

- **Data ready by:** 06:00 Eastern once unpaused; at most ~1 minute after the run starts.
- **Measured run time** (serverless, 2026-11-18): 50 s for a manual job run with no new files, 56 s with a new feed file, about 100 s for a failed run (2 attempts).
- **Freshness check:** none (out of scope).
- **Cost per run:** unknown. Look in `system.billing.usage` the day after a run; billing lags.

## Health checks

Run these in the SQL editor:

```sql
-- Rows per layer
SELECT 'bronze_loads' t, count(*) FROM workspace.default.bronze_loads
UNION ALL SELECT 'silver_loads', count(*) FROM workspace.default.silver_loads
UNION ALL SELECT 'gold_carrier_lane_scorecard', count(*) FROM workspace.default.gold_carrier_lane_scorecard;

-- Which files bronze has loaded, and when
SELECT _source_file, min(_ingested_at) AS ingested_at, count(*) AS rows
FROM workspace.default.bronze_loads GROUP BY _source_file ORDER BY ingested_at;

-- What the last silver MERGEs did
SELECT version, timestamp, operation,
       operationMetrics.numSourceRows, operationMetrics.numTargetRowsInserted, operationMetrics.numTargetRowsUpdated
FROM (DESCRIBE HISTORY workspace.default.silver_loads) ORDER BY version DESC LIMIT 5;

-- Is gold trusted? 'certified' only after all DQ checks passed; 'warn' means the last run failed its checks
SHOW TBLPROPERTIES workspace.default.gold_carrier_lane_scorecard ('quality');
```

The results of each check are in the run's "Data-quality checks" cell output; open the run from the [job page](https://dbc-c4cb7bbd-1462.cloud.databricks.com/jobs/697967429732215?o=7474656911982802).

## Alerts and first steps

| Alert | Means | First step |
|---|---|---|
| **Job failure email** (to lester.salango.pro@gmail.com) | The run failed after 1 retry: either a DQ check failed (an `AssertionError` that names the checks) or the code or a file broke. | Open the run and read the error. For DQ failures, see the table below. Gold keeps the previous data but is marked `quality = warn`. |
| **Duration warning email** | The run took more than 10 minutes (it normally takes ~1). | Check for a huge new file in `raw/` or a `reprocess_all_bronze=true` run. The job times out at 30 minutes. |

### What each data-quality failure means

| Check | Likely cause | First step |
|---|---|---|
| silver: one row per load_id | The MERGE source had duplicate keys, or someone wrote to silver by hand | Look at `DESCRIBE HISTORY` on silver; rerun with `reprocess_all_bronze=true` |
| silver: every bronze load is present and current | A batch was skipped or applied out of order | Rerun with `reprocess_all_bronze=true` |
| silver: no hand-typed DOT failed to parse | A new DOT format (for example `DOT# 123`) | Find the rows where `carrier_dot_raw` is not blank and `carrier_dot` is null; extend `clean_dot` in `src/` |
| silver: no required field is null or unparseable | A bad timestamp or rate in the feed | Find the null `pickup_ts_utc`, `last_modified_utc` or `customer_rate` in silver, then the raw row in bronze |
| silver: Delivered loads have a carrier and a cost | The TMS sent a Delivered load without a carrier or cost | Raise it with the TMS owner; the load stays out of a trusted gold |
| silver: status is one of the 5 known values | A new TMS status | Confirm the meaning with operations before adding it |
| gold: not empty | Wrong `report_month`, or no Delivered loads | Check the parameter |
| gold: one row per carrier x lane | One DOT has two legal names in FMCSA | Check `silver_fmcsa_carriers` for a duplicate `dot_number` |
| gold: … reconciles to silver | Join fan-out (FMCSA duplicates) or a filter mismatch | Same as above |
| gold: margin = revenue - cost on every row | Rounding or a type change | Check the decimal types in `src/` |
| gold: flagged loads never exceed load_count | Logic error in the flags | Review the gold cell |
| gold: legal_name blank only for unverified carriers | A blank `legal_name` in FMCSA | Check that carrier in `silver_fmcsa_carriers` |
| forced failure | `force_dq_failure=true` was passed | Expected during an email test; rerun without it |

## Recovery

- **Rerun:** safe at any time. Bronze skips loaded files, silver applies only newer versions, and gold is rebuilt.
- **Rebuild silver from bronze:** run with `reprocess_all_bronze=true`. It's idempotent: a rerun with no changes shows 0 inserted and 0 updated.
- **Backfill another month:** run with `report_month=YYYY-MM`. Gold holds **one month at a time** and is replaced, so rerun October afterwards if that is the month people read.
- **Full refresh** (drop and rebuild every table): ask Lester first. It's only needed if bronze is wrong, for example a corrected file was loaded under an old name.

## Known issues and limitations

- **Test feed, landed and then removed.** On 2026-11-18, `tools/new_feed/loads_2026-11-19.csv` was landed to test incremental loading: 1 cost correction, 1 new load, 1 stale version and 1 re-send. Expect 1 inserted and 1 updated; gold then has 1,367 loads and revenue of 4,007,430.61. It was then removed: the file was deleted from `raw/`, its 4 rows were deleted from bronze, and silver was set back with `RESTORE TABLE … TO VERSION AS OF 3`. Gold is back to the exercise totals of 1,366 loads and 4,004,780.61. To repeat the test, land the file again and run the job, then remove it the same way, restoring silver to the version before the test MERGE.
- **Batches can be read twice.** Silver's watermark is the newest bronze arrival time among the rows it *kept*. A batch that held only older versions is read again on the next run. That's harmless, because the MERGE ignores versions that aren't newer.
- **Blank legal names are nulls.** For unverified carriers, `legal_name` is null rather than an empty string.
- **The job always runs October by default.** `report_month` defaults to `2026-10`. A real daily schedule would derive the month from the run date.
- **COPY INTO keys on the file path.** A corrected file landed under an existing name is not reloaded.
- **No freshness check and no prod target.**

## How to remove everything (not run; ask first)

```bash
databricks lakeview trash 01f1e35942291816b926da78e98c569c --profile DEFAULT
```
```bash
databricks jobs delete 697967429732215 --profile DEFAULT
```
```bash
databricks tables delete workspace.default.gold_carrier_lane_scorecard --profile DEFAULT
```
```bash
databricks tables delete workspace.default.silver_loads --profile DEFAULT
```
```bash
databricks tables delete workspace.default.silver_fmcsa_carriers --profile DEFAULT
```
```bash
databricks tables delete workspace.default.bronze_loads --profile DEFAULT
```
```bash
databricks tables delete workspace.default.bronze_fmcsa_carriers --profile DEFAULT
```
```bash
databricks fs rm -r dbfs:/Volumes/workspace/default/interview/raw --profile DEFAULT
```
```bash
databricks workspace delete "/Users/lester.salango.pro@gmail.com/carrier_lane_scorecard" --profile DEFAULT
```
