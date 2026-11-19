# Databricks notebook source
# MAGIC %md
# MAGIC # Carrier Lane Scorecard — October 2026
# MAGIC
# MAGIC **Goal:** for each carrier × lane (origin state → destination state), count the Delivered loads picked up in
# MAGIC October 2026 (Eastern time), the revenue, cost and margin we made, and how many loads were hauled while the
# MAGIC carrier was not authorized or can't be found in FMCSA.
# MAGIC
# MAGIC **Layout (medallion):**
# MAGIC | Layer | Table | What it holds |
# MAGIC |---|---|---|
# MAGIC | Bronze | `bronze_loads`, `bronze_fmcsa_carriers` | The CSVs as-is, all strings, plus source file and load time |
# MAGIC | Silver | `silver_loads`, `silver_fmcsa_carriers` | Typed, cleaned, **one row per load** in its current state |
# MAGIC | Gold | `gold_carrier_lane_scorecard` | One row per carrier × lane for the report month |
# MAGIC
# MAGIC **Safe to rerun:** bronze only loads files it hasn't seen (`COPY INTO`), silver only applies newer versions
# MAGIC (`MERGE`), gold is rebuilt from silver. Data-quality checks at the end fail the run if anything is off.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Parameters
# MAGIC Catalog, schema, landing volume and report month are widgets, so the same notebook runs in another catalog,
# MAGIC for another month, or as a job without code changes. Nothing below this cell hard-codes a location.
# MAGIC - `reprocess_all_bronze`: re-MERGE every bronze row into silver (recovery, and to prove the MERGE is idempotent).
# MAGIC - `force_dq_failure`: adds one failing check on purpose, to test the failure email.

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("schema", "default")
dbutils.widgets.text("volume", "interview")
dbutils.widgets.text("report_month", "2026-10")
dbutils.widgets.dropdown("reprocess_all_bronze", "false", ["false", "true"])
dbutils.widgets.dropdown("force_dq_failure", "false", ["false", "true"])

CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")
VOLUME = dbutils.widgets.get("volume")
REPORT_MONTH = dbutils.widgets.get("report_month")              # 'YYYY-MM'
REPROCESS_ALL_BRONZE = dbutils.widgets.get("reprocess_all_bronze") == "true"
FORCE_DQ_FAILURE = dbutils.widgets.get("force_dq_failure") == "true"

RAW_DIR = f"/Volumes/{CATALOG}/{SCHEMA}/{VOLUME}/raw"
LOADS_CSV = f"{RAW_DIR}/loads.csv"
FMCSA_CSV = f"{RAW_DIR}/fmcsa_carriers.csv"

def table(name: str) -> str:
    """Fully qualified table name in the target catalog and schema."""
    return f"{CATALOG}.{SCHEMA}.{name}"

REPORT_TZ = "America/New_York"   # business rule 2: reporting runs on US Eastern time
spark.conf.set("spark.sql.session.timeZone", "UTC")  # all raw timestamps are UTC; convert to ET explicitly
print(f"Reading from {RAW_DIR}, writing to {CATALOG}.{SCHEMA}, report month {REPORT_MONTH}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Shared cleaning rules
# MAGIC Defined once and used by both the profiling and silver. `try_cast` returns null instead of crashing on a bad
# MAGIC value, so a bad value is caught by the data-quality checks rather than silently changing the numbers.

# COMMAND ----------

from pyspark.sql import functions as F
from pyspark.sql.window import Window

MONEY = "DECIMAL(12,2)"   # exact money, never float

def clean_dot(col_name: str):
    """'USDOT 0123456 ' -> 123456 (BIGINT) ; blank -> null ; unparseable -> null (caught by DQ)."""
    return F.expr(f"try_cast(nullif(trim(regexp_replace({col_name}, '(?i)usdot', '')), '') AS BIGINT)")

def money(col_name: str):
    return F.expr(f"try_cast(nullif(trim({col_name}), '') AS {MONEY})")

def utc_ts(col_name: str):
    return F.expr(f"try_to_timestamp({col_name})")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Check the landed files
# MAGIC Fail fast if a file is missing, before any table is touched.

# COMMAND ----------

landed = {f.name: f.size for f in dbutils.fs.ls(RAW_DIR)}
display(spark.createDataFrame(list(landed.items()), "file string, bytes long"))
for required in ("loads.csv", "fmcsa_carriers.csv"):
    assert required in landed, f"Missing landed file: {RAW_DIR}/{required}"

# COMMAND ----------

# MAGIC %md
# MAGIC ## Profile the raw data
# MAGIC Before writing any transformation, look at what the data actually does. The data dictionary warns about
# MAGIC re-sends, hand-typed DOT numbers and UTC timestamps; these cells measure each one so the silver rules are
# MAGIC based on evidence, not guesses. Everything is read as **strings** so nothing is silently cast or dropped.

# COMMAND ----------

raw_loads = (spark.read.option("header", True).option("inferSchema", False).csv(LOADS_CSV)
             .withColumn("_file_row", F.monotonically_increasing_id()))   # position in the file (one small file → one partition)
raw_fmcsa = spark.read.option("header", True).option("inferSchema", False).csv(FMCSA_CSV)

profile = {}

# COMMAND ----------

# MAGIC %md
# MAGIC ### 1. A load appears many times
# MAGIC The feed re-sends the full record on every change, and sometimes re-sends the same version twice.
# MAGIC So the file has far more rows than loads, and silver must keep only the **latest** version of each load.

# COMMAND ----------

data_cols = [c for c in raw_loads.columns if c != "_file_row"]
versions = raw_loads.groupBy("load_id").agg(F.count("*").alias("versions"))

profile["raw_rows"] = raw_loads.count()
profile["distinct_loads"] = versions.count()
profile["exact_duplicate_rows"] = profile["raw_rows"] - raw_loads.select(data_cols).distinct().count()
profile["loads_with_tied_latest"] = (raw_loads
    .withColumn("max_lm", F.max("last_modified").over(Window.partitionBy("load_id")))
    .where("last_modified = max_lm").groupBy("load_id").count().where("count > 1").count())

display(versions.groupBy("versions").count().orderBy("versions"))
print({k: profile[k] for k in ("raw_rows", "distinct_loads", "exact_duplicate_rows", "loads_with_tied_latest")})

# COMMAND ----------

# MAGIC %md
# MAGIC ### 2. File order is not time order
# MAGIC "Keep the last row I see" would be wrong: for many loads the last row in the file is an **older** version.
# MAGIC Silver must order by `last_modified`, never by position.

# COMMAND ----------

by_position = Window.partitionBy("load_id").orderBy(F.col("_file_row").desc())
last_in_file = raw_loads.withColumn("rn", F.row_number().over(by_position)).where("rn = 1") \
                        .select("load_id", F.col("last_modified").alias("last_in_file_lm"))
latest = raw_loads.groupBy("load_id").agg(F.max("last_modified").alias("latest_lm"))
out_of_order = last_in_file.join(latest, "load_id").where("last_in_file_lm <> latest_lm")
profile["loads_last_row_not_latest"] = out_of_order.count()
print(f"Loads whose last row in the file is NOT the newest version: {profile['loads_last_row_not_latest']}")

example = out_of_order.orderBy("load_id").first()["load_id"]
display(raw_loads.where(F.col("load_id") == example)
        .select("_file_row", "load_id", "status", "carrier_cost", "last_modified").orderBy("_file_row"))

# COMMAND ----------

# MAGIC %md
# MAGIC ### 3. DOT numbers are typed by hand
# MAGIC Each DOT is shown as a "shape" (digits → `9`). Leading zeros, padding spaces and a `USDOT` prefix all appear.
# MAGIC Comparing the raw text with FMCSA misses many real matches; stripping `USDOT`, trimming and casting to a
# MAGIC number fixes it.

# COMMAND ----------

display(raw_loads.select(F.regexp_replace(F.coalesce("carrier_dot", F.lit("<blank>")), "[0-9]", "9").alias("dot_shape"))
        .groupBy("dot_shape").count().orderBy(F.desc("count")))

fmcsa_dots_text = raw_fmcsa.select(F.col("dot_number").alias("dot_text"))
fmcsa_dots_num = raw_fmcsa.select(clean_dot("dot_number").alias("dot_num"))
with_dot = raw_loads.where(F.trim(F.coalesce("carrier_dot", F.lit(""))) != "")
profile["rows_with_dot"] = with_dot.count()
profile["rows_matching_fmcsa_raw_text"] = with_dot.join(fmcsa_dots_text, F.col("carrier_dot") == F.col("dot_text")).count()
profile["rows_matching_fmcsa_cleaned"] = with_dot.join(fmcsa_dots_num, clean_dot("carrier_dot") == F.col("dot_num")).count()
profile["rows_dot_unparseable"] = with_dot.where(clean_dot("carrier_dot").isNull()).count()
print({k: profile[k] for k in ("rows_with_dot", "rows_matching_fmcsa_raw_text", "rows_matching_fmcsa_cleaned", "rows_dot_unparseable")})

# COMMAND ----------

# MAGIC %md
# MAGIC ### 4. Pickup time is UTC, reporting is Eastern
# MAGIC A pickup at `2026-11-01T02:52Z` is **Oct 31, 10:52 pm** in New York, so it belongs to October.
# MAGIC Filtering on the UTC date gives a different set of loads. Measured on the current version of Delivered loads.

# COMMAND ----------

by_time = Window.partitionBy("load_id").orderBy(F.col("last_modified").desc())
current = (raw_loads.withColumn("rn", F.row_number().over(by_time))
           .where("rn = 1").where("status = 'Delivered'")
           .withColumn("pickup_utc", utc_ts("pickup_ts"))
           .withColumn("pickup_date_utc", F.to_date("pickup_utc"))
           .withColumn("pickup_date_et", F.to_date(F.from_utc_timestamp("pickup_utc", REPORT_TZ))))

in_oct = lambda c: F.col(c).between("2026-10-01", "2026-10-31")
oct_counts = current.agg(
    F.sum(in_oct("pickup_date_utc").cast("int")).alias("october_by_utc_date"),
    F.sum(in_oct("pickup_date_et").cast("int")).alias("october_by_et_date"),
    F.sum((in_oct("pickup_date_et") & ~in_oct("pickup_date_utc")).cast("int")).alias("only_in_et"),
    F.sum((in_oct("pickup_date_utc") & ~in_oct("pickup_date_et")).cast("int")).alias("only_in_utc"),
).first().asDict()
profile.update(oct_counts)
print(oct_counts)
display(current.where(in_oct("pickup_date_et") != in_oct("pickup_date_utc"))
        .select("load_id", "pickup_ts", "pickup_date_utc", "pickup_date_et").orderBy("pickup_ts"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Bronze — land the files as-is
# MAGIC
# MAGIC **Loads:** `COPY INTO` appends every `loads*.csv` file in the landing folder **once**. It remembers which
# MAGIC files it already loaded, so a rerun loads nothing new, and tomorrow's file (`loads_2026-11-19.csv`) is
# MAGIC picked up on its own. Every column stays a string, and we add which file the row came from and when it arrived.
# MAGIC
# MAGIC **FMCSA:** a full census snapshot, so each run replaces the bronze copy.

# COMMAND ----------

LOAD_COLS = ["load_id", "status", "carrier_dot", "origin_city", "origin_state", "dest_city", "dest_state",
             "pickup_ts", "customer_rate", "accessorial_revenue", "carrier_cost", "margin", "last_modified"]

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {table('bronze_loads')} (
  {', '.join(f'{c} STRING' for c in LOAD_COLS)},
  _source_file STRING, _ingested_at TIMESTAMP)
COMMENT 'Raw TMS load change feed as received: every column a string, one row per record sent (versions and re-sends kept).'
""")

copy_result = spark.sql(f"""
COPY INTO {table('bronze_loads')}
FROM (SELECT {', '.join(LOAD_COLS)}, _metadata.file_path AS _source_file, current_timestamp() AS _ingested_at
      FROM '{RAW_DIR}')
FILEFORMAT = CSV
PATTERN = 'loads*.csv'
FORMAT_OPTIONS ('header' = 'true', 'inferSchema' = 'false')
""").first().asDict()
print("COPY INTO bronze_loads:", copy_result)

(spark.read.option("header", True).option("inferSchema", False).csv(FMCSA_CSV)
 .select("*", F.col("_metadata.file_path").alias("_source_file"), F.current_timestamp().alias("_ingested_at"))
 .write.mode("overwrite").option("overwriteSchema", True).saveAsTable(table("bronze_fmcsa_carriers")))
spark.sql(f"COMMENT ON TABLE {table('bronze_fmcsa_carriers')} IS 'Raw FMCSA census snapshot as received, all strings; replaced on every run.'")

display(spark.sql(f"""
SELECT 'bronze_loads' AS table_name, count(*) AS row_count FROM {table('bronze_loads')}
UNION ALL SELECT 'bronze_fmcsa_carriers', count(*) FROM {table('bronze_fmcsa_carriers')}"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Silver — FMCSA carriers
# MAGIC Typed: DOT as a number (same cleaning as the loads, so the join keys match), status upper-cased, date as a date.

# COMMAND ----------

(spark.table(table("bronze_fmcsa_carriers"))
 .select(clean_dot("dot_number").alias("dot_number"),
         F.trim("legal_name").alias("legal_name"),
         F.upper(F.trim("authority_status")).alias("authority_status"),
         F.expr("try_to_date(status_date)").alias("status_date"),
         "_source_file", "_ingested_at")
 .write.mode("overwrite").option("overwriteSchema", True).saveAsTable(table("silver_fmcsa_carriers")))
spark.sql(f"COMMENT ON TABLE {table('silver_fmcsa_carriers')} IS 'FMCSA carrier census, typed; one row per USDOT number.'")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Silver — loads, one row per load (incremental `MERGE`)
# MAGIC
# MAGIC 1. **Standardize** each bronze row: trim text, clean the DOT, type money as decimals (blank accessorial = 0),
# MAGIC    parse UTC timestamps and add the **Eastern** pickup date. Revenue and gross margin follow business rules 3–4;
# MAGIC    the legacy `margin` column is dropped because it leaves out accessorials.
# MAGIC 2. **New rows only:** take bronze rows that arrived after the newest one silver has already seen.
# MAGIC 3. **Latest version per load** within that batch: order by `last_modified`, never by file position.
# MAGIC    Ties are exact re-sends; a hash of the row is the last tie-breaker so the pick is deterministic.
# MAGIC 4. **MERGE:** insert new loads; update an existing load only if the incoming version is **newer**.
# MAGIC    An older or repeated version can never overwrite a newer one, so the order the feed arrives in doesn't matter.

# COMMAND ----------

from delta.tables import DeltaTable

def standardize_loads(bronze_df):
    rev = f"DECIMAL(14,2)"
    return (bronze_df.select(
                F.trim("load_id").alias("load_id"),
                F.initcap(F.lower(F.trim("status"))).alias("status"),
                F.col("carrier_dot").alias("carrier_dot_raw"),
                clean_dot("carrier_dot").alias("carrier_dot"),
                F.trim("origin_city").alias("origin_city"),
                F.upper(F.trim("origin_state")).alias("origin_state"),
                F.trim("dest_city").alias("dest_city"),
                F.upper(F.trim("dest_state")).alias("dest_state"),
                utc_ts("pickup_ts").alias("pickup_ts_utc"),
                F.to_date(F.from_utc_timestamp(utc_ts("pickup_ts"), REPORT_TZ)).alias("pickup_date_et"),
                money("customer_rate").alias("customer_rate"),
                F.coalesce(money("accessorial_revenue"), F.lit(0).cast(MONEY)).alias("accessorial_revenue"),
                money("carrier_cost").alias("carrier_cost"),
                utc_ts("last_modified").alias("last_modified_utc"),
                "_source_file",
                F.col("_ingested_at").alias("_bronze_ingested_at"),
                F.xxhash64(*LOAD_COLS).alias("_row_hash"))
            .withColumn("revenue", (F.col("customer_rate") + F.col("accessorial_revenue")).cast(rev))
            .withColumn("gross_margin", (F.col("revenue") - F.col("carrier_cost")).cast(rev)))

silver_name = table("silver_loads")
bronze = spark.table(table("bronze_loads"))

if not spark.catalog.tableExists(silver_name):
    standardize_loads(bronze).limit(0).drop("_row_hash").write.saveAsTable(silver_name)
    spark.sql(f"COMMENT ON TABLE {silver_name} IS 'TMS loads in their current state: one row per load_id, latest last_modified wins. Typed and standardized.'")

watermark = spark.table(silver_name).agg(F.max("_bronze_ingested_at")).first()[0]
batch = bronze if (REPROCESS_ALL_BRONZE or watermark is None) else bronze.where(F.col("_ingested_at") > F.lit(watermark))

latest_first = Window.partitionBy("load_id").orderBy(
    F.col("last_modified_utc").desc(), F.col("_bronze_ingested_at").desc(), F.col("_row_hash").desc())
incoming = (standardize_loads(batch)
            .withColumn("_rn", F.row_number().over(latest_first))
            .where("_rn = 1").drop("_rn", "_row_hash"))

incoming_rows = incoming.count()
print(f"Watermark: {watermark} | reprocess_all_bronze={REPROCESS_ALL_BRONZE} | loads in this batch: {incoming_rows}")

merge_metrics = {"skipped": True}
if incoming_rows:
    (DeltaTable.forName(spark, silver_name).alias("t")
     .merge(incoming.alias("s"), "t.load_id = s.load_id")
     .whenMatchedUpdateAll(condition="s.last_modified_utc > t.last_modified_utc")
     .whenNotMatchedInsertAll()
     .execute())
    last_op = spark.sql(f"DESCRIBE HISTORY {silver_name} LIMIT 1").first()
    m = last_op["operationMetrics"]
    merge_metrics = {"version": last_op["version"], "source_rows": int(m["numSourceRows"]),
                     "inserted": int(m["numTargetRowsInserted"]), "updated": int(m["numTargetRowsUpdated"])}
print("MERGE silver_loads:", merge_metrics)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Gold — carrier lane scorecard
# MAGIC - **Scope:** current state `Delivered`, pickup date **in Eastern time** within the report month.
# MAGIC - **Unverified:** the carrier's DOT isn't in FMCSA (LEFT join, keep the load, `legal_name` stays blank).
# MAGIC - **Unauthorized:** carrier is `REVOKED`/`INACTIVE` **and** that status took effect on or before the pickup date.
# MAGIC   A carrier revoked after the pickup was authorized when it hauled the load.
# MAGIC - **margin_pct** is a ratio of the sums, not an average of per-load percentages.

# COMMAND ----------

month_start = F.to_date(F.lit(f"{REPORT_MONTH}-01"))
loads = (spark.table(silver_name)
         .where((F.col("status") == "Delivered") &
                F.col("pickup_date_et").between(month_start, F.last_day(month_start))))
carriers = spark.table(table("silver_fmcsa_carriers"))

flagged = (loads.join(carriers, loads.carrier_dot == carriers.dot_number, "left")
           .withColumn("is_unverified", F.col("dot_number").isNull())
           .withColumn("is_unauthorized",
                       ~F.col("is_unverified")
                       & F.col("authority_status").isin("REVOKED", "INACTIVE")
                       & (F.col("status_date") <= F.col("pickup_date_et"))))

AMOUNT = "DECIMAL(18,2)"
gold = (flagged.groupBy("carrier_dot", "origin_state", "dest_state")
        .agg(F.max("legal_name").alias("legal_name"),            # one name per DOT; null when unverified
             F.count("*").alias("load_count"),
             F.sum("revenue").cast(AMOUNT).alias("total_revenue"),
             F.sum("carrier_cost").cast(AMOUNT).alias("total_carrier_cost"),
             F.sum("gross_margin").cast(AMOUNT).alias("gross_margin"),
             F.sum(F.col("is_unauthorized").cast("int")).alias("unauthorized_load_count"),
             F.sum(F.col("is_unverified").cast("int")).alias("unverified_load_count"))
        .withColumn("margin_pct", F.expr("try_divide(gross_margin, total_revenue)").cast("DECIMAL(9,4)"))
        .select("carrier_dot", "legal_name", "origin_state", "dest_state", "load_count", "total_revenue",
                "total_carrier_cost", "gross_margin", "margin_pct", "unauthorized_load_count", "unverified_load_count"))

gold_name = table("gold_carrier_lane_scorecard")
gold.write.mode("overwrite").option("overwriteSchema", True).saveAsTable(gold_name)
spark.sql(f"""COMMENT ON TABLE {gold_name} IS
  'Carrier x lane (origin state -> destination state) scorecard for Delivered loads picked up in {REPORT_MONTH} (US Eastern). One row per carrier_dot, origin_state, dest_state.'""")
spark.sql(f"ALTER TABLE {gold_name} SET TBLPROPERTIES ('quality' = 'warn', 'report_month' = '{REPORT_MONTH}')")
display(spark.table(gold_name).orderBy(F.desc("load_count")))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Data-quality checks
# MAGIC Every check runs, the results are shown as a table, and then the run **fails** if any check failed, so a job
# MAGIC sends the failure email. The gold table is marked `quality = certified` only when all checks pass.

# COMMAND ----------

silver = spark.table(silver_name)
bronze = spark.table(table("bronze_loads"))
gold_t = spark.table(gold_name)

s = silver.agg(
    F.count("*").alias("rows"), F.countDistinct("load_id").alias("ids"),
    F.sum((F.trim(F.coalesce("carrier_dot_raw", F.lit(""))) != "").cast("int")
          * F.col("carrier_dot").isNull().cast("int")).alias("dot_unparsed"),
    F.sum((F.col("pickup_ts_utc").isNull() | F.col("last_modified_utc").isNull()
           | F.col("customer_rate").isNull()).cast("int")).alias("required_null"),
    F.sum(((F.col("status") == "Delivered") & (F.col("carrier_dot").isNull() | F.col("carrier_cost").isNull())).cast("int")).alias("delivered_missing_carrier"),
    F.sum((~F.col("status").isin("Open", "Covered", "In Transit", "Delivered", "Cancelled")).cast("int")).alias("bad_status"),
).first()

bronze_latest = bronze.groupBy(F.trim("load_id").alias("load_id")).agg(F.max(utc_ts("last_modified")).alias("lm"))
not_current = (bronze_latest.join(silver.select("load_id", "last_modified_utc"), "load_id", "full")
               .where(~F.col("lm").eqNullSafe(F.col("last_modified_utc"))).count())

expected = loads.agg(F.count("*").alias("n"), F.sum("revenue").alias("rev"),
                     F.sum("carrier_cost").alias("cost"), F.sum("gross_margin").alias("margin")).first()
g = gold_t.agg(F.count("*").alias("rows"),
               F.countDistinct("carrier_dot", "origin_state", "dest_state").alias("keys"),
               F.sum("load_count").alias("n"), F.sum("total_revenue").alias("rev"),
               F.sum("total_carrier_cost").alias("cost"), F.sum("gross_margin").alias("margin"),
               F.sum("unauthorized_load_count").alias("unauth"), F.sum("unverified_load_count").alias("unverified"),
               F.sum(((F.col("unauthorized_load_count") + F.col("unverified_load_count")) > F.col("load_count")).cast("int")).alias("flags_over_count"),
               F.sum((F.col("legal_name").isNull() != (F.col("unverified_load_count") == F.col("load_count"))).cast("int")).alias("name_vs_unverified"),
               F.sum((F.col("gross_margin") != F.col("total_revenue") - F.col("total_carrier_cost")).cast("int")).alias("margin_mismatch"),
               ).first()

checks = {
    "silver: one row per load_id":                         s["rows"] == s["ids"],
    "silver: every bronze load is present and current":    not_current == 0,
    "silver: no hand-typed DOT failed to parse":           s["dot_unparsed"] == 0,
    "silver: no required field is null or unparseable":    s["required_null"] == 0,
    "silver: Delivered loads have a carrier and a cost":   s["delivered_missing_carrier"] == 0,
    "silver: status is one of the 5 known values":         s["bad_status"] == 0,
    "gold: not empty":                                     g["rows"] > 0,
    "gold: one row per carrier x lane":                    g["rows"] == g["keys"],
    "gold: load_count reconciles to silver":               g["n"] == expected["n"],
    "gold: revenue reconciles to silver":                  g["rev"] == expected["rev"],
    "gold: carrier cost reconciles to silver":             g["cost"] == expected["cost"],
    "gold: margin reconciles to silver":                   g["margin"] == expected["margin"],
    "gold: margin = revenue - cost on every row":          g["margin_mismatch"] == 0,
    "gold: flagged loads never exceed load_count":         g["flags_over_count"] == 0,
    "gold: legal_name blank only for unverified carriers": g["name_vs_unverified"] == 0,
}
if FORCE_DQ_FAILURE:
    checks["forced failure (force_dq_failure = true)"] = False

display(spark.createDataFrame([(k, v) for k, v in checks.items()], "check string, passed boolean"))
failed = [k for k, v in checks.items() if not v]
if failed:
    raise AssertionError(f"{len(failed)} data-quality check(s) failed: {failed}")

spark.sql(f"ALTER TABLE {gold_name} SET TBLPROPERTIES ('quality' = 'certified')")
print(f"All {len(checks)} checks passed; {gold_name} marked certified.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Run summary
# MAGIC The last cell returns a small JSON summary, so a job run (or the CLI) can read the result.

# COMMAND ----------

import json

summary = {
    "report_month": REPORT_MONTH,
    "profile": profile,
    "bronze_copy_into": {k: int(v) for k, v in copy_result.items()},
    "bronze_loads_rows": bronze.count(),
    "silver_loads_rows": s["rows"],
    "silver_merge": merge_metrics,
    "gold": {"rows": g["rows"], "load_count": g["n"], "total_revenue": str(g["rev"]),
             "total_carrier_cost": str(g["cost"]), "gross_margin": str(g["margin"]),
             "margin_pct": str(round(g["margin"] / g["rev"], 4)),
             "unauthorized_load_count": g["unauth"], "unverified_load_count": g["unverified"]},
    "dq_checks_passed": len(checks),
}
print(json.dumps(summary, indent=2, default=str))
dbutils.notebook.exit(json.dumps(summary, default=str))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Interview talking points
# MAGIC
# MAGIC ### Final totals (October 2026, US Eastern pickup date, Delivered)
# MAGIC | Gold rows | Loads | Revenue | Carrier cost | Gross margin | Margin % | Unauthorized | Unverified |
# MAGIC |---|---|---|---|---|---|---|---|
# MAGIC | 758 | 1,366 | 4,004,780.61 | 3,360,830.64 | 643,949.97 | 16.08 % | 154 | 20 |
# MAGIC
# MAGIC Checked twice: this notebook (PySpark), and a separate plain-Python script that applies the data dictionary's
# MAGIC rules on its own (`tools/reference_totals.py`). Both give the same numbers to the cent.
# MAGIC
# MAGIC ### 30-second walkthrough
# MAGIC 1. **Profile first.** I measured the traps before writing transformations, so every rule rests on evidence.
# MAGIC 2. **Bronze = as received.** Strings only, plus the source file and arrival time. `COPY INTO` loads each file once.
# MAGIC 3. **Silver = one row per load, current state.** Typed and cleaned. An incremental `MERGE` only applies a version
# MAGIC    that is *newer* than what we have, so late or re-sent records can't overwrite good data.
# MAGIC 4. **Gold = the scorecard**, rebuilt from silver: LEFT join to FMCSA, flag each load, then aggregate.
# MAGIC 5. **Data-quality checks fail the run** (and email me). Gold is marked `certified` only when they all pass.
# MAGIC
# MAGIC ### The traps, and why each choice
# MAGIC | # | Trap in the data | What I did | Why |
# MAGIC |---|---|---|---|
# MAGIC | 1 | 3,200 rows but 1,800 loads; 62 exact re-sends | Latest `last_modified` per `load_id` | Business rule 1: current state = latest version |
# MAGIC | 2 | For 445 loads, the last row in the file is an **older** version | Order by `last_modified`, never file position | The feed is unordered |
# MAGIC | 3 | 135 loads had cost corrected after delivery | Latest version wins | Corrections must reach the margin |
# MAGIC | 4 | DOT typed by hand: `USDOT 123`, `00983756`, spaces | Strip `USDOT`, trim, cast to BIGINT | Raw text matched only 1,158 of 2,390 rows to FMCSA; cleaned, 2,351 |
# MAGIC | 5 | `pickup_ts` is UTC, reporting is Eastern | `from_utc_timestamp(..., 'America/New_York')` then date | UTC dates give 1,358 loads, not 1,366 (19 in, 11 out) |
# MAGIC | 6 | Unauthorized must compare dates in ET; 9 loads have status date = pickup date | `status_date <= pickup_date_et` | Rule 5 says "on or before"; one load flips if UTC is used |
# MAGIC | 7 | 147 loads use a carrier revoked **after** the pickup | Not flagged | The carrier was authorized when it hauled |
# MAGIC | 8 | Legacy `margin` leaves out accessorials (554K vs 644K) | Ignore it; revenue = rate + accessorials | Data dictionary says don't use it |
# MAGIC | 9 | Blank accessorial on 1,217 rows | `coalesce(..., 0)` | Otherwise revenue becomes null and drops out of the sums |
# MAGIC | 10 | 20 loads have a DOT not in FMCSA | LEFT join, keep them, blank name | Rule 6: keep them in the scorecard |
# MAGIC | 11 | `margin_pct` | Sum of margin ÷ sum of revenue | An average of per-load % weights small loads like big ones |
# MAGIC | 12 | Status must come from the current version | Deduplicate **then** filter Delivered | A Delivered-then-Cancelled load must drop out |
# MAGIC
# MAGIC ### Where an AI assistant typically gets it wrong (and I checked)
# MAGIC - **#2:** `dropDuplicates(["load_id"])` or "keep last row" — keeps an arbitrary or old version.
# MAGIC - **#4:** joins the DOT as text, or casts without stripping `USDOT`; loads silently become "unverified".
# MAGIC - **#5:** filters `pickup_ts` on UTC dates, or uses a fixed `-4h` offset instead of the time-zone name.
# MAGIC - **#8:** sums the existing `margin` column because it's already there.
# MAGIC
# MAGIC ### Incremental and idempotent: proven
# MAGIC - Rerun with no new files: bronze loads 0 rows and silver skips the MERGE.
# MAGIC - Re-MERGE all 1,800 loads: **0 inserted, 0 updated**.
# MAGIC - A test feed (cost correction, new load, stale older version, exact re-send) gave 1 insert and 1 update. The
# MAGIC   stale version was ignored, and the new load picked up at Nov 1 03:30 UTC counted in **October** (Eastern).
# MAGIC   It was then removed with `DELETE` on bronze and `RESTORE TABLE ... TO VERSION AS OF` on silver (Delta time travel).
# MAGIC
# MAGIC ### Production: schedule and monitoring
# MAGIC - Lakeflow job on serverless, daily 06:00 Eastern, 1 retry, 30-min timeout, `max_concurrent_runs = 1`
# MAGIC   (two MERGEs never race).
# MAGIC - Emails on failure and when a run takes longer than 10 minutes (it normally takes ~1 minute).
# MAGIC - DQ failure → the run fails → email. Gold stays `quality = warn` until a clean run.
# MAGIC
# MAGIC ### Trade-offs I'd mention (what I'd change at scale)
# MAGIC - **Lakeflow Declarative Pipelines:** Auto Loader for bronze, `AUTO CDC ... SEQUENCE BY last_modified` for silver
# MAGIC   (it handles out-of-order changes natively), expectations instead of asserts, and a materialized view for gold.
# MAGIC - **Watermark:** silver re-reads a batch that held only older versions; harmless because the MERGE ignores them.
# MAGIC   With Change Data Feed or streaming checkpoints it would read each row exactly once.
# MAGIC - **FMCSA history:** we only have the current snapshot. If a carrier was revoked and later reinstated, we can't
# MAGIC   see that it was revoked in between. Keeping each snapshot (SCD Type 2) would fix that.
# MAGIC - **Gold holds one month.** For a daily schedule, derive `report_month` from the run date or partition gold by month.
