from auth import allowed
import logging

import streamlit as st
from components.cards import page_header
from sqlalchemy import select
from database import SessionLocal, Project, Category
from services import ai_service
from services.project_access import visible_project_ids


logger = logging.getLogger(__name__)

TONES = ['Professional', 'Friendly', 'Escalation', 'Customer-facing', 'Internal Team']
LANGS = ['English', 'Spanish', 'French', 'German', 'Portuguese', 'Hindi', 'Arabic', 'Japanese', 'Chinese']


def _render_result(user) -> None:
    """Show the last AI result. Kept in session state so the follow-up
    'Submit for approval' button survives Streamlit's rerun."""
    data = st.session_state.get('ai_result')
    if not data:
        return
    result = data['result']
    if result['mode'] == 'reuse':
        st.success(f"Reused existing response **{result['title']}** (similarity {result['similarity']:.0%}). No duplicate created.")
    else:
        saved = ' and saved it to the library.' if result.get('response_id') else '.'
        st.info(f"No close match (best similarity {result['similarity']:.0%}). Generated a new response{saved}")
    st.code(result['text'], language=None, wrap_lines=True)
    st.caption('Use the copy icon in the box above.')

    needs_approval = (result.get('mode') == 'new' and not result.get('response_id')
                      and not data['can_save'] and data['request_approval'])
    if needs_approval and not data.get('submitted'):
        if st.button('Submit for library approval', key='ai_submit_approval'):
            try:
                from services.ai_approval_service import submit_pending
                submit_pending(user_id=user.id, project_id=data['project_id'], category_id=data['category_id'],
                               title=(data['ticket'].split('\n')[0] or 'AI response')[:120],
                               body=result['text'], ticket_excerpt=data['ticket'][:500])
            except Exception:
                logger.exception('Submitting AI response for approval failed')
                st.error('Could not submit for approval. Please try again.')
            else:
                data['submitted'] = True
                st.rerun()
    elif data.get('submitted'):
        st.success('Submitted for manager/admin approval.')


def render(user):
    if not allowed(user.role, 'use_ai'):
        st.warning('You do not have access to the AI assistant.')
        return
    page_header('AI Response Assistant', 'Runs locally via Ollama. Reuses similar library entries; creates new responses only when needed.', icon='🤖')

    if not ai_service.ollama_available():
        st.error(
            'Ollama is not reachable.\n\n'
            'With Docker Compose the `ollama` service should be running. '
            'First start may take several minutes while models download.\n\n'
            'Check: `docker compose logs ollama` and ensure models are pulled '
            '(see README / docker-compose pull step).'
        )
        with st.expander('Debug'):
            st.write('OLLAMA endpoint status: offline')
            st.code('docker compose ps\ndocker compose logs --tail=50 ollama')
        return

    models = ai_service.list_models()
    st.success(f'Ollama online · models: {", ".join(models) if models else "(none listed yet)"}')

    tab_gen, tab_rewrite, tab_tools = st.tabs([
        'Generate from ticket',
        'Rewrite / tone',
        'Translate · Grammar · Summarize',
    ])

    # ── Generate (reuse-first) ───────────────────────────────────
    with tab_gen:
        with SessionLocal() as db:
            projects = db.scalars(
                select(Project)
                .where(Project.is_deleted == False)
                .order_by(Project.sort_order, Project.id)
            ).all()
        _visible = visible_project_ids(user.id, user.role)
        if _visible is not None:
            projects = [p for p in projects if p.id in _visible]

        if not projects:
            st.info('Create a project first.')
            return

        pmap = {p.id: p for p in projects}
        project_id = st.selectbox(
            'Project',
            [p.id for p in projects],
            format_func=lambda i: f'{pmap[i].icon} {pmap[i].name}',
        )

        with SessionLocal() as db:
            cats = db.scalars(
                select(Category)
                .where(Category.project_id == project_id)
                .order_by(Category.sort_order, Category.id)
            ).all()

        cat_id = None
        if cats:
            cat_id = st.selectbox(
                'Save new responses into category',
                [c.id for c in cats],
                format_func=lambda i: next(c.name for c in cats if c.id == i),
            )
        else:
            st.warning('This project has no categories yet. Create one before saving AI responses.')

        ticket = st.text_area('Ticket description / issue', height=180)
        recipient = st.text_input('Recipient name (optional)', value='Customer', help='Used in the greeting, e.g. Hello Customer,')
        tone = st.selectbox('Tone', TONES, key='gen_tone')
        can_save = allowed(user.role, "save_library") or allowed(user.role, "approve_content")
        save_new = False
        request_approval = False
        if can_save:
            save_new = st.checkbox(
                "Save to library when AI creates a **new** response (skipped on reuse)",
                value=False,
                help="Managers and admins can save directly into the library.",
            )
        else:
            st.caption(
                "AI is available for all users. Saving into the library requires "
                "manager or admin approval."
            )
            request_approval = st.checkbox(
                "Submit new AI response for manager/admin approval",
                value=True,
            )

        if st.button('Find or generate response', type='primary', width='stretch'):
            if not ticket.strip():
                st.warning('Enter a ticket description.')
            else:
                with st.spinner('Searching library, then generating only if needed…'):
                    try:
                        # Project-specific designation if set for this user
                        from database import UserProjectDesignation
                        from sqlalchemy import select as _select
                        with SessionLocal() as _db:
                            override = _db.scalar(
                                _select(UserProjectDesignation.designation).where(
                                    UserProjectDesignation.user_id == user.id,
                                    UserProjectDesignation.project_id == project_id,
                                )
                            )
                        agent_designation = (
                            (override or getattr(user, 'designation', None) or 'Support Engineer')
                        )
                        result = ai_service.generate_from_ticket(
                            ticket_description=ticket.strip(),
                            project_id=project_id,
                            user_id=user.id,
                            category_id=cat_id if save_new else None,
                            tone=tone,
                            save_if_new=bool(can_save and save_new and cat_id),
                            agent_name=getattr(user, 'full_name', None) or user.username,
                            agent_designation=agent_designation,
                            recipient=(recipient or 'Customer').strip() or 'Customer',
                        )
                    except Exception:
                        logger.exception('AI generate_from_ticket failed')
                        st.error('The AI request failed. Check that Ollama is running and try again.')
                        return
                st.session_state['ai_result'] = {
                    'result': result, 'project_id': project_id, 'category_id': cat_id,
                    'ticket': ticket.strip(), 'can_save': can_save, 'request_approval': request_approval,
                }

        _render_result(user)

    # ── Rewrite ─────────────────────────────────────────────────
    with tab_rewrite:
        src = st.text_area('Response to rewrite', height=200, key='rw_src')
        tone = st.selectbox('Target tone', TONES, key='rw_tone')
        if st.button('Rewrite', type='primary', key='rw_btn', width='stretch'):
            if not src.strip():
                st.warning('Paste a response first.')
            else:
                with st.spinner('Rewriting locally…'):
                    try:
                        out = ai_service.rewrite(src.strip(), tone)
                        st.code(out, language=None, wrap_lines=True)
                    except Exception:
                        logger.exception('AI rewrite failed')
                        st.error('Rewrite failed. Please try again.')

    # ── Tools ───────────────────────────────────────────────────
    with tab_tools:
        src = st.text_area('Text', height=180, key='tool_src')
        c1, c2, c3 = st.columns(3)
        lang = c1.selectbox('Translate to', LANGS)
        if c1.button('Translate', width='stretch'):
            if src.strip():
                with st.spinner('Translating…'):
                    try:
                        st.code(ai_service.translate(src.strip(), lang), language=None, wrap_lines=True)
                    except Exception:
                        logger.exception('AI text tool failed')
                        st.error('The AI request failed. Please try again.')
        if c2.button('Fix grammar', width='stretch'):
            if src.strip():
                with st.spinner('Correcting…'):
                    try:
                        st.code(ai_service.correct_grammar(src.strip()), language=None, wrap_lines=True)
                    except Exception:
                        logger.exception('AI text tool failed')
                        st.error('The AI request failed. Please try again.')
        if c3.button('Summarize', width='stretch'):
            if src.strip():
                with st.spinner('Summarizing…'):
                    try:
                        st.code(ai_service.summarize(src.strip()), language=None, wrap_lines=True)
                    except Exception:
                        logger.exception('AI text tool failed')
                        st.error('The AI request failed. Please try again.')


    # ── Approvals (manager / admin) ─────────────────────────────
    if allowed(user.role, "approve_content"):
        st.divider()
        st.markdown("### 📋 AI library approvals")
        try:
            from services.ai_approval_service import list_pending, approve_pending, reject_pending
            pending = list_pending()
        except Exception:
            logger.exception('Loading pending AI approvals failed')
            st.caption('Approvals are temporarily unavailable.')
            pending = []
        if not pending:
            st.caption("No pending AI responses.")
        for item in pending:
            with st.container(border=True):
                st.markdown(
                    f"**{item['title']}** · {item['project_name']} · by `{item['username']}`"
                )
                if item.get("ticket_excerpt"):
                    st.caption(item["ticket_excerpt"][:200])
                st.code(item["body"], language=None, wrap_lines=True)
                a1, a2 = st.columns(2)
                if a1.button("Approve & save to library", key=f"ai_appr_{item['id']}", type="primary"):
                    try:
                        rid = approve_pending(item["id"], user.id, category_id=item.get("category_id"))
                        st.success(f"Saved response {rid}")
                        st.rerun()
                    except Exception:
                        logger.exception('AI text tool failed')
                        st.error('The AI request failed. Please try again.')
                if a2.button("Reject", key=f"ai_rej_{item['id']}"):
                    reject_pending(item["id"], user.id)
                    st.rerun()

