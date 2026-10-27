from __future__ import annotations

import streamlit as st
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from auth import allowed, hash_password
from config import ROLES
from database import SessionLocal, User
from utils.validators import valid_password
from services.account_service import admin_reset_password, admin_set_password, delete_user, unlock_login


def render(user) -> None:
    if not allowed(user.role, "manage_users") and user.role != "superadmin":
        st.error("You do not have permission to manage users.")
        return

    st.subheader("Users")
    st.caption("Manage accounts, roles and account status from one place.")

    with st.expander("➕ Create user", expanded=False):
        with st.form("admin_center_create_user"):
            c1, c2 = st.columns(2)
            username = c1.text_input("Username")
            email = c2.text_input("Email")
            full_name = st.text_input("Full name")
            designation = st.text_input("Designation", "Support Engineer")
            role = st.selectbox("Role", ROLES)
            password = st.text_input("Initial password", type="password")
            submitted = st.form_submit_button("Create user", type="primary")

        if submitted:
            if not username.strip() or not full_name.strip():
                st.error("Username and full name are required.")
            elif not valid_password(password):
                st.error("Password does not meet the configured password policy.")
            elif user.role != "superadmin" and role in {"admin", "superadmin"}:
                st.error("Only a superadmin can create privileged administrators.")
            else:
                with SessionLocal() as db:
                    account = User(
                        username=username.strip(),
                        email=email.strip() or None,
                        full_name=full_name.strip(),
                        designation=designation.strip() or "Support Engineer",
                        role=role,
                        password_hash=hash_password(password),
                        must_change_password=True,
                        is_active=True,
                    )
                    db.add(account)
                    try:
                        db.commit()
                        st.success("User created successfully.")
                        st.rerun()
                    except IntegrityError:
                        db.rollback()
                        st.error("Username or email already exists.")

    with SessionLocal() as db:
        accounts = db.scalars(select(User).order_by(User.username)).all()

    search = st.text_input("Search users", placeholder="Name, username or email")
    needle = search.strip().lower()
    if needle:
        accounts = [
            a for a in accounts
            if needle in (a.username or "").lower()
            or needle in (a.full_name or "").lower()
            or needle in (a.email or "").lower()
        ]

    for account in accounts:
        with st.container(border=True):
            c1, c2, c3, c4 = st.columns([3, 2, 1.2, 1.5], vertical_alignment="center")
            c1.markdown(f"**{account.full_name}**  \n`{account.username}` · {account.email or 'No email'}")
            c2.write(f"**{account.role}**  \n{account.designation}")
            c3.write("Active" if account.is_active else "Disabled")
            with c4:
                with st.popover("Manage", use_container_width=True):
                    if account.id == user.id:
                        st.caption("Your own account is protected from destructive actions.")
                    new_role = st.selectbox("Role", ROLES, index=ROLES.index(account.role) if account.role in ROLES else 0, key=f"ucr_{account.id}")
                    active = st.checkbox("Account active", account.is_active, key=f"uca_{account.id}")
                    if st.button("Save", key=f"ucs_{account.id}", type="primary", use_container_width=True):
                        if account.id == user.id and (new_role != account.role or not active):
                            st.error("You cannot disable or change the role of your current account here.")
                        elif user.role != "superadmin" and new_role in {"admin", "superadmin"}:
                            st.error("Only a superadmin can assign privileged roles.")
                        else:
                            with SessionLocal() as db:
                                row = db.get(User, account.id)
                                row.role = new_role
                                row.is_active = active
                                db.commit()
                            st.success("User updated.")
                            st.rerun()

                    st.markdown("---")
                    if account.id != user.id:
                        if st.button("Unlock account", key=f"ucul_{account.id}", use_container_width=True):
                            try:
                                n = unlock_login(account.username)
                                st.success(f"Unlocked ({n} attempts cleared).")
                            except Exception:
                                st.error("Unlock failed.")
                        new_pw = st.text_input("Temp password", type="password", key=f"ucpw_{account.id}")
                        if st.button("Set password", key=f"ucsp_{account.id}", use_container_width=True):
                            try:
                                admin_set_password(account.id, new_pw or "", user.id)
                                unlock_login(account.username)
                                st.success("Password set; user must change it on next login.")
                            except Exception as exc:
                                st.error(str(exc))
                        if st.button("Reset password (email link)", key=f"ucrp_{account.id}", use_container_width=True):
                            try:
                                admin_reset_password(account.id, user.id)
                                st.success("A secure password-reset link has been emailed to the user.")
                            except Exception:
                                st.error("Password reset failed.")

                        if st.button("Delete user", key=f"ucdel_{account.id}", use_container_width=True):
                            st.session_state[f"confirm_delete_{account.id}"] = True

                        if st.session_state.get(f"confirm_delete_{account.id}"):
                            st.error("This permanently removes the account and its user-owned data.")
                            c_yes, c_no = st.columns(2)
                            if c_yes.button("Confirm delete", key=f"ucdel_yes_{account.id}", type="primary", use_container_width=True):
                                try:
                                    delete_user(account.id, user.id)
                                    st.session_state.pop(f"confirm_delete_{account.id}", None)
                                    st.success("User deleted.")
                                    st.rerun()
                                except Exception:
                                    st.error("User deletion failed. Check the application log for details.")
                            if c_no.button("Cancel", key=f"ucdel_no_{account.id}", use_container_width=True):
                                st.session_state.pop(f"confirm_delete_{account.id}", None)
                                st.rerun()
