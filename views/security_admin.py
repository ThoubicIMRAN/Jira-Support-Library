import streamlit as st

from components.cards import page_header
from sqlalchemy import select
from database import SessionLocal, SMTPConfig, Project
from config import ROLES
from email_service import send_html_email, branded_email
from services.account_service import create_invitation
from utils.security import encrypt_secret


def render(user, *, embedded: bool = False):
    if not embedded:
        page_header('🔐 Security & Messaging')
    smtp_tab,invite_tab,trash_tab=st.tabs(['SMTP configuration','Invite user','Project trash'])
    with smtp_tab:
        if user.role!='superadmin': st.error('Only superadmins can configure SMTP.')
        else:
            with SessionLocal() as db:
                cfg=db.scalar(select(SMTPConfig).order_by(SMTPConfig.id.desc()))
                with st.form('smtp_config'):
                    c1,c2=st.columns([3,1]); host=c1.text_input('SMTP server',cfg.host if cfg else ''); port=c2.number_input('Port',1,65535,cfg.port if cfg else 587)
                    username=st.text_input('Username',cfg.username if cfg else ''); password=st.text_input('Password',type='password',help='Leave blank to retain the existing encrypted password.')
                    sender_email=st.text_input('Sender email',cfg.sender_email if cfg else ''); sender_name=st.text_input('Sender name',cfg.sender_name if cfg else 'Jira Support Library')
                    c3,c4,c5=st.columns(3); use_tls=c3.checkbox('STARTTLS',cfg.use_tls if cfg else True); use_ssl=c4.checkbox('Implicit SSL',cfg.use_ssl if cfg else False); active=c5.checkbox('Active',cfg.is_active if cfg else True)
                    save=st.form_submit_button('Save SMTP configuration',type='primary')
                if save:
                    if not host.strip() or not sender_email.strip(): st.error('SMTP server and sender email are required.')
                    elif use_tls and use_ssl: st.error('Choose STARTTLS or implicit SSL, not both.')
                    else:
                        row=cfg or SMTPConfig(host=host,port=int(port),sender_email=sender_email)
                        row.host=host.strip(); row.port=int(port); row.username=username.strip(); row.sender_email=sender_email.strip(); row.sender_name=sender_name.strip() or 'Jira Support Library'; row.use_tls=use_tls; row.use_ssl=use_ssl; row.is_active=active
                        if password: row.encrypted_password=encrypt_secret(password)
                        if not cfg: db.add(row)
                        db.commit(); st.success('SMTP configuration saved securely.')
                with st.form('test_email'):
                    recipient=st.text_input('Test recipient'); test=st.form_submit_button('Send test email')
                if test:
                    try: send_html_email(recipient,'Jira Support Library SMTP test',branded_email('SMTP test successful','<p>Your Jira Support Library SMTP configuration is working.</p>')); st.success('Test email sent.')
                    except Exception:
                        import logging
                        logging.getLogger(__name__).exception('SMTP test email failed for user %s', user.id)
                        st.error('Test email failed. Please try again.')
    with invite_tab:
        if user.role not in ('admin','superadmin'): st.error('Administrator access required.')
        else:
            with st.form('invite_user'):
                email=st.text_input('Email address'); role=st.selectbox('Role',ROLES,index=3); designation=st.text_input('Default designation','Support Engineer')
                send=st.form_submit_button('Send invitation',type='primary')
            if send:
                if user.role!='superadmin' and role in ('admin','superadmin'): st.error('Only a superadmin can invite privileged administrators.')
                else:
                    try: create_invitation(email,role,designation,user.id); st.success('Invitation sent.')
                    except Exception:
                        import logging
                        logging.getLogger(__name__).exception('Invitation creation failed for user %s', user.id)
                        st.error('Invitation could not be sent. Please try again.')
    with trash_tab:
        with SessionLocal() as db:
            archived=db.scalars(select(Project).where(Project.is_deleted==True).order_by(Project.updated_at.desc())).all()
            if not archived: st.info('Project trash is empty.')
            for project in archived:
                c1,c2,c3=st.columns([6,1,1]); c1.write(f'{project.icon} **{project.name}** · `{project.key}`')
                if c2.button('Restore',key=f'restore_{project.id}'):
                    project.is_deleted=False; db.commit(); st.rerun()
                if c3.button('Delete',key=f'purge_{project.id}',help='Permanently delete project and all content'):
                    st.session_state.purge_project=project.id
            purge=st.session_state.get('purge_project')
            if purge:
                row=db.get(Project,purge)
                st.error('Permanent deletion selected for this project. This deletes all categories and responses.')
                if st.button('Confirm permanent deletion',type='primary'):
                    db.delete(row); db.commit(); st.session_state.pop('purge_project',None); st.rerun()

# Phase 5 session administration extension.
def render_sessions(user):
 import streamlit as st
 from sqlalchemy import select, func
 from database import SessionLocal, AppSession, User
 from services.session_service import revoke_user_sessions
 st.subheader('Active sessions')
 if user.role != 'superadmin':
  st.info('Only superadmins can revoke other users’ sessions.')
  return
 with SessionLocal() as db:
  # Render one row per user instead of one row per session. This prevents
  # duplicate widget keys when a user has multiple active sessions.
  session_stats = db.execute(
   select(
    AppSession.user_id,
    func.count(AppSession.id).label('session_count'),
    func.max(AppSession.last_seen_at).label('last_seen_at'),
   )
   .where(AppSession.revoked_at.is_(None))
   .group_by(AppSession.user_id)
   .order_by(func.max(AppSession.last_seen_at).desc())
   .limit(200)
  ).all()
  user_ids = [row.user_id for row in session_stats]
  users = {
   account.id: account
   for account in db.scalars(select(User).where(User.id.in_(user_ids))).all()
  } if user_ids else {}
  if not session_stats:
   st.info('There are no active sessions.')
   return
  for stat in session_stats:
   account = users.get(stat.user_id)
   with st.container(border=True):
    c1, c2 = st.columns([7, 2], vertical_alignment='center')
    c1.markdown(
     f'**{account.username if account else stat.user_id}**  \n'
     f'{stat.session_count} active session(s) · Last seen: {stat.last_seen_at}'
    )
    if c2.button(
     'Revoke all',
     key=f'revoke_user_sessions_{stat.user_id}',
     width='stretch',
     disabled=stat.user_id == user.id,
     help='The current superadmin session cannot be revoked from this row.',
    ):
     revoked = revoke_user_sessions(stat.user_id)
     st.toast(f'Revoked {revoked} session(s).', icon='✅')
     st.rerun()

_original_security_render = render


def render(user, *, embedded: bool = False):
    _original_security_render(user, embedded=embedded)
    st.markdown("---")
    render_sessions(user)
