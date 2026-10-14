from __future__ import annotations
import streamlit as st
from sqlalchemy import select
from database import SessionLocal, User, AuditLog, UserDirectoryIdentity
from config import LDAPS_ENABLED, LDAPS_HOST, LDAPS_PORT, LDAPS_BASE_DN, LDAPS_BIND_DN, LDAPS_USER_FILTER
from services.ldap_service import get_config, save_config, search_users

def render(user):
    if user.role not in {"admin","superadmin"}: st.error("Administrator access required."); return
    st.subheader("Active Directory / LDAPS")
    if not LDAPS_ENABLED:
        st.warning("LDAPS is disabled at application configuration level. Set LDAPS_ENABLED=true to enable directory sign-in and imports.")
    st.caption("Add local application accounts from Active Directory over a secure LDAPS connection.")
    cfg=get_config()
    with st.form("ldaps_config"):
        c1,c2=st.columns(2)
        host=c1.text_input("LDAPS host",cfg.host if cfg else LDAPS_HOST,placeholder="ad.example.com")
        port=c2.number_input("LDAPS port",1,65535,int(cfg.port if cfg else LDAPS_PORT))
        base=c1.text_input("Base DN",cfg.base_dn if cfg else LDAPS_BASE_DN,placeholder="DC=example,DC=com")
        bind=c2.text_input("Bind DN",cfg.bind_dn if cfg else LDAPS_BIND_DN)
        pwd=st.text_input("Bind password",type="password",help="Leave blank to retain the encrypted password.")
        filt=st.text_input("User search filter",cfg.user_filter if cfg else LDAPS_USER_FILTER)
        ssl_required=st.checkbox("Require LDAPS certificate validation",True)
        save=st.form_submit_button("Save LDAPS configuration",type="primary")
    if save:
        try: save_config(host,port,base,bind,pwd,filt,ssl_required); st.success("LDAPS configuration saved."); st.rerun()
        except Exception as exc: st.error(f"Could not save LDAPS configuration: {exc}")
    if not cfg and not save: st.info("Configure LDAPS before searching Active Directory."); return
    st.divider(); st.subheader("Find account")
    query=st.text_input("AD username",placeholder="first.last")
    if st.button("Search Active Directory",type="primary",disabled=(not query.strip() or not LDAPS_ENABLED)):
        try: st.session_state["ad_results"]=search_users(query.strip())
        except Exception as exc: st.error(f"Directory search failed: {exc}")
    for i,item in enumerate(st.session_state.get("ad_results",[])):
        with st.container(border=True):
            c1,c2=st.columns([4,1])
            c1.markdown(f"**{item['full_name']}**  \n`{item['username']}` · {item['email'] or 'No email'}")
            if c2.button("Add account",key=f"ad_add_{i}",type="primary"):
                try:
                    with SessionLocal() as db:
                        conditions=[User.username==item['username']]
                        if item['email']: conditions.append(User.email==item['email'])
                        existing=db.scalar(select(User).where(*conditions))
                        if existing: raise ValueError("A local account already exists for this username or email.")
                        row=User(username=item['username'],email=item['email'] or None,full_name=item['full_name'],designation=item['designation'],role="user",password_hash=None,is_active=True,must_change_password=False)
                        db.add(row); db.flush(); db.add(UserDirectoryIdentity(user_id=row.id, username=item["username"], distinguished_name=item["dn"])); db.add(AuditLog(user_id=user.id,action="ad_account_imported",entity_type="user",entity_id=str(row.id),details=f"Imported {item['username']} from Active Directory")); db.commit()
                    st.success(f"{item['username']} added."); st.rerun()
                except Exception as exc: st.error(str(exc))
