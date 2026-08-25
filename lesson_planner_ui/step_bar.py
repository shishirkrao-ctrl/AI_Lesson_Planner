"""Top-of-page step tracker, rendered as a row of pills (active/done/pending)
-- mirrors the React frontend's layout, which has no sidebar at all: the
step tracker sits above the title as a horizontal chip row instead of down
the side."""
import streamlit as st

from .state import STEP_LABELS, current_step


def render_step_bar() -> None:
    step = current_step()
    pills = []
    for num, label in STEP_LABELS:
        if num == step:
            cls = "sh-step-pill-active"
        elif num < step:
            cls = "sh-step-pill-done"
        else:
            cls = "sh-step-pill-pending"
        pills.append(f'<span class="sh-step-pill {cls}">{num}. {label}</span>')
    st.markdown(f'<div class="sh-step-pill-row">{"".join(pills)}</div>', unsafe_allow_html=True)
