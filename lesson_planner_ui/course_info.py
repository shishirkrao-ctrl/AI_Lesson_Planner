"""Step 1 — course/subject details form (name, code, credits -> has_lab,
optional documented-by). Field set matches the React CourseInfoCard."""
import html

import streamlit as st

from .state import reset_state


def render_course_info_card() -> None:
    existing = st.session_state.get("course_info")
    defaults = existing or {}

    with st.container(border=True):
        st.markdown('<div class="sh-card-title">Course details</div>', unsafe_allow_html=True)
        st.markdown(
            '<p class="sh-hint">A few basics before we get into the syllabus. Courses with 5 '
            "credits are treated as having a lab component.</p>",
            unsafe_allow_html=True,
        )

        with st.form("course_info_form", border=False):
            col1, col2 = st.columns(2)
            with col1:
                course_name = st.text_input("Course name", value=defaults.get("course_name", ""))
            with col2:
                course_code = st.text_input("Course code", value=defaults.get("course_code", ""))
            col3, col4 = st.columns(2)
            with col3:
                credits = st.number_input(
                    "Number of credits",
                    min_value=1,
                    max_value=10,
                    step=1,
                    value=int(defaults.get("credits", 3)),
                )
            with col4:
                documented_by = st.text_input(
                    "Documented by (optional)",
                    value=defaults.get("documented_by", ""),
                    placeholder="e.g. Prof. Jane Doe, Dept of CSE",
                )
            submitted = st.form_submit_button("Next", type="primary")

        if submitted:
            if not course_name.strip() or not course_code.strip():
                st.session_state["error"] = "please fill in both the course name and course code."
            else:
                has_lab = int(credits) == 5
                new_info = {
                    "course_name": course_name.strip(),
                    "course_code": course_code.strip(),
                    "credits": int(credits),
                    "has_lab": has_lab,
                    "documented_by": documented_by.strip(),
                }
                # credit count changed the lab requirement -> source files collected
                # under the old assumption are no longer valid, start those over.
                # The schedule (step 1) doesn't depend on has_lab, so it's kept.
                if existing and existing.get("has_lab") != has_lab:
                    reset_state(keep_course_info=False, keep_schedule_config=True)
                st.session_state["course_info"] = new_info
                st.session_state["error"] = None
            st.rerun()

        if existing:
            lab_note = " &middot; includes lab component" if existing.get("has_lab") else ""
            st.markdown(
                f'<p class="sh-hint">&#10003; {html.escape(existing["course_name"])} '
                f'({html.escape(existing["course_code"])}) &middot; {existing["credits"]} credits'
                f"{lab_note}</p>",
                unsafe_allow_html=True,
            )
