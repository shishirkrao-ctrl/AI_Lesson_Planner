"""
Academic-calendar PDF parsing.

Replaces the old flow of manually typing in the semester start/end date and
the two ISA start dates. Instead, the user uploads the institution's academic
calendar PDF (the "Week# / Month / Mon..Sat / # of working days /
Activities" grid, e.g. the PES University calendar), and this module reads
the grid directly to work out:

  - every calendar date the semester covers
  - which of those dates are public holidays (cells marked "H")
  - the ISA 1 / ISA 2 exam windows (cells marked "ISA 1" / "ISA 2")
  - the Last Working Day (a cell marked "LWD"), after which nothing counts

Rules applied (per institution instruction, not just what the PDF says):
  - Saturdays and Sundays are never teaching days, regardless of what the
    calendar's own "# of working days" column implies about a given Saturday.
  - Nothing after the Last Working Day (LWD) is counted, even if the PDF
    still lists dates for ESA/results beyond it.
  - Public holidays (cells marked "H") are NOT excluded -- per instruction
    they're kept as ordinary working/teaching days. They're still parsed and
    reported separately as holiday_dates for reference.

No Streamlit here -- plain parsing + date logic, unit-testable on its own.
"""
import re
from datetime import date, timedelta

import pdfplumber

WEEKDAY_COLS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
_WEEKDAY_INDEX = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5}  # Sun never appears in the grid

MONTH_NUM = {
    name.lower(): i + 1
    for i, name in enumerate(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    )
}
MONTH_NUM["sept"] = 9

_ROW_ANCHOR_RE = re.compile(r"^\d{1,2}\.$")           # "1.", "2.", ... in the Week# column
_CELL_LEADING_NUM_RE = re.compile(r"^(\d{1,2})\s*(.*)$")
_SESSION_RE = re.compile(r"Session:\s*([A-Za-z]+)\s*[\u2013-]\s*([A-Za-z]+)\s*(\d{4})")


class CalendarParseError(ValueError):
    """Raised when the uploaded PDF doesn't look like the expected calendar grid."""


def _find_column_bounds(page) -> list:
    """
    The grid's vertical gridlines are drawn as vector rects. Full-height
    rects (one per row) mark real column boundaries; short rects are just
    the sub-cell alignment lines pdfplumber's renderer leaves inside a
    single day cell. Cluster the x-positions of the tall ones to get the
    real column edges, independent of exact PDF dimensions.
    """
    xs = sorted(set(round(r["x0"], 1) for r in page.rects if r["height"] > 15))
    if not xs:
        raise CalendarParseError("couldn't find the calendar's table gridlines on this page")
    clusters = []
    for x in xs:
        if clusters and x - clusters[-1][-1] <= 8:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    return [sum(c) / len(c) for c in clusters]


def _parse_cell(text: str):
    """'26\\nH' -> (26, 'H'); '19\\nISA 1' -> (19, 'ISA 1'); '' -> (None, None)."""
    text = (text or "").strip()
    if not text:
        return None, None
    m = _CELL_LEADING_NUM_RE.match(text)
    if m:
        return int(m.group(1)), (m.group(2).strip() or None)
    return None, text


def parse_calendar_grid(pdf_file) -> dict:
    """
    Reads the academic-calendar PDF and returns:
      {
        "start_month": 8, "start_year": 2026,   # from the "Session: Aug - Dec 2026" line
        "rows": [ {"week": "1.", "cells": {"Mon": (3, None), ..., "Sat": (8, None)}}, ... ],
      }
    `pdf_file` is anything pdfplumber.open() accepts (path or file-like/UploadedFile).
    """
    with pdfplumber.open(pdf_file) as pdf:
        page = pdf.pages[0]
        words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
        bounds = _find_column_bounds(page)

    if len(bounds) < 9:
        raise CalendarParseError(
            "this doesn't look like the expected calendar grid (couldn't find all 6 day columns)"
        )
    # bounds layout: [left edge, week#|month, month|Mon, Mon|Tue, ..., Fri|Sat, Sat|workdays, workdays|activities]
    week_month_edge = bounds[1]
    day_col_bounds = bounds[2:9]  # 7 edges -> 6 day columns (Mon..Sat)
    activities_edge = bounds[8]

    full_text = " ".join(w["text"] for w in words)
    m = _SESSION_RE.search(full_text)
    if not m:
        raise CalendarParseError("couldn't find a 'Session: <Month> - <Month> <Year>' line in the PDF")
    start_month_name, _end_month_name, start_year = m.group(1), m.group(2), int(m.group(3))
    start_key = start_month_name.lower()[:4] if start_month_name.lower().startswith("sept") else start_month_name.lower()[:3]
    if start_key not in MONTH_NUM:
        raise CalendarParseError(f"unrecognised session start month '{start_month_name}'")
    start_month = MONTH_NUM[start_key]

    anchors = sorted(
        (w for w in words if _ROW_ANCHOR_RE.match(w["text"]) and w["x0"] < week_month_edge),
        key=lambda w: w["top"],
    )
    if not anchors:
        raise CalendarParseError("couldn't find any 'Week #' row markers (1., 2., 3., ...) in the PDF")
    anchor_tops = [a["top"] for a in anchors]

    def _nearest_row(top):
        best_i, best_d = None, None
        for i, t in enumerate(anchor_tops):
            d = abs(top - t)
            if best_d is None or d < best_d:
                best_d, best_i = d, i
        return best_i, best_d

    # A cell's day-number can sit slightly *above* its own row when the cell
    # below it (e.g. "15\nH") wraps to two lines, so we match every word to
    # its nearest row-anchor by vertical distance rather than a hard band --
    # capped so stray header/footer text well outside the table is dropped.
    max_row_dist = 15
    rows = [{"week": a["text"], "cells": {c: [] for c in WEEKDAY_COLS}} for a in anchors]
    for w in words:
        if w["x0"] < week_month_edge or w["x0"] >= activities_edge:
            continue
        row_i, dist = _nearest_row(w["top"])
        if dist > max_row_dist:
            continue
        for col_i, col_name in enumerate(WEEKDAY_COLS):
            if day_col_bounds[col_i] <= w["x0"] < day_col_bounds[col_i + 1]:
                rows[row_i]["cells"][col_name].append(w)
                break

    parsed_rows = []
    for r in rows:
        cells = {}
        for col_name in WEEKDAY_COLS:
            ws = sorted(r["cells"][col_name], key=lambda w: (round(w["top"]), w["x0"]))
            cells[col_name] = _parse_cell(" ".join(w["text"] for w in ws))
        parsed_rows.append({"week": r["week"], "cells": cells})

    return {"start_month": start_month, "start_year": start_year, "rows": parsed_rows}


def compute_working_days(
    parsed: dict,
    holiday_code: str = "H",
    lwd_code: str = "LWD",
    isa1_code: str = "ISA 1",
    isa2_code: str = "ISA 2",
) -> dict:
    """
    Walks the parsed grid day-by-day (real calendar dates, Sunday always
    skipped since it's never a grid column) and returns:
      {
        "sem_start": date, "sem_end": date,
        "lwd_date": date | None,
        "isa1_start": date | None, "isa1_end": date | None,
        "isa2_start": date | None, "isa2_end": date | None,
        "holiday_dates": [date, ...],
        "teaching_dates": [date, ...],   # Mon-Fri, on/before LWD (holidays kept as working days)
        "warnings": [str, ...],
      }
    """
    rows = parsed["rows"]
    warnings = []

    # Anchor the very first date from the first filled cell + the session's
    # start month/year -- everything after that is pure date arithmetic, so
    # OCR'd day-numbers never have to be trusted for month/year rollovers.
    cursor = None
    for row in rows:
        for col_name in WEEKDAY_COLS:
            day_num, _code = row["cells"][col_name]
            if day_num is not None:
                cursor = date(parsed["start_year"], parsed["start_month"], day_num)
                break
        if cursor:
            break
    if cursor is None:
        raise CalendarParseError("couldn't find a starting date anywhere in the calendar grid")

    sem_start = cursor
    holiday_dates = []
    teaching_dates = []
    isa1_dates, isa2_dates = [], []
    lwd_date = None
    sem_end = cursor

    for row in rows:
        for col_name in WEEKDAY_COLS:
            day_num, code = row["cells"][col_name]
            if day_num is not None or code is not None:
                if day_num is not None and cursor.day != day_num:
                    warnings.append(
                        f"week {row['week']} {col_name}: expected day {cursor.day}, PDF shows {day_num} "
                        "(kept the calculated date)"
                    )
                sem_end = max(sem_end, cursor)
                code_u = (code or "").upper()
                is_weekend = cursor.weekday() >= 5  # Sat=5, Sun=6 -- per instructions, always non-working
                is_holiday = code is not None and code.strip().upper() == holiday_code.upper()
                if is_holiday:
                    holiday_dates.append(cursor)
                if lwd_code.upper() in code_u:
                    lwd_date = cursor
                if isa1_code.replace(" ", "") in code_u.replace(" ", ""):
                    isa1_dates.append(cursor)
                if isa2_code.replace(" ", "") in code_u.replace(" ", ""):
                    isa2_dates.append(cursor)
                # Per instruction, holidays are NOT excluded from the teaching
                # calendar -- they're kept as ordinary working/teaching days.
                # is_holiday is still tracked (holiday_dates below) purely
                # for display/reference, it just no longer removes the date
                # from teaching_dates.
                if not is_weekend:
                    teaching_dates.append(cursor)
            cursor += timedelta(days=1)
            if cursor.weekday() == 6:  # Sunday never appears as a grid column -- skip straight to Monday
                cursor += timedelta(days=1)

    if lwd_date is None:
        warnings.append("no 'LWD' (Last Working Day) marker found -- using the full calendar range instead")
    else:
        teaching_dates = [d for d in teaching_dates if d <= lwd_date]

    # ISA weeks are exam windows, not lecture days -- students are sitting
    # exams, so those dates (even though they're plain Mon-Fri, non-"H" days)
    # must come back out of the teaching calendar. They're still reported
    # separately as isa1_start/end and isa2_start/end for the checkpoint
    # markers in the generated schedule.
    isa_blocked = set()
    if isa1_dates:
        isa_blocked.update(d for d in teaching_dates if min(isa1_dates) <= d <= max(isa1_dates))
    if isa2_dates:
        isa_blocked.update(d for d in teaching_dates if min(isa2_dates) <= d <= max(isa2_dates))
    teaching_dates = [d for d in teaching_dates if d not in isa_blocked]

    return {
        "sem_start": sem_start,
        "sem_end": sem_end,
        "lwd_date": lwd_date,
        "isa1_start": min(isa1_dates) if isa1_dates else None,
        "isa1_end": max(isa1_dates) if isa1_dates else None,
        "isa2_start": min(isa2_dates) if isa2_dates else None,
        "isa2_end": max(isa2_dates) if isa2_dates else None,
        "holiday_dates": sorted(holiday_dates),
        "teaching_dates": sorted(set(teaching_dates)),
        "warnings": warnings,
    }


def extract_working_days_from_pdf(pdf_file) -> dict:
    """Convenience one-shot: parse + compute in a single call."""
    parsed = parse_calendar_grid(pdf_file)
    return compute_working_days(parsed)


def filter_teaching_weekdays(teaching_dates: list, classes_per_week: int) -> list:
    """
    Narrows the calendar-derived teaching dates down to a specific course's
    class days, e.g. classes_per_week=3 -> keep only Mon/Tue/Wed of each
    week. classes_per_week=5 (the default) keeps every Mon-Fri date as-is.
    """
    n = max(1, min(int(classes_per_week or 5), 5))
    keep_weekdays = set(range(n))  # Mon=0 ... 
    return [d for d in teaching_dates if d.weekday() in keep_weekdays]
