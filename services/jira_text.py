"""Prepare response text for Jira comments (reporter, mentions, resolution notes)."""
from __future__ import annotations

import re


_THANKS_RE = re.compile(
    r"(?=(?:^|\n)\s*(?:"
    r"Thank you for your cooperation\.?"
    r"|Thanks(?:\s+for\s+your\s+cooperation)?\.?"
    r"|Thank you\.?"
    r"|Best regards,?"
    r"|Regards,?"
    r"|Kind regards,?"
    r"))",
    re.IGNORECASE | re.MULTILINE,
)


def _fill_greeting_and_tokens(text: str, recipient: str) -> str:
    """Replace @R / Customer and empty Hello, with recipient (name or [~user])."""
    name = (recipient or "Customer").strip() or "Customer"
    out = text or ""

    out = re.sub(r"@R\b", name, out, flags=re.IGNORECASE)
    out = re.sub(
        r"(Hello|Hi|Dear)\s*,",
        rf"\1 {name},",
        out,
        flags=re.IGNORECASE,
    )
    out = re.sub(
        r"(Hello|Hi|Dear)\s{2,},",
        rf"\1 {name},",
        out,
        flags=re.IGNORECASE,
    )
    out = re.sub(r"\bCustomer\b", name, out)
    out = re.sub(r"(Hello|Hi|Dear)\s{2,}", r"\1 ", out, flags=re.IGNORECASE)
    return out


def apply_reporter_placeholders(text: str, reporter_name: str) -> str:
    return _fill_greeting_and_tokens(text, reporter_name)


def insert_resolution_notes(text: str, notes: str) -> str:
    notes = (notes or "").strip()
    if not notes:
        return text
    block = f"\n\nResolution notes:\n{notes}\n\n"
    m = _THANKS_RE.search(text or "")
    if m:
        pos = m.start()
        return (text[:pos].rstrip() + block + text[pos:].lstrip("\n")).strip() + "\n"
    return (text or "").rstrip() + block


def build_comment_preview(
    template: str,
    *,
    reporter_name: str,
    mention_mode: str = "plain",
    mention_username: str = "",
    resolution_notes: str = "",
) -> str:
    """
    mention_mode:
      - plain → Hello {Reporter Display Name},
      - wiki  → Hello [~username],
      - none  → Hello Customer, (or leftover @R if present)
    """
    mode = (mention_mode or "plain").lower()
    user = (mention_username or "").strip()
    display = (reporter_name or "Customer").strip() or "Customer"

    if mode == "wiki" and user:
        recipient = f"[~{user}]"
    elif mode == "none":
        recipient = "Customer"
    else:
        # plain (default)
        recipient = display

    body = _fill_greeting_and_tokens(template, recipient)
    body = insert_resolution_notes(body, resolution_notes)
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()
