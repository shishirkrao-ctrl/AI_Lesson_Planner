"""
Bridges the UI to the backend pipeline. There is no lecture-notes PDF
anywhere in this app anymore: the textbook(s) are the only source used to
locate each topic's page and to grade its difficulty/lecture hours.
"""
import html

import streamlit as st

# --- backend (unchanged) ----------------------------------------------------
from syllabus_processor import process_syllabus
from Extracting.TB_Extractor import (
    ground_topics_in_textbook,
    attach_textbook_pages,
)


def run_pipeline(skeleton: dict, textbook_files, unit_limits: dict, lab_topics: list = None):
    """
    textbook_files: list of Streamlit UploadedFile objects for the textbook
    PDF(s), in upload order (first -> T1, second -> T2, ...). A single
    UploadedFile is also accepted for back-compat.

    1. Extracts + embeds every textbook locally, together, into one shared
       vector store (Extracting/TB_Extractor.py) and retrieves, per topic,
       the best-matching page + excerpt across ALL of them via a HYBRID
       (dense vector + keyword re-rank) search -- no PDF is uploaded to
       Gemini for this step.
    2. Sends those excerpts (plain text) to Gemini so it can grade each
       topic's difficulty and estimate its lecture hours straight from the
       textbook (syllabus_processor.process_syllabus).
    3. Attaches each topic's textbook reference onto the result so
       data_helpers/schedule_builder can render the "Reference Book &
       Chapter #" column (e.g. "T2 - p.42 (PDF p.57)", or "PESU Academy"
       when a topic has no match in any uploaded textbook).
    4. Lab topics (5-credit course) are NOT matched against the textbook at
       all -- they're purely a count. schedule_builder.merge_lab_rows_into_schedule
       only checks whether the list is non-empty (to decide whether labs
       exist) and then labels each lab session generically as "LAB 1",
       "LAB 2", ... regardless of the actual topic names, so there's no
       textbook grounding step to run for them.

    Returns (data, lab_topics, error) where lab_topics is passed straight
    through unchanged (empty list when there are no lab topics).
    """
    try:
        with st.spinner("Reading the textbook(s) and matching them to each topic\u2026"):
            topic_context = ground_topics_in_textbook(skeleton, textbook_files)

        with st.spinner(
            "Grading topic difficulty from the textbook and compiling the lesson plan\u2026 this can take a minute."
        ):
            data = process_syllabus(skeleton_json=skeleton, topic_context=topic_context, unit_limits=unit_limits)
            data = attach_textbook_pages(data, topic_context)

        return data, (lab_topics or []), None

    except Exception as e:
        return None, [], str(e)


def render_error(message: str) -> None:
    st.markdown(
        f'<div class="sh-error"><b>generation failed.</b> {html.escape(message)} '
        f"Check your files and try again.</div>",
        unsafe_allow_html=True,
    )

