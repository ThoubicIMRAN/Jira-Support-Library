"""
Local AI Response Assistant backed by Ollama (Docker service `ollama`).

Rules:
- Prefer reusing an existing library response when semantic similarity is high.
- Only generate + save a NEW response when no good match exists.
- Safe for concurrent users: one shared Ollama container serves all app workers.
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone

import httpx
import numpy as np
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from config import (
    OLLAMA_BASE,
    OLLAMA_CHAT_MODEL,
    OLLAMA_EMBED_MODEL,
    AI_SIMILARITY_THRESHOLD,
    AI_REQUEST_TIMEOUT,
)
from database import (
    SessionLocal,
    Response,
    Category,
    ResponseEmbedding,
    AIGenerationLog,
)

logger = logging.getLogger(__name__)

TONE_INSTRUCTIONS = {
    'Professional': 'Clear, direct, professional. Short sentences. No filler.',
    'Friendly': 'Warm and helpful, still concise. No fluff.',
    'Escalation': 'Firm and urgent. State impact and next step in few lines.',
    'Customer-facing': 'Speak to the end customer. Polite, plain language, brief.',
    'Internal Team': 'Internal note. Technical and short.',
}

STYLE_RULES = """
Write like a real support engineer posting a short Jira comment or email reply.

REQUIRED STYLE:
- 4 to 8 short lines maximum (unless the ticket truly needs more)
- Greeting: Hello @R,  (or Hello, if no recipient)
- One or two sentences stating what was done / status
- One short ask (e.g. confirm everything works) when appropriate
- Closing: Thank you for your understanding. (or similar, one line)
- Signature block EXACTLY:
  Best regards,
  @NAME
  @DESIGNATION

FORBIDDEN:
- Do NOT write "Here is a reusable response template"
- Do NOT use "We are pleased to inform you", "please do not hesitate", "further questions or concerns"
- Do NOT invent long formal letters
- Do NOT invent ticket numbers, dates, or product behaviour not in the input
- Keep any real issue details from the ticket (e.g. hardware, software name)

Placeholders allowed in the body: @NAME, @DESIGNATION, @ROLE, @R, @DATE
Output ONLY the response text — no title, no markdown fences, no commentary.
"""



def _utcnow():
    return datetime.now(timezone.utc)


def _hash_text(text: str) -> str:
    return hashlib.sha256((text or '').strip().encode('utf-8')).hexdigest()


def _cosine(a: list[float], b: list[float]) -> float:
    va = np.asarray(a, dtype=np.float32)
    vb = np.asarray(b, dtype=np.float32)
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb)) or 1e-9
    return float(np.dot(va, vb) / denom)


def ollama_available() -> bool:
    try:
        with httpx.Client(timeout=3.0) as client:
            r = client.get(f'{OLLAMA_BASE}/api/tags')
            return r.status_code == 200
    except Exception:
        return False


def list_models() -> list[str]:
    try:
        with httpx.Client(timeout=5.0) as client:
            r = client.get(f'{OLLAMA_BASE}/api/tags')
            r.raise_for_status()
            return [m.get('name', '') for m in r.json().get('models', [])]
    except Exception:
        return []


def embed(text: str) -> list[float]:
    with httpx.Client(timeout=AI_REQUEST_TIMEOUT) as client:
        r = client.post(
            f'{OLLAMA_BASE}/api/embeddings',
            json={'model': OLLAMA_EMBED_MODEL, 'prompt': (text or '')[:8000]},
        )
        r.raise_for_status()
        data = r.json()
        vec = data.get('embedding')
        if not vec:
            raise RuntimeError(f'Empty embedding from Ollama: {data}')
        return vec


def chat(system: str, user: str) -> str:
    with httpx.Client(timeout=AI_REQUEST_TIMEOUT) as client:
        r = client.post(
            f'{OLLAMA_BASE}/api/chat',
            json={
                'model': OLLAMA_CHAT_MODEL,
                'stream': False,
                'messages': [
                    {'role': 'system', 'content': system},
                    {'role': 'user', 'content': user},
                ],
            },
        )
        r.raise_for_status()
        return (r.json().get('message') or {}).get('content', '').strip()


def ensure_embedding(db, response: Response) -> list[float]:
    row = db.scalar(
        select(ResponseEmbedding).where(ResponseEmbedding.response_id == response.id)
    )
    if row:
        return json.loads(row.embedding_json)

    text = f'{response.title}\n{response.preview or ""}\n{response.response_body}'
    vec = embed(text)
    db.add(ResponseEmbedding(
        response_id=response.id,
        embedding_json=json.dumps(vec),
        model_name=OLLAMA_EMBED_MODEL,
        updated_at=_utcnow(),
    ))
    db.commit()
    return vec


def find_best_match(project_id: int, query_text: str, threshold: float | None = None):
    """Return (response, similarity) or (None, best_score)."""
    threshold = threshold if threshold is not None else AI_SIMILARITY_THRESHOLD
    query_vec = embed(query_text)
    best, best_score = None, 0.0

    with SessionLocal() as db:
        categories = db.scalars(
            select(Category)
            .options(selectinload(Category.responses))
            .where(Category.project_id == project_id)
        ).all()
        for cat in categories:
            for resp in cat.responses:
                try:
                    vec = ensure_embedding(db, resp)
                    score = _cosine(query_vec, vec)
                    if score > best_score:
                        best, best_score = resp, score
                except Exception as exc:
                    logger.warning('Embedding failed for %s: %s', resp.id, exc)

        if best is not None:
            # Detach simple attributes before session closes
            best_id = best.id
            best_title = best.title
            best_body = best.response_body
        else:
            best_id = best_title = best_body = None

    if best_id and best_score >= threshold:
        # Rebuild a lightweight namespace so callers don't need a live ORM object
        class _Hit:
            pass
        hit = _Hit()
        hit.id = best_id
        hit.title = best_title
        hit.response_body = best_body
        return hit, best_score
    return None, best_score


def rewrite(text: str, tone: str) -> str:
    system = (
        'You are a support response editor. Rewrite the text in the required style. '
        'Preserve placeholders @NAME, @DESIGNATION, @ROLE, @R, @DATE. '
        'Do not invent facts. Output only the rewritten response.\n'
        + STYLE_RULES
    )
    user = f'Tone: {TONE_INSTRUCTIONS.get(tone, tone)}\n\nText:\n{text}'
    return chat(system, user)


def translate(text: str, target_language: str) -> str:
    """Translate support text accurately while preserving structure and tokens."""
    system = (
        "You are an expert professional translator for IT support / Jira comments.\n"
        f"Translate the user's message into {target_language}.\n\n"
        "STRICT RULES:\n"
        "1. Output ONLY the translated text — no preface, notes, or quotes.\n"
        "2. Keep the same paragraph breaks and line structure.\n"
        "3. NEVER translate or alter placeholders: @NAME, @DESIGNATION, @ROLE, @R, @DATE.\n"
        "4. Keep Jira/wiki mentions unchanged: [~username].\n"
        "5. Keep product names, ticket keys (e.g. PROJ-123), emails, and URLs unchanged.\n"
        "6. Match the original formality (formal support tone if present).\n"
        "7. Do not add or remove content."
    )
    user_msg = (
        f"Target language: {target_language}\n\n"
        f"Source text:\n{text}"
    )
    return chat(system, user_msg)



def correct_grammar(text: str) -> str:
    system = (
        'Fix grammar, spelling and clarity only. '
        'Do not change meaning or placeholders @NAME, @DESIGNATION, @ROLE, @R. '
        'Output only the corrected text.'
    )
    return chat(system, text)


def summarize(text: str) -> str:
    system = (
        'Summarize this Jira comment for a support engineer. '
        'Keep key facts, ticket numbers, and action items. Be concise.'
    )
    return chat(system, text)


def generate_from_ticket(
    ticket_description: str,
    project_id: int,
    user_id: int,
    category_id: int | None = None,
    tone: str = 'Professional',
    save_if_new: bool = True,
    agent_name: str | None = None,
    agent_designation: str | None = None,
    recipient: str = 'Customer',
) -> dict:
    """
    Reuse-first pipeline:
    1. Semantic search in project library
    2. If similarity >= threshold → reuse (no new row)
    3. Else generate a SHORT support reply; optionally save with badge AI

    agent_name / agent_designation are substituted into the final text so the
    signature shows the real agent (full name and project designation).
    """
    matched, score = find_best_match(project_id, ticket_description)
    source_hash = _hash_text(ticket_description)

    def _apply_agent(body: str) -> str:
        """Fill placeholders with the current agent (and optional recipient)."""
        from datetime import date
        values = {
            'NAME': (agent_name or '@NAME').strip() or '@NAME',
            'DESIGNATION': (agent_designation or '@DESIGNATION').strip() or '@DESIGNATION',
            'R': (recipient or 'Customer').strip() or 'Customer',
            'DATE': date.today().isoformat(),
            'ROLE': 'user',
        }
        import re
        return re.sub(
            r'@(NAME|DESIGNATION|ROLE|R|DATE)\b',
            lambda m: values[m.group(1).upper()],
            body or '',
            flags=re.I,
        )

    if matched:
        with SessionLocal() as db:
            db.add(AIGenerationLog(
                user_id=user_id,
                project_id=project_id,
                action='reuse',
                source_text_hash=source_hash,
                matched_response_id=matched.id,
                similarity=score,
                details=json.dumps({'title': matched.title}, ensure_ascii=False),
            ))
            db.commit()
        return {
            'mode': 'reuse',
            'text': _apply_agent(matched.response_body),
            'raw_text': matched.response_body,
            'response_id': matched.id,
            'similarity': score,
            'title': matched.title,
        }

    system = (
        'You write short Jira support replies for a multi-user response library.\n'
        + STYLE_RULES
    )
    user_prompt = (
        f'Tone: {TONE_INSTRUCTIONS.get(tone, tone)}\n\n'
        f'Recipient placeholder: use @R in the greeting (will be filled as "{recipient}").\n'
        f'Agent name placeholder: @NAME\n'
        f'Agent designation placeholder: @DESIGNATION\n\n'
        f'Ticket / issue description:\n{ticket_description.strip()}\n\n'
        'Write a short status/reply following the style rules.'
    )
    body = chat(system, user_prompt)
    # Strip common model preambles
    for bad in (
        'Here is a reusable response template:',
        'Here is a reusable response template',
        'Here is the response:',
        'Here is a response template:',
    ):
        if body.lower().startswith(bad.lower()):
            body = body[len(bad):].lstrip(' \n:')

    title = chat(
        'Create a short title (max 60 characters) for this support reply. '
        'Output only the title, no quotes.',
        body[:400],
    ).strip().strip('"')[:60] or 'AI generated response'

    personalized = _apply_agent(body)
    new_id = None
    if save_if_new and category_id:
        with SessionLocal() as db:
            order = db.scalar(
                select(func.max(Response.sort_order)).where(Response.category_id == category_id)
            )
            new_id = 'r_' + uuid.uuid4().hex[:16]
            # Store TEMPLATE with placeholders so other users can personalize later
            row = Response(
                id=new_id,
                category_id=category_id,
                title=title,
                badge='AI',
                preview=(body[:120] + '…') if len(body) > 120 else body,
                response_body=body,
                sort_order=(order + 1 if order is not None else 0),
            )
            db.add(row)
            db.flush()
            try:
                vec = embed(f'{row.title}\n{row.preview}\n{row.response_body}')
                db.add(ResponseEmbedding(
                    response_id=row.id,
                    embedding_json=json.dumps(vec),
                    model_name=OLLAMA_EMBED_MODEL,
                ))
            except Exception as exc:
                logger.warning('Could not store embedding for new response: %s', exc)
            db.add(AIGenerationLog(
                user_id=user_id,
                project_id=project_id,
                action='generate',
                source_text_hash=source_hash,
                created_response_id=new_id,
                similarity=score,
                details=json.dumps({'title': title, 'tone': tone}, ensure_ascii=False),
            ))
            db.commit()
    else:
        with SessionLocal() as db:
            db.add(AIGenerationLog(
                user_id=user_id,
                project_id=project_id,
                action='generate',
                source_text_hash=source_hash,
                similarity=score,
                details=json.dumps({'title': title, 'tone': tone, 'saved': False}, ensure_ascii=False),
            ))
            db.commit()

    return {
        'mode': 'generate',
        'text': personalized,
        'raw_text': body,
        'response_id': new_id,
        'similarity': score,
        'title': title,
    }
