from __future__ import annotations

from fastapi import Header, HTTPException

_ALLOWED_USER = "Neel"
_PASSWORD = "admin"


def require_user_id(
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    x_admin_password: str | None = Header(default=None, alias="X-Admin-Password"),
) -> str:
    """Demo-only auth: single fixed user + password."""
    if (x_admin_password or "").strip() != _PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid password")
    if (x_user_id or "").strip() != _ALLOWED_USER:
        raise HTTPException(status_code=401, detail="Unknown user")
    return _ALLOWED_USER

