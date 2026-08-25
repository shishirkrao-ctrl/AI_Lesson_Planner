"""
Page config, CSS injection, constants, and session state.

Anything that needs to run once at startup (st.set_page_config, CSS) or
that other modules read/write as shared state (st.session_state) lives here
so there is a single source of truth for "what state does this app have".
"""
from pathlib import Path

import streamlit as st

# =============================================================================
# PAGE CONFIG + STYLES
# =============================================================================


def configure_page() -> None:
    """Must run once, before any other st.* call. Call this first from app.py."""
    st.set_page_config(
        page_title="Lesson Planner",
        page_icon="▍",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    _inject_css()


def _inject_css() -> None:
    css_path = Path(__file__).resolve().parent.parent / "styles.css"
    if css_path.exists():
        try:
            st.markdown(f"<style>{css_path.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)
        except OSError:
            pass


# =============================================================================
# CONSTANTS
# =============================================================================

DEFAULT_UNIT_HOURS = 12.0
STEP_LABELS = [
    (1, "course details"),
    (2, "schedule"),
    (3, "source files"),
    (4, "hour targets"),
    (5, "lesson plan"),
]

# =============================================================================
# SESSION STATE
# =============================================================================

_DEFAULTS = {
    "skeleton": None,
    "sections": None,
    "full_json": None,
    "error": None,
    "source_signature": None,
    "uploader_version": 0,
    "schedule_config": None,
    "course_info": None,
    # Lab topics are extracted straight out of the (single) uploaded
    # syllabus -- there is no separate lab syllabus file anymore.
    "lab_topics": None,
    "lab_schedule": None,
}


def init_session_state() -> None:
    """Populate any session_state keys this app relies on that aren't set yet."""
    for k, v in _DEFAULTS.items():
        st.session_state.setdefault(k, v)


def reset_state(keep_course_info: bool = False, keep_schedule_config: bool = False) -> None:
    version = st.session_state.get("uploader_version", 0) + 1
    saved_course_info = st.session_state.get("course_info") if keep_course_info else None
    saved_schedule_config = st.session_state.get("schedule_config") if keep_schedule_config else None
    for k, v in _DEFAULTS.items():
        st.session_state[k] = v
    st.session_state["uploader_version"] = version
    if keep_course_info:
        st.session_state["course_info"] = saved_course_info
    if keep_schedule_config:
        st.session_state["schedule_config"] = saved_schedule_config


def current_step() -> int:
    if st.session_state["full_json"]:
        return 5
    if st.session_state["skeleton"]:
        return 4
    if st.session_state["schedule_config"]:
        return 3
    if st.session_state["course_info"]:
        return 2
    return 1
