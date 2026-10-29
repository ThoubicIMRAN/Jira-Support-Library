"""Profile avatar storage (bytes in DB) with validation."""
from __future__ import annotations

from database import SessionLocal, User

ALLOWED_MIME = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}
MAX_BYTES = 500 * 1024  # 500 KB


class AvatarError(ValueError):
    pass


def set_avatar(user_id: int, data: bytes, mime: str) -> None:
    mime = (mime or "").split(";")[0].strip().lower()
    if mime == "image/jpg":
        mime = "image/jpeg"
    if mime not in ALLOWED_MIME:
        raise AvatarError("Only PNG, JPEG, or WebP images are allowed.")
    if not data or len(data) > MAX_BYTES:
        raise AvatarError(f"Image must be between 1 byte and {MAX_BYTES // 1024} KB.")
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if not user:
            raise AvatarError("User not found.")
        user.avatar_mime = mime
        user.avatar_data = data
        db.commit()


def clear_avatar(user_id: int) -> None:
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if not user:
            return
        user.avatar_mime = None
        user.avatar_data = None
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

    data = getattr(user, "avatar_data", None)
    mime = getattr(user, "avatar_mime", None) or "image/png"
    if not data:
        got = get_avatar(getattr(user, "id", 0) or 0)
        if not got:
            st.caption("No photo")
            return
        data, mime = got
    st.image(bytes(data), width=width)
