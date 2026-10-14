"""Resolution notes from Confluence (AI optional; template always works)."""
from __future__ import annotations

import logging


from services.confluence_service import fetch_page_for_user

logger = logging.getLogger(__name__)


def _template_notes(page: dict, ticket_key: str, ticket_summary: str, extra: str) -> str:
    title = page.get("title") or "documented procedure"
    link = page.get("link") or ""
    excerpt = (page.get("excerpt") or "").strip()
    steps = excerpt[:900] if excerpt else "(See documentation link for detailed steps.)"
    extra_line = f"\n\nAdditional notes: {extra.strip()}" if (extra or "").strip() else ""
    summary = ticket_summary or "the reported issue"
    return (
        f"Issue on {ticket_key or 'ticket'} ({summary}) has been addressed "
        f"using the documented procedure \"{title}\".\n\n"
        f"{steps}{extra_line}\n\n"
        f"Documentation: {link}"
    )


def draft_resolution_notes(
    *,
    user_id: int,
    confluence_url: str = "",
    ticket_key: str = "",
    ticket_summary: str = "",
    extra_context: str = "",
    manual_title: str = "",
    manual_excerpt: str = "",
) -> str:
    if (manual_excerpt or "").strip():
        page = {
            "title": (manual_title or "").strip() or "Confluence procedure",
            "excerpt": manual_excerpt.strip()[:2000],
            "link": (confluence_url or "").strip() or "(no link)",
        }
    else:
        page = fetch_page_for_user(user_id, confluence_url)

    # Prefer AI when Ollama is reachable; always fall back to template
    try:
        from services.ai_service import chat, ollama_available

        if ollama_available():
            system = (
                "You write short Jira resolution notes for support engineers.\n"
                "Output ONLY the notes text (no title line).\n"
                "Structure:\n"
                "1) One sentence problem summary\n"
                "2) Steps taken / how it was solved\n"
                "3) Final line: Documentation: <confluence link>\n"
                "Keep URLs unchanged. Under 150 words."
            )
            user = (
                f"Ticket: {ticket_key} — {ticket_summary}\n"
                f"Confluence title: {page['title']}\n"
                f"Confluence link: {page['link']}\n"
                f"Page excerpt: {page['excerpt']}\n"
                f"Extra context: {extra_context or '(none)'}\n"
            )
            out = (chat(system, user) or "").strip()
            if out:
                return out
    except Exception:
        logger.exception("AI resolution notes failed; using template fallback")

    return _template_notes(page, ticket_key, ticket_summary, extra_context)
