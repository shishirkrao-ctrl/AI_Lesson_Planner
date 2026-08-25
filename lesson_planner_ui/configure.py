"""Step 4 — set target lecture hours per unit before generating the plan."""
import html

import streamlit as st

from .state import DEFAULT_UNIT_HOURS


def render_configure_card(skeleton: dict) -> dict:
    with st.container(border=True):
        st.markdown('<div class="sh-card-title">Set target hours per unit</div>', unsafe_allow_html=True)
        st.markdown(
            '<p class="sh-hint">Topics within each unit are weighted by difficulty, then scaled to fit the target you set here.</p>',
            unsafe_allow_html=True,
        )

        unit_names = list(skeleton.keys())
        unit_limits = {}
        n_cols = min(len(unit_names), 4) or 1
        cols = st.columns(n_cols)
        for i, unit_name in enumerate(unit_names):
            n_topics = len(skeleton[unit_name].get("Subtopics", []))
            with cols[i % n_cols]:
                st.markdown(
                    f'<div class="sh-unit-label">'
                    f'<div class="sh-unit-name">{html.escape(unit_name)}</div>'
                    f'<div class="sh-unit-count">{n_topics} topics</div></div>',
                    unsafe_allow_html=True,
                )
                unit_limits[unit_name] = st.number_input(
                    unit_name,
                    min_value=0.0,
                    value=DEFAULT_UNIT_HOURS,
                    step=0.5,
                    key=f"limit_{unit_name}",
                    label_visibility="collapsed",
                )

        total = sum(unit_limits.values())
        st.markdown(
            f'<p class="sh-total">target total&nbsp; <b>{total:g} hrs</b> &nbsp;across {len(unit_names)} units</p>',
            unsafe_allow_html=True,
        )

        generate_clicked = st.button("compile lesson plan \u2192", type="primary", key="generate_btn")
    return unit_limits, generate_clicked
