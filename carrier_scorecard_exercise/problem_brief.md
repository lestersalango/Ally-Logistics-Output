# Exercise: Carrier Lane Scorecard

**Time:** 35 minutes  ·  **Tools:** Databricks (Python / PySpark). Any AI assistant is welcome.

## Context

We are a freight brokerage. Every truckload we book is a **load**: a customer pays us to move freight from one place to another, and we pay a **carrier** (trucking company) to haul it. The difference between the two is our margin.

Our TMS sends load records to the data platform as a change feed. The government publishes a census of carriers (FMCSA) that tells us whether each carrier is legally authorized to operate.

The operations team wants a **carrier lane scorecard for October 2026**: for each carrier and lane, how many loads it hauled, what margin we made, and whether it hauled any loads while it was not authorized.

## Files

| File | What it is |
|---|---|
| `data/loads.csv` | Load records from the TMS change feed |
| `data/fmcsa_carriers.csv` | FMCSA carrier census snapshot |
| `data_dictionary.md` | Field definitions and business rules. **Read this.** |

## Your task

Build this in a Databricks notebook using a medallion layout. Get as far as you can; we don't expect everyone to finish every step.

1. **Bronze:** load both files into Delta tables as-is.
2. **Silver:** produce a clean table with **one row per load**, in its current state, with fields typed and standardized.
3. **Gold:** produce `gold_carrier_lane_scorecard` with one row per **carrier × lane** (lane = origin state → destination state), covering **Delivered** loads with a pickup date in **October 2026**. Columns:

   | Column | Meaning |
   |---|---|
   | `carrier_dot` | Carrier's USDOT number |
   | `legal_name` | From FMCSA (blank if the carrier isn't in the FMCSA file) |
   | `origin_state`, `dest_state` | The lane |
   | `load_count` | Number of loads |
   | `total_revenue` | Sum of revenue |
   | `total_carrier_cost` | Sum of carrier cost |
   | `gross_margin` | Sum of gross margin |
   | `margin_pct` | `gross_margin / total_revenue` |
   | `unauthorized_load_count` | Loads hauled while the carrier was not authorized |
   | `unverified_load_count` | Loads whose carrier isn't in the FMCSA file |

4. **Stretch** (pick any):
   - Add data-quality checks that would fail the pipeline if something is wrong.
   - Make the silver step incremental (`MERGE`) so it can run again tomorrow on new change-feed rows.
   - Describe how you would schedule and monitor this in production.

## What we're looking for

- Correct numbers. Check your own work and your AI's work.
- Clear, readable code that someone else could run.
- Talk us through what you're doing and why, including when you disagree with the AI.

When time is up you'll walk us through your notebook and your final totals.
