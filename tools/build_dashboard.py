"""Builds the AI/BI dashboard JSON for the carrier lane scorecard.

Run from the project root:
    .venv/Scripts/python tools/build_dashboard.py
Writes src/serving/carrier_lane_scorecard.lvdash.json (deployed with `databricks lakeview update`, see docs/runbook.md).
Queries use bare table names; catalog and schema come from --dataset-catalog / --dataset-schema at deploy time.
"""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "src" / "serving" / "carrier_lane_scorecard.lvdash.json"

# Semantic colors (Okabe-Ito, colour-blind safe)
GOOD, BAD, WARN, OTHER = "#009E73", "#D55E00", "#E69F00", "#CC79A7"

BASE_SQL = [
    "SELECT g.carrier_dot,\n",
    "       coalesce(g.legal_name, concat('Unverified DOT ', g.carrier_dot)) AS carrier,\n",
    "       coalesce(c.authority_status, 'NOT IN FMCSA') AS authority_status,\n",
    "       c.status_date AS authority_status_date,\n",
    "       g.origin_state, g.dest_state,\n",
    "       concat(g.origin_state, ' → ', g.dest_state) AS lane,\n",
    "       g.load_count, g.total_revenue, g.total_carrier_cost, g.gross_margin, g.margin_pct,\n",
    "       g.unauthorized_load_count, g.unverified_load_count,\n",
    "       CASE WHEN g.unverified_load_count > 0 THEN 'Unverified carrier'\n",
    "            WHEN g.unauthorized_load_count > 0 THEN 'Has unauthorized loads'\n",
    "            ELSE 'Authorized' END AS compliance\n",
    "FROM gold_carrier_lane_scorecard g\n",
    "LEFT JOIN silver_fmcsa_carriers c ON g.carrier_dot = c.dot_number\n",
]

MEASURES = [
    ("Loads", "Delivered loads picked up in October 2026 (Eastern)", "SUM(`load_count`)"),
    ("Revenue", "Customer rate + accessorials", "SUM(`total_revenue`)"),
    ("Carrier Cost", "Amount paid to carriers", "SUM(`total_carrier_cost`)"),
    ("Gross Margin", "Revenue - carrier cost", "SUM(`gross_margin`)"),
    ("Margin %", "Gross margin / revenue (ratio of sums)", "SUM(`gross_margin`) / SUM(`total_revenue`)"),
    ("Unauthorized Loads", "Hauled while the carrier's REVOKED/INACTIVE status was already in effect",
     "SUM(`unauthorized_load_count`)"),
    ("Unverified Loads", "Carrier DOT not found in the FMCSA census", "SUM(`unverified_load_count`)"),
]

datasets = [
    {"name": "ds_scorecard", "displayName": "Carrier lane scorecard",
     "queryLines": BASE_SQL,
     "columns": [{"displayName": n, "description": d, "expression": e} for n, d, e in MEASURES]},
    {"name": "ds_unauthorized", "displayName": "Carrier lanes with unauthorized loads",
     "queryLines": BASE_SQL + ["WHERE g.unauthorized_load_count > 0\n"]},
]

USD = {"type": "number-currency", "currencyCode": "USD", "abbreviation": "compact",
       "decimalPlaces": {"type": "max", "places": 2}}
USD_EXACT = {"type": "number-currency", "currencyCode": "USD", "decimalPlaces": {"type": "exact", "places": 2}}
PCT = {"type": "number-percent", "decimalPlaces": {"type": "max", "places": 1}}


def pos(x, y, w, h):
    return {"x": x, "y": y, "width": w, "height": h}


def text(name, lines, p):
    return {"widget": {"name": name, "multilineTextboxSpec": {"lines": lines}}, "position": p}


def measure_field(m):
    return {"name": f"measure({m})", "expression": f"MEASURE(`{m}`)"}


def kpi(name, m, title, fmt, p):
    value = {"fieldName": f"measure({m})", "displayName": title}
    if fmt:
        value["format"] = fmt
    return {"widget": {
        "name": name,
        "queries": [{"name": "main_query", "query": {
            "datasetName": "ds_scorecard", "fields": [measure_field(m)], "disaggregated": False}}],
        "spec": {"version": 2, "widgetType": "counter", "encodings": {"value": value},
                 "frame": {"showTitle": True, "title": title}}},
        "position": p}


COMPLIANCE_COLORS = {"type": "categorical", "mappings": [
    {"value": "Authorized", "color": GOOD},
    {"value": "Has unauthorized loads", "color": BAD},
    {"value": "Unverified carrier", "color": WARN}]}

margin_by_lane = {"widget": {
    "name": "margin-by-lane",
    "queries": [{"name": "main_query", "query": {
        "datasetName": "ds_scorecard",
        "fields": [{"name": "lane", "expression": "`lane`"},
                   {"name": "compliance", "expression": "`compliance`"},
                   {"name": "sum(gross_margin)", "expression": "SUM(`gross_margin`)"}],
        "disaggregated": False}}],
    "spec": {"version": 3, "widgetType": "bar",
             "encodings": {
                 "x": {"fieldName": "sum(gross_margin)", "displayName": "Gross margin",
                       "scale": {"type": "quantitative"}, "format": USD},
                 "y": {"fieldName": "lane", "displayName": "Lane",
                       "scale": {"type": "categorical", "sort": {"by": "value"}}},
                 "color": {"fieldName": "compliance", "displayName": "Carrier compliance",
                           "scale": COMPLIANCE_COLORS}},
             "frame": {"showTitle": True, "title": "Gross margin by lane",
                       "showDescription": True,
                       "description": "Colored by the compliance of the carrier-lane rows that earned it."}}},
    "position": pos(0, 7, 6, 8)}

unauthorized_by_carrier = {"widget": {
    "name": "unauthorized-by-carrier",
    "queries": [{"name": "main_query", "query": {
        "datasetName": "ds_unauthorized",
        "fields": [{"name": "carrier", "expression": "`carrier`"},
                   {"name": "authority_status", "expression": "`authority_status`"},
                   {"name": "sum(unauthorized_load_count)", "expression": "SUM(`unauthorized_load_count`)"}],
        "disaggregated": False}}],
    "spec": {"version": 3, "widgetType": "bar",
             "encodings": {
                 "x": {"fieldName": "sum(unauthorized_load_count)", "displayName": "Unauthorized loads",
                       "scale": {"type": "quantitative"}},
                 "y": {"fieldName": "carrier", "displayName": "Carrier",
                       "scale": {"type": "categorical", "sort": {"by": "value"}}},
                 "color": {"fieldName": "authority_status", "displayName": "FMCSA status",
                           "scale": {"type": "categorical", "mappings": [
                               {"value": "REVOKED", "color": BAD}, {"value": "INACTIVE", "color": OTHER}]}}},
             "frame": {"showTitle": True, "title": "Unauthorized loads by carrier",
                       "showDescription": True,
                       "description": "Loads hauled on or after the date the carrier's authority was revoked or inactivated."}}},
    "position": pos(6, 7, 6, 8)}

lane_matrix = {"widget": {
    "name": "lane-matrix",
    "queries": [{"name": "main_query", "query": {
        "datasetName": "ds_scorecard",
        "fields": [{"name": "origin_state", "expression": "`origin_state`"},
                   {"name": "dest_state", "expression": "`dest_state`"},
                   {"name": "sum(load_count)", "expression": "SUM(`load_count`)"}],
        "disaggregated": False}}],
    "spec": {"version": 3, "widgetType": "heatmap",
             "encodings": {
                 "x": {"fieldName": "dest_state", "displayName": "Destination state", "scale": {"type": "categorical"}},
                 "y": {"fieldName": "origin_state", "displayName": "Origin state", "scale": {"type": "categorical"}},
                 "color": {"fieldName": "sum(load_count)", "displayName": "Loads",
                           "scale": {"type": "quantitative", "colorRamp": {
                               "mode": "custom-sequential", "colors": {"start": "#E8F1FA", "end": "#0072B2"}}}},
                 "label": {"show": True}},
             "frame": {"showTitle": True, "title": "Lane matrix: loads by origin → destination"}}},
    "position": pos(0, 15, 6, 7)}

status_pie = {"widget": {
    "name": "loads-by-fmcsa-status",
    "queries": [{"name": "main_query", "query": {
        "datasetName": "ds_scorecard",
        "fields": [{"name": "authority_status", "expression": "`authority_status`"},
                   measure_field("Loads")],
        "disaggregated": False}}],
    "spec": {"version": 3, "widgetType": "pie",
             "encodings": {
                 "angle": {"fieldName": "measure(Loads)", "displayName": "Loads", "scale": {"type": "quantitative"}},
                 "color": {"fieldName": "authority_status", "displayName": "Current FMCSA status",
                           "scale": {"type": "categorical", "mappings": [
                               {"value": "ACTIVE", "color": GOOD}, {"value": "REVOKED", "color": BAD},
                               {"value": "INACTIVE", "color": OTHER}, {"value": "NOT IN FMCSA", "color": WARN}]}},
                 "label": {"show": True}},
             "frame": {"showTitle": True, "title": "Loads by carrier's current FMCSA status",
                       "showDescription": True,
                       "description": "Current status, not status at pickup: a carrier revoked after the pickup "
                                      "was authorized when it hauled. That's why REVOKED + INACTIVE loads exceed the "
                                      "unauthorized count."}}},
    "position": pos(6, 15, 6, 7)}

ALERT = lambda color: {"type": "basic", "rules": [{
    "condition": {"operand": {"type": "data-value", "value": "0"}, "operator": ">"},
    "backgroundColor": {"hex": color}}]}
TABLE_COLS = [
    ("carrier", "Carrier", None, None), ("carrier_dot", "USDOT", None, None),
    ("authority_status", "FMCSA status", None, None), ("lane", "Lane", None, None),
    ("load_count", "Loads", None, None), ("total_revenue", "Revenue", USD_EXACT, None),
    ("total_carrier_cost", "Carrier cost", USD_EXACT, None), ("gross_margin", "Gross margin", USD_EXACT, None),
    ("margin_pct", "Margin %", PCT, None),
    ("unauthorized_load_count", "Unauthorized", None, ALERT("#F4B9A0")),
    ("unverified_load_count", "Unverified", None, ALERT("#F7D9A0")),
]
detail_table = {"widget": {
    "name": "scorecard-table",
    "queries": [{"name": "main_query", "query": {
        "datasetName": "ds_scorecard",
        "fields": [{"name": c, "expression": f"`{c}`"} for c, *_ in TABLE_COLS],
        "disaggregated": True,
        "orders": [{"direction": "DESC", "expression": "`unauthorized_load_count`"},
                   {"direction": "DESC", "expression": "`load_count`"}]}}],
    "spec": {"version": 2, "widgetType": "table",
             "encodings": {"columns": [
                 {k: v for k, v in {"fieldName": c, "displayName": d, "format": f, "style": s}.items() if v}
                 for c, d, f, s in TABLE_COLS]},
             "frame": {"showTitle": True, "title": "Carrier lane scorecard (one row per carrier × lane)"}}},
    "position": pos(0, 22, 12, 9)}

overview = [
    text("title", ["# Carrier Lane Scorecard — October 2026\n"], pos(0, 0, 12, 1)),
    text("subtitle", [
        "Delivered loads with an October 2026 pickup date in **US Eastern time**, per carrier and lane "
        "(origin state → destination state). Source: `gold_carrier_lane_scorecard`, rebuilt daily and marked "
        "`certified` only when all 15 data-quality checks pass. **Unauthorized** = the carrier's REVOKED/INACTIVE "
        "status took effect on or before the pickup date. **Unverified** = the carrier's DOT isn't in the FMCSA census.\n"],
        pos(0, 1, 12, 2)),
    kpi("kpi-loads", "Loads", "Loads", None, pos(0, 3, 2, 4)),
    kpi("kpi-revenue", "Revenue", "Revenue", USD, pos(2, 3, 2, 4)),
    kpi("kpi-margin", "Gross Margin", "Gross margin", USD, pos(4, 3, 2, 4)),
    kpi("kpi-margin-pct", "Margin %", "Margin %", {"type": "number-percent", "decimalPlaces": {"type": "max", "places": 2}},
        pos(6, 3, 2, 4)),
    kpi("kpi-unauthorized", "Unauthorized Loads", "Unauthorized loads", None, pos(8, 3, 2, 4)),
    kpi("kpi-unverified", "Unverified Loads", "Unverified loads", None, pos(10, 3, 2, 4)),
    margin_by_lane, unauthorized_by_carrier, lane_matrix, status_pie, detail_table,
]


def multi_filter(name, field, title, p, datasets=("ds_scorecard", "ds_unauthorized")):
    queries = [{"name": f"{ds}_{field}", "query": {
        "datasetName": ds, "fields": [{"name": field, "expression": f"`{field}`"}], "disaggregated": False}}
        for ds in datasets]
    return {"widget": {"name": name, "queries": queries,
                       "spec": {"version": 2, "widgetType": "filter-multi-select",
                                "encodings": {"fields": [{"fieldName": field, "displayName": title,
                                                          "queryName": q["name"]} for q in queries]},
                                "frame": {"showTitle": True, "title": title}}},
            "position": p}


filters = [
    multi_filter("filter-carrier", "carrier", "Carrier", pos(0, 0, 3, 2)),
    multi_filter("filter-origin", "origin_state", "Origin state", pos(3, 0, 3, 2)),
    multi_filter("filter-dest", "dest_state", "Destination state", pos(6, 0, 3, 2)),
    multi_filter("filter-compliance", "compliance", "Carrier compliance", pos(9, 0, 3, 2)),
]

dashboard = {
    "datasets": datasets,
    "pages": [
        {"name": "overview", "displayName": "Scorecard", "pageType": "PAGE_TYPE_CANVAS",
         "layoutVersion": "GRID_V1", "layout": overview},
        {"name": "filters", "displayName": "Filters", "pageType": "PAGE_TYPE_GLOBAL_FILTERS",
         "layoutVersion": "GRID_V1", "layout": filters},
    ],
    "uiSettings": {"theme": {
        "canvasBackgroundColor": {"light": "#F7F9FB", "dark": "#1F272D"},
        "widgetBackgroundColor": {"light": "#FFFFFF", "dark": "#11171C"},
        "widgetBorderColor": {"light": "#FFFFFF", "dark": "#11171C"},
        "fontColor": {"light": "#11171C", "dark": "#E8ECF0"},
        "selectionColor": {"light": "#2272B4", "dark": "#8ACAFF"},
        "visualizationColors": ["#0072B2", "#E69F00", "#009E73", "#CC79A7", "#D55E00", "#56B4E9", "#F0E442"],
        "widgetHeaderAlignment": "LEFT",
        "widgetCornerRadius": 8}},
}

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(dashboard, indent=2, ensure_ascii=False), encoding="utf-8")

# Self-check: every visualization field name used in encodings exists in its query
for item in overview:
    w = item["widget"]
    if "spec" not in w:
        continue
    names = {f["name"] for q in w["queries"] for f in q["query"]["fields"]}
    enc = w["spec"]["encodings"]
    used = [c["fieldName"] for c in enc.get("columns", [])] + \
           [v["fieldName"] for v in enc.values() if isinstance(v, dict) and "fieldName" in v]
    missing = set(used) - names
    assert not missing, f"{w['name']}: {missing}"
for page in dashboard["pages"]:
    rows = {}
    for item in page["layout"]:
        p = item["position"]
        rows.setdefault(p["y"], 0)
        rows[p["y"]] += p["width"]
    print(page["name"], "row widths:", dict(sorted(rows.items())))
print(f"Wrote {OUT}")
