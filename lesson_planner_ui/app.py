"""
Wires the individual step modules together into the page's main() flow.
This is the only module that reads session_state to decide which cards to
show and in what order — everything else just renders the card it's given.
"""
import streamlit as st

from .configure import render_configure_card
from .course_info import render_course_info_card
from .data_helpers import parse_json_sections
from .pipeline import render_error, run_pipeline
from .results import render_results
from .schedule_config import render_schedule_card
from .state import configure_page, init_session_state, reset_state
from .step_bar import render_step_bar
from .upload import handle_upload, render_upload_card


def main() -> None:
    configure_page()
    init_session_state()

    render_step_bar()

    st.markdown('<h1 class="sh-title">Turn a syllabus into a lesson plan</h1>', unsafe_allow_html=True)
    st.markdown(
        '<p class="sh-subtitle">Upload a syllabus (PDF) and its matching textbook. '
        "We'll structure the topics, locate each one in the textbook, score their difficulty "
        "straight from that page, and allocate hours per unit.</p>",
        unsafe_allow_html=True,
    )

    # Step 1 — course/subject details.
    render_course_info_card()

    # Step 2 — semester schedule details (calendar upload -> working hours).
    if st.session_state["course_info"]:
        render_schedule_card()

    has_lab = bool((st.session_state.get("course_info") or {}).get("has_lab"))

    # Step 3 — syllabus + textbook upload. Extraction only runs once the
    # user presses "Submit" on this card, not just because files are picked.
    if st.session_state["course_info"] and st.session_state["schedule_config"]:
        syllabus_input_type, syllabus_file, textbook_files, submitted = render_upload_card(has_lab=has_lab)

        ready = bool(syllabus_file and textbook_files)
        if submitted and ready:
            handle_upload(syllabus_input_type, syllabus_file, textbook_files, has_lab=has_lab)
        elif not ready and st.session_state["skeleton"] is not None:
            reset_state(keep_course_info=True, keep_schedule_config=True)
            st.rerun()

        if st.session_state["skeleton"]:
            unit_limits, generate_clicked = render_configure_card(st.session_state["skeleton"])
            if generate_clicked:
                data, lab_topics_out, err = run_pipeline(
                    st.session_state["skeleton"],
                    textbook_files,
                    unit_limits,
                    lab_topics=st.session_state.get("lab_topics"),
                )
                if err:
                    st.session_state["error"] = err
                else:
                    st.session_state["full_json"] = data
                    st.session_state["sections"] = parse_json_sections(data)
                    st.session_state["lab_schedule"] = lab_topics_out
                    st.session_state["error"] = None
                st.rerun()

    if st.session_state["error"]:
        render_error(st.session_state["error"])

    if st.session_state["full_json"]:
        render_results()

    st.markdown(
        '<div class="sh-footer">Lesson Planner &middot; syllabus &rarr; lesson plan</div>',
        unsafe_allow_html=True,
    )
