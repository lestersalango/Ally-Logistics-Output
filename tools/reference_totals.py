"""Independent check of the gold totals, in plain Python (no Spark).

Run from the project root:
    .venv/Scripts/python tools/reference_totals.py [extra_loads.csv ...]

Extra change-feed files (e.g. tools/new_feed/loads_2026-11-19.csv) are added to loads.csv.

Implements the business rules in carrier_scorecard_exercise/data_dictionary.md
so the notebook's numbers can be checked against a second implementation.
"""
import csv
import sys
import re
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

DATA = Path(__file__).resolve().parents[1] / "carrier_scorecard_exercise" / "data"
ET = ZoneInfo("America/New_York")
OCT_START, OCT_END = date(2026, 10, 1), date(2026, 10, 31)


def read(name):
    with open(DATA / name if not Path(name).is_absolute() and not Path(name).exists() else name,
              encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def clean_dot(raw):
    s = re.sub(r"(?i)usdot", "", raw or "").strip()
    return int(s) if s else None


def utc(ts):
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def money(v):
    return Decimal(v) if v and v.strip() else Decimal("0")


def main():
    loads = read("loads.csv") + [r for extra in sys.argv[1:] for r in read(extra)]
    fmcsa = {int(r["dot_number"]): r for r in read("fmcsa_carriers.csv")}

    # Rule 1: current state = latest last_modified (string compare is safe: fixed ISO format).
    current = {}
    for r in loads:
        k = r["load_id"]
        if k not in current or r["last_modified"] > current[k]["last_modified"]:
            current[k] = r

    gold = defaultdict(lambda: dict(load_count=0, total_revenue=Decimal(0), total_carrier_cost=Decimal(0),
                                    unauthorized_load_count=0, unverified_load_count=0))
    for r in current.values():
        if r["status"] != "Delivered":
            continue
        pickup_date_et = utc(r["pickup_ts"]).astimezone(ET).date()  # Rule 2
        if not (OCT_START <= pickup_date_et <= OCT_END):
            continue
        dot = clean_dot(r["carrier_dot"])
        g = gold[(dot, r["origin_state"], r["dest_state"])]
        g["load_count"] += 1
        g["total_revenue"] += money(r["customer_rate"]) + money(r["accessorial_revenue"])  # Rule 3
        g["total_carrier_cost"] += money(r["carrier_cost"])
        carrier = fmcsa.get(dot)
        if carrier is None:  # Rule 6
            g["unverified_load_count"] += 1
        elif carrier["authority_status"] in ("REVOKED", "INACTIVE") and \
                date.fromisoformat(carrier["status_date"]) <= pickup_date_et:  # Rule 5
            g["unauthorized_load_count"] += 1

    tot = defaultdict(Decimal)
    for g in gold.values():
        for k, v in g.items():
            tot[k] += v
    margin = tot["total_revenue"] - tot["total_carrier_cost"]  # Rule 4
    print(f"silver rows (distinct loads): {len(current)}")
    print(f"gold rows (carrier x lane):   {len(gold)}")
    print(f"load_count:                   {tot['load_count']}")
    print(f"total_revenue:                {tot['total_revenue']}")
    print(f"total_carrier_cost:           {tot['total_carrier_cost']}")
    print(f"gross_margin:                 {margin}")
    print(f"margin_pct:                   {margin / tot['total_revenue']:.4%}")
    print(f"unauthorized_load_count:      {tot['unauthorized_load_count']}")
    print(f"unverified_load_count:        {tot['unverified_load_count']}")


if __name__ == "__main__":
    main()
