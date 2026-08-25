"""Step 5 — render the finished lesson plan: summary metrics, topics-by-unit
breakdown, and the dated class-by-class schedule (with ISA/buffer rows). For
5-credit courses, the lab sessions built from the lab topics extracted
straight out of the same syllabus are folded into that SAME schedule table
as LAB1, LAB2, ... rows -- courses with no lab component show no lab rows
at all."""
import html
import math

import pandas as pd
import streamlit as st

from .data_helpers import build_hours_table
from .pdf_export import build_lesson_plan_pdf
from .schedule_builder import (
    build_lesson_plan_rows,
    isa_marker_class_index,
    merge_lab_rows_into_schedule,
)


def render_metrics(topic_df: pd.DataFrame, unit_totals_df: pd.DataFrame) -> None:
    n_units = unit_totals_df.shape[0]
    n_topics = topic_df.shape[0]
    total_hours = topic_df["Lecture Hours"].sum() if not topic_df.empty else 0

    metrics = [("units", n_units), ("topics", n_topics), ("total hours", f"{total_hours:g}")]
    cols = st.columns(3)
    for col, (label, value) in zip(cols, metrics):
        with col:
            st.markdown(
                f'<div class="sh-metric-tint"><div class="sh-metric-label">{label}</div>'
                f'<div class="sh-metric-value">{value}</div></div>',
                unsafe_allow_html=True,
            )


def render_unit_breakdown(sections: list) -> None:
    for section in sections:
        total_hours = sum(t["hours"] for t in section["topics"])
        with st.expander(
            f"{section['heading']}  \u00b7  {len(section['topics'])} topics  \u00b7  {total_hours:g} hrs"
        ):
            table_df = pd.DataFrame(
                [{"Topic": t["name"], "Minutes": t["hours"] * 60} for t in section["topics"]]
            )
            st.dataframe(
                table_df,
                hide_index=True,
                width="stretch",
                column_config={
                    "Topic": st.column_config.TextColumn("Topic"),
                    "Minutes": st.column_config.NumberColumn("Minutes", format="%.1f min"),
                },
            )


def _row_style(row_type: str) -> str:
    if row_type == "isa":
        return (
            "background: var(--sh-red-tint); color: #8F2E2C; font-weight: 600;"
        )
    if row_type == "buffer":
        return "background: var(--sh-primary-tint); color: var(--sh-muted); font-style: italic;"
    if row_type == "lab":
        return "background: var(--sh-cobalt-tint); font-weight: 600;"
    if row_type == "banana":
        return "background: #FFF6D6; color: #8A6D1D; font-style: italic;"
    if row_type == "orange":
        return "background: #FFE3C6; color: #8A4B1D; font-style: italic;"
    if row_type == "jackfruit":
        return "background: #E4F1DA; color: #2F5D34; font-style: italic;"
    return ""


def _render_plan_table(rows: list) -> None:
    """Renders the Week / Session / Unit / Reference Book & Chapter # /
    Topics / % Syllabus / Cum % table, with ISA and Buffer rows visually
    called out — same column layout as the reference lesson-plan format."""
    head = (
        '<table style="width:100%; border-collapse:collapse; font-size:0.82rem; '
        'font-family: var(--sh-sans); color: var(--sh-ink);">'
        '<thead><tr style="background: var(--sh-cobalt-tint); text-align:left; '
        'border-bottom: 1px solid var(--sh-border);">'
        '<th style="padding:8px; border-right:1px solid var(--sh-border);">Week</th>'
        '<th style="padding:8px; border-right:1px solid var(--sh-border);">Session</th>'
        '<th style="padding:8px; border-right:1px solid var(--sh-border);">Unit</th>'
        '<th style="padding:8px; border-right:1px solid var(--sh-border);">Reference Book &amp; Chapter #</th>'
        '<th style="padding:8px; border-right:1px solid var(--sh-border);">Topics</th>'
        '<th style="padding:8px; border-right:1px solid var(--sh-border); text-align:center;">% Syllabus</th>'
        '<th style="padding:8px; text-align:center;">Cum %</th>'
        "</tr></thead><tbody>"
    )
    body_rows = []
    for r in rows:
        style = _row_style(r["row_type"])
        # ISA rows don't show a Week number -- they sit between weeks (or
        # span the boundary), so a specific week value would be misleading.
        week_display = "" if r["row_type"] == "isa" else r["week"]
        body_rows.append(
            f'<tr style="border-bottom:1px solid var(--sh-border); {style}">'
            f'<td style="padding:6px 8px; border-right:1px solid var(--sh-border); text-align:center;">{week_display}</td>'
            f'<td style="padding:6px 8px; border-right:1px solid var(--sh-border); text-align:center;">{html.escape(str(r["session"]))}</td>'
            f'<td style="padding:6px 8px; border-right:1px solid var(--sh-border);">{html.escape(r["unit"])}</td>'
            f'<td style="padding:6px 8px; border-right:1px solid var(--sh-border);">{html.escape(r["ref"])}</td>'
            f'<td style="padding:6px 8px; border-right:1px solid var(--sh-border);">{html.escape(r["topics"])}</td>'
            f'<td style="padding:6px 8px; border-right:1px solid var(--sh-border); text-align:center;">{html.escape(r["unit_pct"])}</td>'
            f'<td style="padding:6px 8px; text-align:center;">{html.escape(r["cum_pct"])}</td>'
            "</tr>"
        )
    table_html = head + "".join(body_rows) + "</tbody></table>"
    st.markdown(
        f'<div style="border:1px solid var(--sh-border); border-radius: var(--sh-radius-sm); '
        f'overflow:hidden; overflow-x:auto;">{table_html}</div>',
        unsafe_allow_html=True,
    )


def render_schedule(topic_df: pd.DataFrame, unit_totals_df: pd.DataFrame) -> pd.DataFrame:
    schedule_config = st.session_state.get("schedule_config") or {}
    minutes_per_class = schedule_config.get("minutes_per_class", 60.0)
    classes_per_week = schedule_config.get("classes_per_week", 5)
    teaching_dates = schedule_config.get("teaching_dates", [])
    isa1_start = schedule_config.get("isa1_start")
    isa1_end = schedule_config.get("isa1_end")
    isa2_start = schedule_config.get("isa2_start")
    isa2_end = schedule_config.get("isa2_end")

    # Lab rows only ever get folded in for courses flagged with a lab
    # component (see course_info.py — 5-credit courses). Everything else
    # renders exactly as before, theory-only.
    course_info = st.session_state.get("course_info") or {}
    has_lab = bool(course_info.get("has_lab"))
    lab_schedule = st.session_state.get("lab_schedule") or []
    labs_per_week = schedule_config.get("labs_per_week")

    st.markdown('<div class="sh-card-title">Class-by-class schedule</div>', unsafe_allow_html=True)
    lab_hint = (
        " Lab periods for this course are folded into the same running Session "
        "count — a week's lab slots collapse into one row (e.g. \"4-5\") labelled "
        "<b>LAB 1</b>, <b>LAB 2</b>, etc."
        if has_lab
        else ""
    )
    st.markdown(
        f'<p class="sh-hint">Each row is one {minutes_per_class:g}-minute session, numbered in teaching '
        "order (weekends are skipped, but public holidays are kept as working days). No unit starts "
        "inside or straddling an ISA window — if a unit finishes early, the leftover working days show "
        "as Buffer rows right here in the table, and the next unit starts fresh right after the ISA. "
        "Every unit ends with a <b>Banana Problem</b> session, every 2nd unit additionally ends with an "
        "<b>Orange Problem</b> session right before it — both fit within that unit's own allotted hours "
        "rather than adding extra classes on top, and any teaching days left over at the end of the term are filled "
        "in as <b>Jackfruit Problem</b> sessions. Topics with no match in any uploaded textbook are "
        f"referenced as <b>PESU Academy</b>.{lab_hint}</p>",
        unsafe_allow_html=True,
    )

    checkpoints = []
    idx1 = isa_marker_class_index(teaching_dates, isa1_start)
    if idx1 is not None:
        checkpoints.append((idx1, "ISA 1", isa1_start, isa1_end))
    idx2 = isa_marker_class_index(teaching_dates, isa2_start)
    if idx2 is not None:
        checkpoints.append((idx2, "ISA 2", isa2_start, isa2_end))
    checkpoints.sort(key=lambda c: c[0])

    rows, n_classes = build_lesson_plan_rows(
        topic_df,
        unit_totals_df,
        minutes_per_class,
        checkpoints,
        classes_per_week,
        n_teaching_days=len(teaching_dates) if teaching_dates else None,
    )

    # Fold LAB 1, LAB 2, ... rows into the same table, sharing the theory
    # schedule's own running Session count (a week's lab periods collapse
    # into a single row spanning that many session numbers). Subjects with
    # no lab component (has_lab False) never reach this branch, so they get
    # no lab rows at all, per the original request.
    lab_note = None
    if has_lab:
        if not lab_schedule:
            lab_note = "No lab section was found in the uploaded syllabus, so no lab rows could be added."
        elif not labs_per_week:
            lab_note = "Set the number of labs per week above to include the lab sessions in this table."
        else:
            n_weeks = max(
                math.ceil(len(teaching_dates) / classes_per_week) if classes_per_week else 0,
                math.ceil(n_classes / classes_per_week) if classes_per_week else 0,
            )
            rows = merge_lab_rows_into_schedule(rows, lab_schedule, labs_per_week, n_weeks)

    display_df = pd.DataFrame(
        [
            {
                "Week": "" if r["row_type"] == "isa" else r["week"],
                "Session": r["session"],
                "Unit": r["unit"],
                "Reference Book & Chapter #": r["ref"],
                "Topics": r["topics"],
                "% Syllabus": r["unit_pct"],
                "Cum %": r["cum_pct"],
            }
            for r in rows
        ]
    )

    if display_df.empty:
        st.markdown('<p class="sh-hint">No minutes to schedule yet.</p>', unsafe_allow_html=True)
        return display_df, n_classes

    if n_classes > len(teaching_dates):
        short_by = n_classes - len(teaching_dates)
        st.markdown(
            f'<div class="sh-error"><b>heads up:</b> the topics (plus any buffer) need {n_classes} '
            f"classes but the semester only has {len(teaching_dates)} teaching day(s) available — "
            f"{short_by} class(es) fall past the semester end date. Increase class length/classes per "
            "week, extend the semester, or trim unit hour targets.</div>",
            unsafe_allow_html=True,
        )

    if lab_note:
        st.markdown(f'<p class="sh-hint">{lab_note}</p>', unsafe_allow_html=True)

    _render_plan_table(rows)

    # Just the single PDF export action here -- matches the React results
    # screen, which shows the table plus one "download as PDF" button and
    # nothing else (no CSV export, no row-type count summary).
    course_info = st.session_state.get("course_info") or {}
    st.markdown('<div style="margin-top:1rem;"></div>', unsafe_allow_html=True)
    try:
        pdf_bytes = build_lesson_plan_pdf(
            course_name=course_info.get("course_name", ""),
            course_code=course_info.get("course_code", ""),
            credits=course_info.get("credits", 3),
            department=None,
            documented_by=course_info.get("documented_by") or None,
            schedule_rows=rows,
        )
        st.download_button(
            "download as PDF",
            data=pdf_bytes,
            file_name=f"{course_info.get('course_code', 'lesson_plan')}_lesson_plan.pdf".replace(" ", "_"),
            mime="application/pdf",
            type="primary",
            key="download_schedule_pdf",
        )
    except Exception as e:
        st.markdown(f'<p class="text-red" style="color:var(--sh-red); font-size:0.85rem;">couldn\'t generate the PDF: {html.escape(str(e))}</p>', unsafe_allow_html=True)
    return display_df, n_classes


def render_results() -> None:
    sections = st.session_state["sections"]
    topic_df, unit_totals_df = build_hours_table(sections)

    with st.container(border=True):
        st.markdown('<div class="sh-card-title">Lesson plan output</div>', unsafe_allow_html=True)
        render_metrics(topic_df, unit_totals_df)

    with st.container(border=True):
        st.markdown('<div class="sh-card-title">Topics by unit</div>', unsafe_allow_html=True)
        render_unit_breakdown(sections)

    with st.container(border=True):
        render_schedule(topic_df, unit_totals_df)
