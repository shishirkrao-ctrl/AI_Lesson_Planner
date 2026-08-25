"""
Renders the generated schedule as a PDF that mirrors the university's
existing "Lesson Plan" table format: merged Week/Unit cells, colored
ISA / Buffer / Lab / Orange Problem / Jackfruit Problem rows, and an
Activity Type summary table at the bottom.
"""
from io import BytesIO
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# Max data rows rendered in a single physical Table block. Kept low enough that
# every chunk comfortably fits on one landscape-A4 page, so reportlab never has
# to auto-split a table mid-page -- which is what triggers its crash when a
# vertical SPAN (merged Week/Unit cell) straddles the split point.
MAX_ROWS_PER_CHUNK = 20

# Row-type -> (background, text color, bold, italic) -- mirrors the frontend's rowStyle()
ROW_STYLES = {
    "isa": ("#FBEAEA", "#8F2E2C", True, False),
    "buffer": ("#EAF2FB", "#5B7286", False, True),
    "lab": ("#EAF2FB", "#223648", True, False),
    "banana": ("#FFF6D6", "#8A6D1D", False, True),
    "orange": ("#FFE3C6", "#8A4B1D", False, True),
    "jackfruit": ("#E4F1DA", "#2F5D34", False, True),
}
UNIT_PALETTE = ["#DCEEFF", "#FFE9D6", "#E4F1DA", "#F5E1F5", "#FFF3C4", "#E0E7FF"]

COLS = ["Week", "Session", "Unit", "Reference Book & Chapter #", "Topics", "% of Syllabus", "Cumulative %"]
COL_WIDTHS = [16 * mm, 16 * mm, 26 * mm, 40 * mm, 122 * mm, 22 * mm, 22 * mm]


def _style_sheet():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle("Cell", parent=styles["Normal"], fontSize=8, leading=10))
    styles.add(ParagraphStyle("CellBold", parent=styles["Cell"], fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle("CellItalic", parent=styles["Cell"], fontName="Helvetica-Oblique"))
    styles.add(
        ParagraphStyle(
            "Center",
            parent=styles["Cell"],
            alignment=TA_CENTER,
        )
    )
    styles.add(
        ParagraphStyle(
            "CenterBold",
            parent=styles["Center"],
            fontName="Helvetica-Bold",
        )
    )
    return styles


def _p(text, style):
    text = "" if text is None else str(text)
    return Paragraph(text.replace("\n", "<br/>"), style)


def build_lesson_plan_pdf(
    course_name: str,
    course_code: str,
    credits: int,
    department: Optional[str],
    documented_by: Optional[str],
    schedule_rows: list,
) -> bytes:
    styles = _style_sheet()
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        leftMargin=10 * mm,
        rightMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
    )

    story = []

    header_style = ParagraphStyle("Header", parent=styles["Title"], fontSize=16, alignment=TA_CENTER)
    sub_style = ParagraphStyle("Sub", parent=styles["Normal"], fontSize=11, alignment=TA_CENTER)
    story.append(Paragraph(department or "Lesson Plan", header_style))
    story.append(Paragraph(f"Course Name: {course_name}", sub_style))
    story.append(
        Paragraph(
            f"Course code: {course_code} &nbsp;&nbsp;|&nbsp;&nbsp; Credits: {credits}"
            + (f" &nbsp;&nbsp;|&nbsp;&nbsp; Documented by: {documented_by}" if documented_by else ""),
            sub_style,
        )
    )
    story.append(Spacer(1, 8))

    # ---- assign a background tint per unit, in order of first appearance ----
    unit_color = {}
    for r in schedule_rows:
        u = (r.get("unit") or "").strip()
        if u and u not in unit_color and r.get("row_type") not in ("isa",):
            unit_color[u] = UNIT_PALETTE[len(unit_color) % len(UNIT_PALETTE)]

    n = len(schedule_rows)

    # ---- Step 1: partition rows into atomic "blocks" that must never be torn
    # apart across a page break. A block is either a single ISA row, or a
    # maximal run of consecutive non-ISA rows that share the same unit (which
    # is always a superset of any week-level merge nested inside it). ----
    blocks = []
    i = 0
    while i < n:
        r = schedule_rows[i]
        if r.get("row_type") == "isa":
            blocks.append((i, i + 1))
            i += 1
            continue
        unit_val = r.get("unit")
        j = i + 1
        while j < n and schedule_rows[j].get("row_type") != "isa" and schedule_rows[j].get("unit") == unit_val:
            j += 1
        blocks.append((i, j))
        i = j

    # ---- Step 2: group consecutive blocks into page-sized chunks, never
    # splitting a block. Each chunk becomes its own Table wrapped in
    # KeepTogether, so reportlab never auto-splits a table mid-span (the
    # scenario that crashes it). ----
    chunk_bounds = []  # list of (start, end) row-index ranges into schedule_rows
    chunk_start = 0
    chunk_len = 0
    for (b_start, b_end) in blocks:
        b_len = b_end - b_start
        if chunk_len and chunk_len + b_len > MAX_ROWS_PER_CHUNK:
            chunk_bounds.append((chunk_start, b_start))
            chunk_start = b_start
            chunk_len = 0
        chunk_len += b_len
    chunk_bounds.append((chunk_start, n))

    base_style = [
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#C9E0F5")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2F4860")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]

    for chunk_idx, (start, end) in enumerate(chunk_bounds):
        data = [[Paragraph(h, styles["CenterBold"]) for h in COLS]]
        span_commands = []
        bg_commands = []
        text_color_commands = []

        row_idx = 1  # header is row 0, within this chunk's table
        i = start
        while i < end:
            r = schedule_rows[i]
            row_type = r.get("row_type", "lecture")

            if row_type == "isa":
                label = r.get("unit") or r.get("topics") or "ISA"
                data.append([_p(label, styles["CenterBold"]), "", "", "", "", "", ""])
                span_commands.append(("SPAN", (0, row_idx), (6, row_idx)))
                bg, fg, bold, italic = ROW_STYLES["isa"]
                bg_commands.append(("BACKGROUND", (0, row_idx), (6, row_idx), colors.HexColor(bg)))
                text_color_commands.append(("TEXTCOLOR", (0, row_idx), (6, row_idx), colors.HexColor(fg)))
                i += 1
                row_idx += 1
                continue

            # non-ISA row: figure out how many consecutive rows (within this
            # chunk) share this week / this unit
            week_val = r.get("week")
            unit_val = r.get("unit")

            week_span = 1
            j = i + 1
            while j < end and schedule_rows[j].get("row_type") != "isa" and schedule_rows[j].get("week") == week_val:
                week_span += 1
                j += 1

            unit_span = 1
            j = i + 1
            while j < end and schedule_rows[j].get("row_type") != "isa" and schedule_rows[j].get("unit") == unit_val:
                unit_span += 1
                j += 1

            cell_style = styles["Cell"]
            if row_type in ("lab",):
                cell_style = styles["CellBold"]
            elif row_type in ("buffer", "banana", "orange", "jackfruit"):
                cell_style = styles["CellItalic"]

            data.append(
                [
                    _p(week_val, styles["Center"]),
                    _p(r.get("session"), styles["Center"]),
                    _p(unit_val, cell_style),
                    _p(r.get("ref"), cell_style),
                    _p(r.get("topics"), cell_style),
                    _p(r.get("unit_pct"), styles["Center"]),
                    _p(r.get("cum_pct"), styles["Center"]),
                ]
            )

            if week_span > 1:
                span_commands.append(("SPAN", (0, row_idx), (0, row_idx + week_span - 1)))
            if unit_span > 1:
                span_commands.append(("SPAN", (2, row_idx), (2, row_idx + unit_span - 1)))

            if row_type in ROW_STYLES:
                bg, fg, bold, italic = ROW_STYLES[row_type]
                bg_commands.append(("BACKGROUND", (0, row_idx), (6, row_idx), colors.HexColor(bg)))
                text_color_commands.append(("TEXTCOLOR", (2, row_idx), (4, row_idx), colors.HexColor(fg)))
            elif unit_val and unit_val in unit_color:
                bg_commands.append(("BACKGROUND", (0, row_idx), (1, row_idx), colors.HexColor(unit_color[unit_val])))
                bg_commands.append(("BACKGROUND", (2, row_idx), (2, row_idx), colors.HexColor(unit_color[unit_val])))

            row_idx += 1
            i += 1

        table = Table(data, colWidths=COL_WIDTHS, repeatRows=1)
        table.setStyle(TableStyle(base_style + span_commands + bg_commands + text_color_commands))
        story.append(KeepTogether(table))
        if chunk_idx < len(chunk_bounds) - 1:
            story.append(Spacer(1, 4))

    # ---- Activity Type summary, same shape as the reference document ----
    story.append(Spacer(1, 14))
    counts = {}
    for r in schedule_rows:
        rt = r.get("row_type", "lecture")
        counts[rt] = counts.get(rt, 0) + 1
    total = sum(counts.values()) or 1

    label_map = [
        ("lecture", "Lecture Hours"),
        ("lab", "Lab Hours"),
        ("orange", "Orange Problem"),
        ("banana", "Banana Problem"),
        ("jackfruit", "Jackfruit - Miniproject"),
        ("buffer", "Buffer"),
        ("isa", "ISA"),
    ]
    summary_data = [["#", "Activity Type", "# of Sessions", "%"]]
    idx = 1
    for key, label in label_map:
        if counts.get(key):
            summary_data.append([str(idx), label, str(counts[key]), f"{counts[key] / total * 100:.2f}%"])
            idx += 1
    summary_data.append(["", "Total", str(total), "100%"])

    summary_table = Table(summary_data, colWidths=[10 * mm, 60 * mm, 30 * mm, 20 * mm])
    summary_table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#C9E0F5")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2F4860")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#EAF2FB")),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(summary_table)

    doc.build(story)
    return buf.getvalue()