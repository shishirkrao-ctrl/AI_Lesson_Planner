"""
Packing units/topics into numbered classes and slotting in ISA windows +
buffer days. No Streamlit calls in this module — pure data shaping, used by
results.py's render_schedule().
"""
import math
from datetime import date

import pandas as pd

from .timeline import pack_fields_into_classes

BANANA_LABEL = "Banana Problem"
ORANGE_LABEL = "Orange Problem"
JACKFRUIT_LABEL = "Jackfruit Problem"


def _unit_percentages(unit_totals_df: pd.DataFrame) -> tuple:
    """
    Returns ({unit: unit_pct}, {unit: cumulative_pct}) where unit_pct is
    that unit's share of the total lecture hours across all units (the
    "% Syllabus" column) and cumulative_pct is the running total in unit
    order (the "Cum %" column) -- same idea as the plain-percentage columns
    in the reference lesson-plan table format.
    """
    unit_pct, cum_pct = {}, {}
    if unit_totals_df.empty:
        return unit_pct, cum_pct

    total_hours = unit_totals_df["Total Hours"].sum()
    running = 0.0
    for _, row in unit_totals_df.iterrows():
        pct = (row["Total Hours"] / total_hours * 100) if total_hours else 0.0
        running += pct
        unit_pct[row["Unit"]] = round(pct)
        cum_pct[row["Unit"]] = round(running)
    return unit_pct, cum_pct


def compute_unit_class_blocks(topic_hours_df: pd.DataFrame, minutes_per_class: float = 60.0) -> list:
    """
    Packs each unit's topics on its OWN fresh minute timeline so every unit
    starts on a clean class boundary. Topics within a unit still blend
    across class boundaries as before.

    Returns an ordered list of {"unit", "n_classes", "class_topics", "class_tb"}
    where class_topics/class_tb are lists of strings, one per class, for that
    unit (class_tb holds the "Pg N" textbook references). Assumes
    topic_hours_df's rows are grouped by unit (contiguous), which is how
    build_hours_table produces it.
    """
    blocks = []
    current_unit = None
    current_rows = []

    def flush(unit_name, rows):
        class_fields, n_classes = pack_fields_into_classes(rows, minutes_per_class, fields=["Topic", "TB"])
        blocks.append(
            {
                "unit": unit_name,
                "n_classes": n_classes,
                "class_topics": class_fields["Topic"],
                "class_tb": class_fields["TB"],
                "class_row_type": ["lecture"] * n_classes,
            }
        )

    for row in topic_hours_df.to_dict("records"):
        if current_unit is None:
            current_unit, current_rows = row["Unit"], [row]
        elif row["Unit"] == current_unit:
            current_rows.append(row)
        else:
            flush(current_unit, current_rows)
            current_unit, current_rows = row["Unit"], [row]
    if current_unit is not None:
        flush(current_unit, current_rows)
    return blocks


def _append_special_sessions(blocks: list) -> list:
    """
    Every unit gets a trailing "Banana Problem" practice session, and every
    2nd unit (after unit 2, 4, 6, ...) additionally gets a trailing "Orange
    Problem" session right before it -- but both must fit WITHIN the unit's
    own hour-based class count, not extend it. A unit whose topics add up to
    14 hrs (= 14 classes at 60 min/class) still only occupies 14 classes
    total after Banana (and Orange, if applicable) are added -- the last one
    or two of those classes are converted into the special-session rows
    instead of new classes being appended on top.

    This means the trailing class(es) that would otherwise have held topic
    content are swapped: the last class becomes Banana Problem (Orange
    Problem, on a 2nd unit, takes the class immediately before it). If a
    unit is too short to hold both without dropping any topic content (fewer
    classes than special sessions needed), it's extended by just the
    shortfall so nothing is silently lost.

    These stay folded into the unit's own n_classes either way, so they
    behave exactly like the rest of that unit's classes for every purpose
    downstream: they still count toward how many classes the unit needs to
    fit before the next ISA checkpoint (deferred as a whole, along with the
    unit, if they don't fit), they land in the same week/session numbering,
    and they're tagged with their own row_type ("banana"/"orange") purely so
    the table can style them differently from a normal lecture row.
    """
    for i, block in enumerate(blocks, start=1):
        # Order matters: Banana is always last, Orange (on 2nd units) sits
        # in the class right before it.
        specials = [(ORANGE_LABEL, "orange")] if i % 2 == 0 else []
        specials.append((BANANA_LABEL, "banana"))

        n_special = len(specials)
        n = block["n_classes"]
        if n < n_special:
            # Not enough classes in the unit to hold the specials without
            # dropping topic content -- extend by just the shortfall.
            shortfall = n_special - n
            for _ in range(shortfall):
                block["class_topics"].append("-")
                block["class_tb"].append("-")
                block["class_row_type"].append("lecture")
            block["n_classes"] += shortfall
            n = block["n_classes"]

        start_idx = n - n_special
        for offset, (label, row_type) in enumerate(specials):
            idx = start_idx + offset
            block["class_topics"][idx] = label
            block["class_tb"][idx] = "-"
            block["class_row_type"][idx] = row_type
    return blocks


def build_lesson_plan_rows(
    topic_hours_df: pd.DataFrame,
    unit_totals_df: pd.DataFrame,
    minutes_per_class: float,
    checkpoints: list,
    classes_per_week: int = 5,
    n_teaching_days: int = None,
) -> tuple:
    """
    Lays units out class-by-class (see compute_unit_class_blocks), but no
    unit is ever allowed to straddle or start inside an ISA window: whichever
    unit doesn't fully fit before a checkpoint gets deferred -- together with
    every unit after it -- to start right after that ISA, and whatever gap is
    left over beforehand is filled with explicit Buffer rows. Shaped for the
    Week / Session / Unit / Reference / Topics / % Syllabus / Cum % table
    format: each row
    also carries a Week number, its Unit's "% Syllabus" and "Cum %" (shown
    only on that unit's first row, like a merged cell), and a row_type of
    "lecture" | "buffer" | "isa" | "banana" | "orange" | "jackfruit" so the
    UI can style rows differently.

    Every unit gets one trailing "Banana Problem" session, every 2nd unit
    additionally gets a trailing "Orange Problem" session right before it --
    both carved out of that unit's own hour-based class count rather than
    added on top of it (see _append_special_sessions) -- and if
    n_teaching_days is given and there are
    teaching days left over after everything else has been scheduled, those
    leftover sessions at the very end of the term are filled in as
    "Jackfruit Problem" rows instead of being left unscheduled.

    Returns (rows, total_classes_used) where rows is a list of dicts:
      {"week", "session", "unit", "ref", "topics", "unit_pct", "cum_pct", "row_type"}
    """
    blocks = compute_unit_class_blocks(topic_hours_df, minutes_per_class)
    blocks = _append_special_sessions(blocks)
    unit_pct_map, cum_pct_map = _unit_percentages(unit_totals_df)

    classes_per_week = int(classes_per_week) if classes_per_week else 5
    if classes_per_week <= 0:
        classes_per_week = 5

    events = []
    content_end = 0
    unit_i = 0
    for idx, label, s, e in checkpoints:
        while unit_i < len(blocks):
            candidate_end = content_end + blocks[unit_i]["n_classes"]
            if candidate_end <= idx:
                events.append(("unit", unit_i))
                content_end = candidate_end
                unit_i += 1
            else:
                break
        gap = idx - content_end
        if gap > 0:
            events.append(("buffer", gap))
            content_end = idx
        events.append(("isa", label, s, e))
    for j in range(unit_i, len(blocks)):
        events.append(("unit", j))
        content_end += blocks[j]["n_classes"]

    rows = []
    class_no = 0
    for ev in events:
        if ev[0] == "unit":
            block = blocks[ev[1]]
            unit_name = block["unit"]
            first_row = True
            for topics, tb, row_type in zip(
                block["class_topics"], block["class_tb"], block["class_row_type"]
            ):
                class_no += 1
                rows.append(
                    {
                        "week": math.ceil(class_no / classes_per_week),
                        "session": class_no,
                        "unit": unit_name if first_row else "",
                        "ref": tb,
                        "topics": topics,
                        "unit_pct": f"{unit_pct_map.get(unit_name, 0)}%" if first_row else "",
                        "cum_pct": f"{cum_pct_map.get(unit_name, 0)}%" if first_row else "",
                        "row_type": row_type,
                    }
                )
                first_row = False
        elif ev[0] == "buffer":
            for _ in range(ev[1]):
                class_no += 1
                rows.append(
                    {
                        "week": math.ceil(class_no / classes_per_week),
                        "session": class_no,
                        "unit": "",
                        "ref": "-",
                        "topics": "Buffer — revision / catch-up",
                        "unit_pct": "",
                        "cum_pct": "",
                        "row_type": "buffer",
                    }
                )
        else:  # isa marker — doesn't consume a class/session number
            _, label, s, e = ev
            week = math.ceil(max(class_no, 1) / classes_per_week)
            rows.append(
                {
                    "week": week,
                    "session": "ISA",
                    "unit": "",
                    "ref": "-",
                    "topics": f"{label} \u2014 {s} \u2192 {e}",
                    "unit_pct": "",
                    "cum_pct": "",
                    "row_type": "isa",
                }
            )

    # Anything left over at the very end of the term -- teaching days beyond
    # every unit's classes + Banana/Orange sessions -- gets filled in as
    # Jackfruit Problem sessions instead of being left blank.
    if n_teaching_days is not None and class_no < n_teaching_days:
        for _ in range(n_teaching_days - class_no):
            class_no += 1
            rows.append(
                {
                    "week": math.ceil(class_no / classes_per_week),
                    "session": class_no,
                    "unit": "",
                    "ref": "-",
                    "topics": JACKFRUIT_LABEL,
                    "unit_pct": "",
                    "cum_pct": "",
                    "row_type": "jackfruit",
                }
            )

    return rows, class_no


def merge_lab_rows_into_schedule(
    theory_rows: list, lab_schedule: list, labs_per_week: int, n_weeks: int
) -> list:
    """
    Folds lab periods into the SAME continuous session count as the theory
    schedule -- one combined table, one running Session number -- instead of
    the lab having its own parallel numbering. Within a week, theory rows
    keep their existing order and their session numbers just continue
    counting up; then that week's lab periods (all `labs_per_week` of them,
    since one lab exercise runs across the full week's lab slots -- see
    the module docstring below) are collapsed into a SINGLE row occupying
    the next `labs_per_week` session numbers, shown as a range in "Session"
    (e.g. "4-5"; a single number if labs_per_week is 1) and labelled
    "LAB 1", "LAB 2", ... in "Topics" (that counter increments once per
    lab week, not once per period). Within a week, Lab always shows before
    Buffer, which always shows before ISA (ISA rows don't consume a session
    number and pass through unchanged).

    Cycles are no longer needed for content -- the "Topics" cell is just the
    "LAB N" label -- but a non-empty lab_schedule (lab topics were actually
    found in the syllabus) is still required to turn labs on at all; the
    "Reference Book & Chapter #" column is left blank for lab rows, since a
    merged lab block isn't tied to a single textbook reference the way a
    theory topic is.

    If lab_schedule/labs_per_week/n_weeks make labs a no-op (no lab
    component, no lab topics found, or 0 labs/week configured),
    theory_rows is returned as-is with its session numbers untouched.
    """
    labs_per_week = int(labs_per_week) if labs_per_week else 0
    n_weeks = int(n_weeks) if n_weeks else 0
    if labs_per_week <= 0 or not lab_schedule or n_weeks <= 0:
        return list(theory_rows)

    by_week = {}
    for r in theory_rows:
        by_week.setdefault(r["week"], []).append(r)
    max_week = max([n_weeks] + list(by_week.keys()))

    result = []
    session_no = 0
    lab_week_no = 0
    for week in range(1, max_week + 1):
        week_rows = by_week.get(week, [])
        # Both Buffer and ISA rows are held back so Lab always shows first
        # within a week, then Buffer, then ISA last; every other row type
        # keeps its original relative order.
        main_rows = [r for r in week_rows if r["row_type"] not in ("buffer", "isa")]
        buffer_rows = [r for r in week_rows if r["row_type"] == "buffer"]
        isa_rows = [r for r in week_rows if r["row_type"] == "isa"]

        for r in main_rows:
            new_r = dict(r)
            if r["row_type"] in ("lecture", "buffer", "banana", "orange", "jackfruit"):
                session_no += 1
                new_r["session"] = session_no
            result.append(new_r)
        if week <= n_weeks:
            start = session_no + 1
            session_no += labs_per_week
            session_label = f"{start}-{session_no}" if labs_per_week > 1 else str(start)
            lab_week_no += 1
            result.append(
                {
                    "week": week,
                    "session": session_label,
                    "unit": "Lab",
                    "ref": "",
                    "topics": f"LAB {lab_week_no}",
                    "unit_pct": "",
                    "cum_pct": "",
                    "row_type": "lab",
                }
            )
        for r in buffer_rows:
            new_r = dict(r)
            session_no += 1
            new_r["session"] = session_no
            result.append(new_r)
        for r in isa_rows:
            result.append(dict(r))
    return result


def isa_marker_class_index(teaching_dates: list, isa_start: date) -> int:
    """How many classes (teaching dates) fall strictly before isa_start.
    The ISA-week marker gets inserted right after that many classes."""
    if isa_start is None:
        return None
    return sum(1 for d in teaching_dates if d < isa_start)
