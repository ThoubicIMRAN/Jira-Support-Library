from __future__ import annotations

import streamlit as st


def page_header(title: str, description: str, icon: str = "⚙️") -> None:
    st.markdown(
        f"<div class='admin-header'><div><h1>{icon} {title}</h1><p>{description}</p></div></div>",
        unsafe_allow_html=True,
    )


def section_title(title: str, description: str | None = None, icon: str = "") -> None:
    st.markdown(f"### {icon} {title}" if icon else f"### {title}")
    if description:
        st.caption(description)


def metric_card(label: str, value: str | int, help_text: str = "") -> None:
    with st.container(border=True):
        st.metric(label, value, help=help_text or None)


def status_badge(ok: bool, good: str = "Healthy", bad: str = "Attention required") -> None:
    label = good if ok else bad
    cls = "admin-status-ok" if ok else "admin-status-warn"
    st.markdown(f"<span class='{cls}'>{'●' if ok else '●'} {label}</span>", unsafe_allow_html=True)
