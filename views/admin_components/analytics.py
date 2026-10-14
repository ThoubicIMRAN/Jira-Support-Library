from __future__ import annotations

import streamlit as st
from services.workspace_service import usage_summary


def render(user) -> None:
    if user.role not in {"admin", "superadmin"}:
        st.error("Administrator access required.")
        return
    st.subheader("Usage analytics")
    st.caption("Response usage and activity summary.")
    st.dataframe(usage_summary(100), width="stretch", hide_index=True)
