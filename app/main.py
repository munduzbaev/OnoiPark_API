"""
FastAPI app factory — includes all routers, CORS, and shared endpoints.
"""

from datetime import datetime, timezone

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.deps import current_user, current_admin
from app.models.schemas import UpdateSettingsRequest
from app.routers import auth, parkings, sessions, bookings, qr, admin, gate
from app.supabase_client import supabase

app = FastAPI(
    title="OnoiPark API",
    version="2.0.0",
    description="Backend API for the OnoiPark automated parking system (Osh, Kyrgyzstan)",
    swagger_ui_parameters={"syntaxHighlight.theme": "obsidian", "persistAuthorization": True},
)

# ---- CORS ----
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- Routers (all under /api) ----
api_prefix = "/api"

app.include_router(auth.router, prefix=api_prefix)
app.include_router(parkings.router, prefix=api_prefix)
app.include_router(sessions.router, prefix=api_prefix)
app.include_router(bookings.router, prefix=api_prefix)
app.include_router(qr.router, prefix=api_prefix)
app.include_router(admin.router, prefix=api_prefix)
app.include_router(gate.router, prefix=api_prefix)


# ---- Health ----
@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "2.0.0"}


# ---------------------------------------------------------------------------
# Shared endpoints: history, user profile, settings
# ---------------------------------------------------------------------------

@app.get("/api/history")
async def get_history(user: dict = Depends(current_user)):
    """Return completed parking sessions for the current user."""
    try:
        sr = (
            supabase.table("parking_sessions")
            .select("*, parkings(name)")
            .eq("user_id", user["id"])
            .eq("status", "completed")
            .order("exited_at", desc=True)
            .execute()
        )
    except Exception:
        return {"history": []}

    history = []
    for s in (sr.data or []):
        parking_data = s.get("parkings") or {}
        parking_name = (
            parking_data.get("name", s.get("parking_id", ""))
            if isinstance(parking_data, dict)
            else s.get("parking_id", "")
        )
        entered = s.get("entered_at") or s.get("created_at", "")
        exited = s.get("exited_at", "")
        duration = 0.0
        if entered and exited:
            try:
                d_in = datetime.fromisoformat(entered.replace("Z", "+00:00"))
                d_out = datetime.fromisoformat(exited.replace("Z", "+00:00"))
                duration = round((d_out - d_in).total_seconds() / 60, 1)
            except Exception:
                pass

        history.append(
            {
                "id": str(s["id"]),
                "parkingName": parking_name,
                "spotNumber": s.get("spot_number"),
                "startTime": entered,
                "endTime": exited,
                "duration": duration,
                "cost": float(s.get("cost", 0)),
            }
        )

    return {"history": history}


@app.get("/api/history/all")
async def get_all_users(user: dict = Depends(current_admin)):
    """Admin: return all profiles (used by dashboard api.getAllUsers())."""
    try:
        pr = (
            supabase.table("profiles")
            .select("id, plate_number, phone_number, name, role, created_at")
            .order("created_at", desc=True)
            .execute()
        )
    except Exception:
        return []

    return [
        {
            "id": str(u["id"]),
            "plateNumber": u["plate_number"],
            "phoneNumber": u["phone_number"],
            "name": u.get("name", ""),
            "role": u.get("role", "driver"),
            "createdAt": u.get("created_at"),
        }
        for u in (pr.data or [])
    ]


@app.get("/api/user/profile")
async def get_user_profile(user: dict = Depends(current_user)):
    """Return the current user's profile."""
    meta = user.get("user_metadata", {})
    profile = {}
    try:
        pr = supabase.table("profiles").select("*").eq("id", user["id"]).execute()
        if pr.data:
            profile = pr.data[0]
    except Exception:
        pass

    return {
        "user": {
            "id": user["id"],
            "plateNumber": profile.get("plate_number") or meta.get("plateNumber", ""),
            "phoneNumber": profile.get("phone_number") or meta.get("phoneNumber", ""),
            "name": profile.get("name") or meta.get("name", ""),
            "notificationSettings": profile.get("notification_settings")
                or meta.get("notificationSettings", {}),
        }
    }


@app.post("/api/user/update-settings")
async def update_settings(
    body: UpdateSettingsRequest,
    user: dict = Depends(current_user),
):
    """Update user notification settings — persisted in profiles table."""
    meta = user.get("user_metadata", {})
    settings_data = body.notification_settings or {}

    try:
        supabase.table("profiles").update(
            {"notification_settings": settings_data}
        ).eq("id", user["id"]).execute()
    except Exception:
        pass

    try:
        supabase.auth.admin.update_user_by_id(
            user["id"],
            {"user_metadata": {**meta, "notificationSettings": settings_data}},
        )
    except Exception:
        pass

    return {
        "success": True,
        "user": {
            "id": user["id"],
            "plateNumber": meta.get("plateNumber", ""),
            "phoneNumber": meta.get("phoneNumber", ""),
            "name": meta.get("name", ""),
            "notificationSettings": settings_data,
        },
    }


@app.delete("/api/user/delete-account")
async def delete_account(user: dict = Depends(current_user)):
    """Delete the current user's account and their profile."""
    try:
        supabase.table("profiles").delete().eq("id", user["id"]).execute()
    except Exception:
        pass
    try:
        supabase.auth.admin.delete_user(user["id"])
        return {"success": True, "message": "Аккаунт успешно удален"}
    except Exception as e:
        return {"success": False, "error": f"Не удалось удалить аккаунт: {str(e)}"}


# ---------------------------------------------------------------------------
# Duplicate routes without /api prefix for backward compatibility
# ---------------------------------------------------------------------------

app.include_router(auth.router)
app.include_router(parkings.router)
app.include_router(sessions.router)
app.include_router(bookings.router)
app.include_router(qr.router)
app.include_router(admin.router)
app.include_router(gate.router)


@app.get("/health")
async def health_no_prefix():
    return {"status": "ok", "version": "2.0.0"}


@app.get("/history")
async def get_history_no_prefix(user: dict = Depends(current_user)):
    return await get_history(user)


@app.get("/history/all")
async def get_all_users_no_prefix(user: dict = Depends(current_admin)):
    return await get_all_users(user)


@app.get("/user/profile")
async def get_user_profile_no_prefix(user: dict = Depends(current_user)):
    return await get_user_profile(user)


@app.post("/user/update-settings")
async def update_settings_no_prefix(
    body: UpdateSettingsRequest,
    user: dict = Depends(current_user),
):
    return await update_settings(body, user)


@app.delete("/user/delete-account")
async def delete_account_no_prefix(user: dict = Depends(current_user)):
    return await delete_account(user)
