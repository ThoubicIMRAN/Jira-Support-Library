"""Browser-side WebAuthn ceremonies exposed as a Streamlit component."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit.components.v1 as components


def passkey_flow(
    *,
    mode: str,
    options: dict[str, Any],
    expected_origin: str,
    key: str,
) -> Any:
    """Run a passkey registration or authentication ceremony in the browser."""
    if mode not in {"registration", "authentication"}:
        raise ValueError("Unsupported passkey ceremony.")
    component = components.declare_component(
        "jira_support_library_passkey_flow",
        path=str(Path(__file__).with_name("passkey_component")),
    )
    return component(
        mode=mode,
        options=options,
        expected_origin=expected_origin,
        key=key,
        default=None,
    )
