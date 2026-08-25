"""
Step 3 — upload the syllabus + textbook, and hand the syllabus off to the
backend extractors to build the topic "skeleton" (and, for 5-credit
courses, the lab session list).

This is the only module that calls into Extracting/, other than pipeline.py
which calls the textbook-processing side of the backend. There is no
lecture-notes PDF in this app: the textbook is the only source used to
locate each topic's page and grade its difficulty/lecture hours.

There is also no SEPARATE lab syllabus upload: the lab component (for
5-credit courses) is extracted straight out of the same syllabus file the
theory units come from -- see Extracting.PD_Extractor.generate_lab_syllabus_json_from_pdf.

Syllabus input is PDF-only -- the plain-text (.txt) upload path was removed.

Extraction only runs once the user presses "Submit" on this card -- selecting
files alone (or Streamlit re-rendering for an unrelated reason) does not
trigger a call to the backend extractors.
"""
import html

import streamlit as st

# --- backend (unchanged) ----------------------------------------------------
from Extracting.PD_Extractor import generate_syllabus_json_from_pdf, generate_lab_syllabus_json_from_pdf


def render_upload_card(has_lab: bool = False):
    with st.container(border=True):
        st.markdown('<div class="sh-card-title">Upload source files</div>', unsafe_allow_html=True)
        hint = "A syllabus (as PDF) plus one or more course textbooks."
        if has_lab:
            hint += (
                " This course carries 5 credits, so its lab session list is pulled "
                "straight out of this same syllabus — no separate lab file needed."
            )
        st.markdown(f'<p class="sh-hint">{hint}</p>', unsafe_allow_html=True)

        version = st.session_state["uploader_version"]

        syllabus_input_type = "PDF"

        col_syllabus, col_pdf = st.columns(2, gap="medium")
        with col_syllabus:
            syllabus_file = st.file_uploader(
                "syllabus pdf file", type=["pdf"], label_visibility="collapsed", key=f"syllabus_pdf_uploader_{version}"
            )
        with col_pdf:
            textbook_files = st.file_uploader(
                "textbook pdf(s)",
                type=["pdf"],
                accept_multiple_files=True,
                label_visibility="collapsed",
                key=f"textbook_uploader_{version}",
            )
            st.markdown(
                '<p class="sh-hint">Upload in order: the first file becomes T1, the second T2, '
                "and so on. References in the plan are tagged by that order.</p>",
                unsafe_allow_html=True,
            )

        st.markdown(
            '<p class="sh-hint">Each topic is matched to a page across all uploaded textbooks with a '
            "hybrid (semantic + keyword) local text search (no upload to Gemini for this step), and its "
            "difficulty/lecture hours are graded straight from that page's content. Topics with no match "
            "anywhere in the textbooks are labeled <b>PESU Academy</b>.</p>",
            unsafe_allow_html=True,
        )

        ready = bool(syllabus_file and textbook_files)
        if ready:
            chips = [
                f'<span class="sh-file-chip">&#10003; {html.escape(syllabus_file.name)} '
                f'<em>{round(syllabus_file.size / 1024, 1)} KB</em></span>',
            ]
            for i, tb in enumerate(textbook_files, start=1):
                chips.append(
                    f'<span class="sh-file-chip">&#10003; T{i}: {html.escape(tb.name)} '
                    f'<em>{round(tb.size / 1024, 1)} KB</em></span>'
                )
            st.markdown(f'<div class="sh-file-row">{"".join(chips)}</div>', unsafe_allow_html=True)
        else:
            st.markdown(
                '<p class="sh-hint">Add both the syllabus and at least one textbook PDF to continue.</p>',
                unsafe_allow_html=True,
            )

        submitted = st.button("Submit", type="primary", disabled=not ready, key=f"upload_submit_{version}")

    return syllabus_input_type, syllabus_file, textbook_files, submitted


def _normalize_skeleton(skeleton: dict) -> dict:
    """
    generate_syllabus_json() (TXT path) returns each unit's "Subtopics" as
    a flat list of topic-name strings, while generate_syllabus_json_from_pdf()
    (PDF path) returns a list of {"name", "difficulty", "lecture_hours"}
    dicts. process_syllabus() (backend, unchanged) expects the dict shape --
    feeding it plain strings is what causes
    "'str' object has no attribute 'get'". Normalize here, in the frontend
    glue code, so both syllabus paths hand the backend the same shape.
    """
    normalized = {}
    for unit_name, unit_data in skeleton.items():
        subtopics = unit_data.get("Subtopics", []) if isinstance(unit_data, dict) else []
        new_subtopics = [
            sub if isinstance(sub, dict) else {"name": sub, "difficulty": None, "lecture_hours": None}
            for sub in subtopics
        ]
        normalized[unit_name] = {"Subtopics": new_subtopics}
    return normalized


def handle_upload(syllabus_input_type, syllabus_file, textbook_files, has_lab: bool = False) -> None:
    """
    Builds the theory skeleton from `syllabus_file` as before, and -- for
    5-credit (`has_lab`) courses -- ALSO extracts the lab session list out
    of that SAME syllabus file (no separate lab upload/prompt).
    """
    textbook_files = textbook_files or []
    textbook_signature = tuple((tb.name, tb.size) for tb in textbook_files)
    signature = (syllabus_input_type, syllabus_file.name, syllabus_file.size, textbook_signature, has_lab)
    if st.session_state["source_signature"] == signature:
        return

    st.session_state["source_signature"] = signature
    st.session_state["sections"] = None
    st.session_state["full_json"] = None
    st.session_state["lab_schedule"] = None
    st.session_state["error"] = None

    try:
        skeleton = generate_syllabus_json_from_pdf(syllabus_file)
        lab_topics = generate_lab_syllabus_json_from_pdf(syllabus_file) if has_lab else []
        st.session_state["skeleton"] = _normalize_skeleton(skeleton)
        st.session_state["lab_topics"] = lab_topics
    except Exception as e:
        st.session_state["skeleton"] = None
        st.session_state["lab_topics"] = None
        st.session_state["error"] = f"couldn't parse the syllabus: {e}"
