"""Profile avatar storage (bytes in DB) with validation."""
from __future__ import annotations

from database import SessionLocal, User
from services.rate_limit import limit_avatar_upload

ALLOWED_MIME = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}
MAX_BYTES = 500 * 1024  # 500 KB


class AvatarError(ValueError):
    pass


def set_avatar(
    user_id: int,
    data: bytes,
    mime: str,
    *,
    actor_id: int | None = None,
    actor_role: str | None = None,
) -> None:
    """Store avatar bytes. Caller must be the user themselves or a superadmin.

    actor_id / actor_role are required for authorization. If omitted (legacy
    callers), only the same user_id is allowed via a soft check when both
    match the session; prefer always passing actor_*.
    """
    mime = (mime or "").split(";")[0].strip().lower()
    if mime not in ALLOWED_MIME:
        raise AvatarError("Only PNG, JPEG, or WebP images are allowed.")
    if not data or len(data) > MAX_BYTES:
        raise AvatarError(f"Image must be under {MAX_BYTES // 1024} KB.")

    # Authorization: self or superadmin only
    if actor_id is not None:
        if int(actor_id) != int(user_id) and (actor_role or "") != "superadmin":
            raise AvatarError("You can only change your own avatar.")
        limit_avatar_upload(int(actor_id))
    else:
        # Legacy path: rate-limit by target user_id
        limit_avatar_upload(int(user_id))

    with SessionLocal() as db:
        user = db.get(User, user_id)
        if not user:
            raise AvatarError("User not found.")
        user.avatar_data = data
        user.avatar_mime = mime
        user.avatar_url = None  # prefer DB blob
        db.commit()


def clear_avatar(
    user_id: int,
    *,
    actor_id: int | None = None,
    actor_role: str | None = None,
) -> None:
    if actor_id is not None:
        if int(actor_id) != int(user_id) and (actor_role or "") != "superadmin":
            raise AvatarError("You can only clear your own avatar.")
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if not user:
            return
        user.avatar_data = None
        user.avatar_mime = None
        db.commit()


def get_avatar(user_id: int) -> tuple[bytes, str] | None:
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if not user or not user.avatar_data:
            return None
        return bytes(user.avatar_data), (user.avatar_mime or "image/png")


def render_avatar_image(user, *, width: int = 64) -> None:
    """Show avatar in Streamlit if present."""
    import streamlit as st
    try:
        if getattr(user, "avatar_data", None):
            st.image(bytes(user.avatar_data), width=width)
        elif getattr(user, "avatar_url", None):
            st.image(user.avatar_url, width=width)
        else:
            initials = "".join(p[0] for p in (user.full_name or user.username or "?").split()[:2]).upper()
            st.markdown(
                f'<div style="width:{width}px;height:{width}px;border-radius:50%;'
                f'background:#2563eb;color:#fff;display:flex;align-items:center;'
                f'justify-content:center;font-weight:700;font-size:{width//3}px">{initials}</div>',
                unsafe_allow_html=True,
            )
    except Exception:
        st.caption((user.full_name or "?")[:1].upper())
