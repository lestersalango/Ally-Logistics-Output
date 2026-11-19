"""Builds the project summary PDF for the tech team and stakeholders.

Run from the project root:
    .venv/Scripts/python tools/build_summary_pdf.py
Writes docs/reports/carrier_scorecard_summary.pdf
"""
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "reports" / "carrier_scorecard_summary.pdf"
SHOT = ROOT / "docs" / "reports" / "dashboard_2026-11-18.png"

pdfmetrics.registerFont(TTFont("Arial", "C:/Windows/Fonts/arial.ttf"))
pdfmetrics.registerFont(TTFont("Arial-Bold", "C:/Windows/Fonts/arialbd.ttf"))
pdfmetrics.registerFontFamily("Arial", normal="Arial", bold="Arial-Bold")

NAVY, TEAL, CORAL, AMBER = colors.HexColor("#1D3557"), colors.HexColor("#009E73"), colors.HexColor("#D55E00"), colors.HexColor("#E69F00")
INK, MUTED, LINE, TINT = colors.HexColor("#1F2933"), colors.HexColor("#5B6770"), colors.HexColor("#D9DEE3"), colors.HexColor("#F3F6F9")

S = {
    "title": ParagraphStyle("title", fontName="Arial-Bold", fontSize=20, leading=24, textColor=NAVY),
    "sub": ParagraphStyle("sub", fontName="Arial", fontSize=9.5, leading=13, textColor=MUTED),
    "h2": ParagraphStyle("h2", fontName="Arial-Bold", fontSize=12.5, leading=16, textColor=NAVY, spaceBefore=10, spaceAfter=4),
    "body": ParagraphStyle("body", fontName="Arial", fontSize=9.5, leading=13.2, textColor=INK),
    "cell": ParagraphStyle("cell", fontName="Arial", fontSize=8.6, leading=11.2, textColor=INK),
    "cellb": ParagraphStyle("cellb", fontName="Arial-Bold", fontSize=8.6, leading=11.2, textColor=INK),
    "head": ParagraphStyle("head", fontName="Arial-Bold", fontSize=8.6, leading=11, textColor=colors.white),
    "kpi": ParagraphStyle("kpi", fontName="Arial-Bold", fontSize=16, leading=19, textColor=NAVY, alignment=TA_CENTER),
    "kpil": ParagraphStyle("kpil", fontName="Arial", fontSize=7.8, leading=10, textColor=MUTED, alignment=TA_CENTER),
    "flow": ParagraphStyle("flow", fontName="Arial", fontSize=8, leading=10.5, textColor=INK, alignment=TA_CENTER),
    "flowb": ParagraphStyle("flowb", fontName="Arial-Bold", fontSize=9.5, leading=12, textColor=colors.white, alignment=TA_CENTER),
    "arrow": ParagraphStyle("arrow", fontName="Arial-Bold", fontSize=14, leading=16, textColor=MUTED, alignment=TA_CENTER),
    "cap": ParagraphStyle("cap", fontName="Arial", fontSize=8, leading=10.5, textColor=MUTED),
}
W = A4[0] - 36 * mm


def p(text, style="body"):
    return Paragraph(text, S[style])


def table(rows, widths, head=True, zebra=True):
    data = [[p(c, "head") for c in rows[0]]] + [[p(c, "cell") for c in r] for r in rows[1:]] if head else \
           [[p(c, "cell") for c in r] for r in rows]
    t = Table(data, colWidths=[w * W for w in widths], repeatRows=1 if head else 0)
    style = [("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
             ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
             ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE)]
    if head:
        style.append(("BACKGROUND", (0, 0), (-1, 0), NAVY))
    if zebra:
        style += [("BACKGROUND", (0, i), (-1, i), TINT) for i in range(2 if head else 1, len(data), 2)]
    t.setStyle(TableStyle(style))
    return t


def kpis():
    items = [("1,366", "Delivered loads"), ("$4,004,780.61", "Revenue"), ("$643,949.97", "Gross margin"),
             ("16.08%", "Margin"), ("154", "Unauthorized loads"), ("20", "Unverified loads")]
    rows = []
    for start in (0, 3):                       # 2 rows x 3 KPIs, so exact values fit
        chunk = items[start:start + 3]
        rows.append([p(v, "kpi") for v, _ in chunk])
        rows.append([p(label, "kpil") for _, label in chunk])
    t = Table(rows, colWidths=[W / 3] * 3)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), TINT), ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                           ("LINEAFTER", (0, 0), (-2, -1), 1.5, colors.white),
                           ("LINEBELOW", (0, 1), (-1, 1), 1.5, colors.white),
                           ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                           ("TOPPADDING", (0, 0), (-1, 0), 7), ("TOPPADDING", (0, 2), (-1, 2), 7),
                           ("BOTTOMPADDING", (0, 1), (-1, 1), 7), ("BOTTOMPADDING", (0, 3), (-1, 3), 7),
                           ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    return t


def flow():
    boxes = [("Raw files", "2 CSVs landed in a Unity Catalog volume", MUTED),
             ("Bronze", "As received, every column text. COPY INTO loads each file once", colors.HexColor("#8C6D46")),
             ("Silver", "Typed, cleaned, one row per load. Incremental MERGE: newest version wins", colors.HexColor("#6E7B8B")),
             ("Gold", "Carrier \u00d7 lane scorecard + 15 quality checks", colors.HexColor("#B08D1E")),
             ("Dashboard", "AI/BI dashboard on the certified gold table", NAVY)]
    row1, row2, widths = [], [], []
    for i, (name, desc, col) in enumerate(boxes):
        row1.append(p(name, "flowb"))
        row2.append(p(desc, "flow"))
        widths.append(0.168)
        if i < len(boxes) - 1:
            row1.append(p("\u2192", "arrow"))
            row2.append("")
            widths.append(0.04)
    t = Table([row1, row2], colWidths=[w * W for w in widths])
    style = [("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 4),
             ("BOTTOMPADDING", (0, 0), (-1, -1), 4), ("LEFTPADDING", (0, 0), (-1, -1), 3),
             ("RIGHTPADDING", (0, 0), (-1, -1), 3)]
    for i, (_, _, col) in enumerate(boxes):
        c = i * 2
        style += [("BACKGROUND", (c, 0), (c, 0), col), ("BACKGROUND", (c, 1), (c, 1), TINT),
                  ("BOX", (c, 0), (c, 1), 0.5, col), ("SPAN", (c + 1, 0), (c + 1, 1)) if i < len(boxes) - 1 else
                  ("BOX", (c, 0), (c, 1), 0.5, col)]
    t.setStyle(TableStyle(style))
    return t


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Arial", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(18 * mm, 10 * mm, "Carrier Lane Scorecard \u00b7 project summary \u00b7 18 Nov 2026")
    canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {doc.page}")
    canvas.restoreState()


story = [
    p("Carrier Lane Scorecard", "title"),
    p("Project summary for the tech team and stakeholders \u00b7 Databricks (serverless) \u00b7 built 18 Nov 2026", "sub"),
    Spacer(1, 8),
    p("<b>The question.</b> For October 2026, which carriers hauled Delivered loads on which lanes "
      "(origin state \u2192 destination state), what revenue and margin did we make, and did any carrier haul while "
      "it was not legally authorized (FMCSA)?"),
    Spacer(1, 4),
    p("<b>The answer.</b> A daily, self-checking pipeline that produces a certified scorecard table and a dashboard. "
      "October 2026 results:"),
    Spacer(1, 6),
    kpis(),
    Spacer(1, 3),
    p("Every number was reproduced exactly by a second, independent implementation of the business rules (plain Python, no Spark).", "cap"),

    p("What we did, start to finish", "h2"),
    table([
        ["#", "Step", "Outcome"],
        ["1", "Read the brief and profiled the raw data", "Found 12 data traps before writing any pipeline code (next page)"],
        ["2", "Wrote the project plan from our brief template", "Single-notebook scope, conventions, expected totals, steps"],
        ["3", "Landed the files and built the notebook", "Raw CSVs in a Unity Catalog volume; notebook is version-controlled locally"],
        ["4", "Built bronze \u2192 silver \u2192 gold + quality checks", "Totals match exactly; all 15 checks pass; gold marked <b>certified</b>"],
        ["5", "Proved it is safe to rerun and incremental", "Reruns change nothing; a test feed applied only the new and changed loads"],
        ["6", "Scheduled job with alerts", "Daily 06:00 ET (paused until approved); a forced test failure triggered the alert"],
        ["7", "Runbook and interview talking points", "How to run, monitor, recover, and remove; why each choice was made"],
        ["8", "AI/BI dashboard", "KPIs, 4 charts, scorecard table, 4 filters; reads the certified gold table"],
    ], [0.04, 0.46, 0.50]),
]

story += [
    p("How it works", "h2"),
    flow(),
    Spacer(1, 4),
    p("A Lakeflow job runs the notebook on serverless compute: 1 retry, 30-minute timeout, one run at a time. It emails the "
      "owner on failure or when a run takes over 10 minutes. A failed quality check fails the run, and gold stays "
      "marked <b>warn</b> until a clean run. Typical run: about 50 seconds.", "body"),

    PageBreak(),
    p("Data problems found and handled", "h2"),
    table([
        ["Problem in the data", "If ignored", "What we did"],
        ["A load is re-sent on every change: 3,200 rows for 1,800 loads, in no particular order",
         "Loads counted several times, or an old version kept", "Keep the latest version of each load by its timestamp, never by file order"],
        ["Carrier numbers typed by hand (<i>USDOT 123</i>, leading zeros, spaces)",
         "Only 1,158 of 2,390 rows match the FMCSA census", "Clean and convert to a number: 2,351 match"],
        ["Pickup times are in UTC; reporting is US Eastern",
         "1,358 loads instead of 1,366 (wrong month boundary)", "Convert to Eastern before picking October"],
        ["A carrier revoked <i>after</i> the pickup (147 loads)",
         "Wrongly flagged as unauthorized", "Flag only if the revocation date is on or before the pickup date"],
        ["Legacy margin column leaves out extra charges",
         "Margin understated: $554K instead of $644K", "Recalculate: revenue (rate + extras) minus carrier cost"],
        ["20 loads use a carrier missing from FMCSA",
         "Silently dropped by a normal join", "Kept and counted as <b>unverified</b>"],
    ], [0.38, 0.29, 0.33]),

    p("Quality and reliability, proven", "h2"),
    table([
        ["Check", "Result"],
        ["15 automated quality checks (one row per load, totals reconcile, no unparsed values, ...)", "All pass; the run fails and alerts if any fail"],
        ["Rerun with no new data", "0 rows loaded, 0 changes"],
        ["Re-apply all 1,800 loads", "0 inserted, 0 updated: the update is idempotent"],
        ["Test feed: cost correction, new load, stale version, duplicate", "1 inserted, 1 updated; the stale and duplicate records were correctly ignored"],
        ["Test data removed", "Delta time travel (RESTORE) set silver back; totals returned to the official numbers"],
        ["Forced failure (alert test)", "Run failed on both attempts, triggering the failure alert"],
    ], [0.55, 0.45]),
]

story += [
    p("Known limitations and next steps", "h2"),
    table([
        ["Item", "Status / proposal"],
        ["Schedule", "Created but <b>paused</b>; unpause on approval"],
        ["Report month", "Fixed to Oct 2026; derive it from the run date for a real daily report"],
        ["FMCSA history", "Only today's census is available; keep each snapshot (SCD Type 2) to see past revocations"],
        ["Scale-up option", "Move to Lakeflow Declarative Pipelines (Auto Loader, AUTO CDC, expectations)"],
        ["Environments", "Dev only; no prod target, CI or bundle (out of scope for this exercise)"],
        ["Dashboard polish", "Sort the bars by value; show exact KPI values (e.g. $4.00M rather than $4M)"],
    ], [0.25, 0.75]),

    p("Where things are", "h2"),
    table([
        ["What", "Where"],
        ["Start and rules", "README.md (start here), carrier_scorecard_exercise/data_dictionary.md"],
        ["Pipeline", "src/carrier_lane_scorecard.py, deployed as the notebook carrier_lane_scorecard"],
        ["Job", "resources/carrier_lane_scorecard.job.json, deployed as job carrier_lane_scorecard (id 697967429732215)"],
        ["Tables", "workspace.default: bronze_loads, bronze_fmcsa_carriers, silver_loads, silver_fmcsa_carriers, gold_carrier_lane_scorecard"],
        ["Dashboard", "Carrier Lane Scorecard (id 01f1e35942291816b926da78e98c569c), built by tools/build_dashboard.py"],
        ["Operations", "docs/runbook.md: run, monitor, alerts, recovery, removal"],
    ], [0.18, 0.82]),
    PageBreak(),
]

img_w = W                                          # full-page export: 2880 x 2930 px
img_h = img_w * 2930 / 2880
story += [
    p("The dashboard", "h2"),
    p("<b>How to read it:</b> carriers that are REVOKED or INACTIVE today hauled 301 loads, but only 154 of them were "
      "hauled after the revocation took effect. Those 154 are the real compliance exposure. REDLINE TRANSIT INC (25) "
      "and RAPID FREIGHT INC (19) lead the list.", "body"),
    Spacer(1, 5),
    Image(str(SHOT), width=img_w, height=img_h),
    Spacer(1, 3),
    p("Carrier Lane Scorecard (Databricks AI/BI), exported 18 Nov 2026. It has six KPIs, gross margin by lane (colored by "
      "carrier compliance), unauthorized loads by carrier, a lane matrix, loads by each carrier's current FMCSA status, "
      "and the full 758-row scorecard table. Global filters cover carrier, origin, destination and compliance.", "cap"),
]

OUT.parent.mkdir(parents=True, exist_ok=True)
doc = SimpleDocTemplate(str(OUT), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                        bottomMargin=16 * mm, title="Carrier Lane Scorecard: project summary",
                        author="Carrier scorecard project", subject="October 2026 carrier lane scorecard on Databricks")
doc.build(story, onFirstPage=footer, onLaterPages=footer)
print(f"Wrote {OUT}")
