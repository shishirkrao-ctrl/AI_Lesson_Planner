"""Step 2 — upload the institution's academic calendar PDF and turn it into
the concrete list of teaching dates used later by results.py.

No more manually typing semester start/end or ISA start dates: the calendar
PDF's own grid (Week# / Month / Mon..Sat / # of working days / Activities)
already contains everything we need, so we parse it directly. Saturdays and
Sundays are always treated as non-working, and nothing after the calendar's
"LWD" (Last Working Day) marker is counted, regardless of what the PDF shows
after it (ESA, results, etc.).
"""
import math

import streamlit as st

from .calendar_extract import (
    CalendarParseError,
    extract_working_days_from_pdf,
    filter_teaching_weekdays,
)


def render_schedule_card() -> None:
    existing = st.session_state.get("schedule_config")
    has_lab = bool((st.session_state.get("course_info") or {}).get("has_lab"))

    with st.container(border=True):
        st.markdown('<div class="sh-card-title">Semester schedule details</div>', unsafe_allow_html=True)
        st.markdown(
            '<p class="sh-hint">Upload the academic calendar PDF and we\'ll read the semester '
            "dates, holidays, and ISA windows straight from it — no dates to type in. "
            "Saturdays and Sundays are always treated as non-teaching days, and nothing after the "
            "calendar's Last Working Day (LWD) is counted.</p>",
            unsafe_allow_html=True,
        )

        defaults = existing or {}

        calendar_file = st.file_uploader(
            "Academic calendar PDF", type=["pdf"], key="calendar_pdf_uploader"
        )

        with st.form("schedule_form", border=False):
            if has_lab:
                col1, col2, col3 = st.columns(3)
                with col1:
                    minutes_per_class = st.number_input(
                        "Minutes per class",
                        min_value=5.0,
                        step=5.0,
                        value=float(defaults.get("minutes_per_class", 60.0)),
                    )
                with col2:
                    classes_per_week = st.number_input(
                        "Number of classes per week (Mon-Fri only)",
                        min_value=1,
                        max_value=5,
                        step=1,
                        value=int(defaults.get("classes_per_week", 4)),
                    )
                with col3:
                    labs_per_week = st.number_input(
                        "Number of labs per week",
                        min_value=0,
                        max_value=7,
                        step=1,
                        value=int(defaults.get("labs_per_week", 2)),
                    )
            else:
                col1, col2 = st.columns(2)
                with col1:
                    minutes_per_class = st.number_input(
                        "Minutes per class",
                        min_value=5.0,
                        step=5.0,
                        value=float(defaults.get("minutes_per_class", 60.0)),
                    )
                with col2:
                    classes_per_week = st.number_input(
                        "Number of classes per week (Mon-Fri only)",
                        min_value=1,
                        max_value=5,
                        step=1,
                        value=int(defaults.get("classes_per_week", 5)),
                    )
                # Not a 5-credit course -> no lab component, so we don't ask
                # for a labs-per-week count at all.
                labs_per_week = 0

            submitted = st.form_submit_button("Next", type="primary")

        if submitted:
            if calendar_file is None:
                st.session_state["error"] = "upload the academic calendar PDF before submitting."
            else:
                try:
                    extracted = extract_working_days_from_pdf(calendar_file)
                except CalendarParseError as e:
                    st.session_state["error"] = f"couldn't read the academic calendar: {e}"
                    extracted = None
                except Exception as e:
                    st.session_state["error"] = f"couldn't parse the calendar PDF: {e}"
                    extracted = None

                if extracted is not None:
                    teaching_dates = filter_teaching_weekdays(
                        extracted["teaching_dates"], classes_per_week
                    )
                    st.session_state["schedule_config"] = {
                        "sem_start": extracted["sem_start"],
                        "sem_end": extracted["sem_end"],
                        "lwd_date": extracted["lwd_date"],
                        "isa1_start": extracted["isa1_start"],
                        "isa1_end": extracted["isa1_end"],
                        "isa2_start": extracted["isa2_start"],
                        "isa2_end": extracted["isa2_end"],
                        "minutes_per_class": minutes_per_class,
                        "classes_per_week": classes_per_week,
                        "labs_per_week": int(labs_per_week),
                        "holiday_dates": extracted["holiday_dates"],
                        "teaching_dates": teaching_dates,
                        "calendar_warnings": extracted["warnings"],
                    }
                    st.session_state["error"] = None
            st.rerun()

        if existing:
            n_teaching = len(existing.get("teaching_dates", []))
            minutes_per_class = existing.get("minutes_per_class", 60.0) or 60.0
            classes_per_week_existing = existing.get("classes_per_week") or 5
            labs_per_week_existing = int(existing.get("labs_per_week") or 0)
            n_weeks = math.ceil(n_teaching / classes_per_week_existing) if classes_per_week_existing else 0
            n_lab_sessions = n_weeks * labs_per_week_existing
            total_classes = n_teaching + n_lab_sessions
            total_hours = total_classes * minutes_per_class / 60.0
            lab_breakdown = (
                f' <span class="sh-hint" style="color:var(--sh-muted-2);">'
                f"({n_teaching} lecture + {n_lab_sessions} lab)</span>"
                if n_lab_sessions > 0
                else ""
            )
            st.markdown(
                f'<p class="sh-hint">Total classes available: <b>{total_classes}</b>{lab_breakdown} '
                f"&nbsp;|&nbsp; Total working hours: <b>{total_hours:g} hrs</b></p>",
                unsafe_allow_html=True,
            )
            st.markdown(
                f'<p class="sh-hint">Semester: <b>{existing["sem_start"]}</b> &rarr; '
                f'<b>{existing["sem_end"]}</b> (Last Working Day: <b>{existing.get("lwd_date") or "—"}</b>)</p>',
                unsafe_allow_html=True,
            )
            st.markdown(
                f'<p class="sh-hint">ISA 1: <b>{existing["isa1_start"] or "—"}</b> &rarr; '
                f'<b>{existing["isa1_end"] or "—"}</b> &nbsp;|&nbsp; '
                f'ISA 2: <b>{existing["isa2_start"] or "—"}</b> &rarr; <b>{existing["isa2_end"] or "—"}</b></p>',
                unsafe_allow_html=True,
            )
            if has_lab and existing.get("labs_per_week") is not None:
                st.markdown(
                    f'<p class="sh-hint">Labs per week: <b>{existing["labs_per_week"]}</b></p>',
                    unsafe_allow_html=True,
                )
            for w in existing.get("calendar_warnings") or []:
                st.markdown(f'<p class="sh-hint">&#9888; {w}</p>', unsafe_allow_html=True)
