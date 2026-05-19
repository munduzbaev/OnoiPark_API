"""
FastAPI dependencies: current_user, current_admin.
"""

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.supabase_client import supabase

_bearer = HTTPBearer(auto_error=False)


async def current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    """
    Validate Bearer token via Supabase Auth, enrich with role from profiles table.
    Returns: {id, email, user_metadata, role}
    """
    if credentials is None:
        raise HTTPException(status_code=401, detail="Unauthorized")

    token = credentials.credentials

    try:
        resp = supabase.auth.get_user(token)
        user = resp.user
        if user is None:
            raise HTTPException(status_code=401, detail="Unauthorized")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Unauthorized")

    role = "driver"
    try:
        profile_resp = (
            supabase.table("profiles")
            .select("role")
            .eq("id", user.id)
            .execute()
        )
        if profile_resp.data:
            role = profile_resp.data[0].get("role", "driver")
    except Exception:
        pass

    return {
        "id": user.id,
        "email": user.email,
        "user_metadata": user.user_metadata or {},
        "role": role,
    }


async def current_admin(user: dict = Depends(current_user)) -> dict:
    """Require role 'admin' or 'scanner'."""
    if user.get("role") not in ("admin", "scanner"):
        raise HTTPException(status_code=403, detail="Доступ запрещён")
    return user
