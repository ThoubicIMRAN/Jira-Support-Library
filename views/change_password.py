import streamlit as st

from components.cards import page_header
from database import SessionLocal,User
from auth import hash_password
from utils.validators import valid_password

def render(user):
    page_header('🔐 Change temporary password')
    st.warning('You must change the bootstrap or temporary password before accessing the application.')
    with st.form('mandatory_password_change'):
        password=st.text_input('New password',type='password'); confirm=st.text_input('Confirm password',type='password')
        save=st.form_submit_button('Change password',type='primary',width='stretch')
    if save:
        if not valid_password(password): st.error('Password must contain at least 8 characters.')
        elif password!=confirm: st.error('Passwords do not match.')
        else:
            with SessionLocal() as db:
                row=db.get(User,user.id); row.password_hash=hash_password(password); row.must_change_password=False; db.commit()
            st.success('Password changed.'); st.rerun()
