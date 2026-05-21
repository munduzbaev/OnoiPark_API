"""
Auth router — /auth/signup, /auth/signin, /auth/me, /auth/reset-password
"""

from fastapi import APIRouter, Depends, HTTPException
from app.deps import current_user
from app.supabase_client import supabase
from app.models.schemas import (
    SignupRequest,
    SigninRequest,
    ResetPasswordRequest,
    UserProfile,
)

router = APIRouter(prefix="/auth", tags=["auth"])

_DEFAULT_NOTIFICATIONS = {
    "bookingConfirmation": True,
    "freeTimeExpiring": True,
    "paidTimeExpiring": True,
    "paymentConfirmation": True,
}


@router.post("/signup")
async def signup(body: SignupRequest):
    """
    Register a new user.
    Creates a Supabase Auth account and inserts a profiles row.
    """
    # Reject if plate already registered (checked in profiles, not just auth)
    try:
        existing = (
            supabase.table("profiles")
            .select("id")
            .eq("plate_number", body.plate_number)
            .execute()
        )
        if existing.data:
            raise HTTPException(
                status_code=400,
                detail="Пользователь с таким госномером уже зарегистрирован",
            )
    except HTTPException:
        raise
    except Exception:
        pass  # profiles table may not exist on first run; let auth.create_user be the guard

    email = f"{body.plate_number.lower()}@onoipark.app"

    try:
        resp = supabase.auth.admin.create_user(
            {
                "email": email,
                "password": body.phone_number,
                "email_confirm": True,
                "user_metadata": {
                    "name": body.name,
                    "plateNumber": body.plate_number,
                    "phoneNumber": body.phone_number,
                    "notificationSettings": _DEFAULT_NOTIFICATIONS,
                },
            }
        )
    except Exception as e:
        detail = str(e)
        if "already been registered" in detail.lower() or "duplicate" in detail.lower():
            raise HTTPException(
                status_code=400,
                detail="Пользователь с таким госномером уже зарегистрирован",
            )
        raise HTTPException(status_code=500, detail=f"Ошибка регистрации: {detail}")

    user = resp.user
    if user is None:
        raise HTTPException(status_code=400, detail="Failed to create user")

    # Insert profile row
    try:
        supabase.table("profiles").insert(
            {
                "id": user.id,
                "plate_number": body.plate_number,
                "phone_number": body.phone_number,
                "name": body.name,
                "role": "driver",
                "notification_settings": _DEFAULT_NOTIFICATIONS,
            }
        ).execute()
    except Exception as e:
        # Auth user was created; profile insert failed. Log and continue — profile
        # will be back-filled on next signin.
        pass

    return {
        "success": True,
        "user": {
            "id": user.id,
            "plateNumber": body.plate_number,
            "phoneNumber": body.phone_number,
            "name": body.name,
            "notificationSettings": _DEFAULT_NOTIFICATIONS,
        },
        "message": "Регистрация прошла успешно",
    }


@router.post("/signin")
async def signin(body: SigninRequest):
    """
    Sign in an existing user.
    Returns access_token and user profile.
    """
    email = f"{body.plate_number.lower()}@onoipark.app"

    try:
        resp = supabase.auth.sign_in_with_password(
            {"email": email, "password": body.phone_number}
        )
    except Exception:
        raise HTTPException(
            status_code=401, detail="Неверный госномер или номер телефона"
        )

    session = resp.session
    user = resp.user

    if session is None or user is None:
        raise HTTPException(
            status_code=401, detail="Неверный госномер или номер телефона"
        )

    meta = user.user_metadata or {}

    # Fetch profile for authoritative data; fall back to user_metadata
    profile = {}
    try:
        pr = (
            supabase.table("profiles")
            .select("*")
            .eq("id", user.id)
            .execute()
        )
        if pr.data:
            profile = pr.data[0]
        else:
            # Back-fill missing profile (user existed before Phase 2)
            supabase.table("profiles").upsert(
                {
                    "id": user.id,
                    "plate_number": meta.get("plateNumber", body.plate_number),
                    "phone_number": meta.get("phoneNumber", body.phone_number),
                    "name": meta.get("name", ""),
                    "role": "driver",
                    "notification_settings": meta.get(
                        "notificationSettings", _DEFAULT_NOTIFICATIONS
                    ),
                }
            ).execute()
    except Exception:
        pass

    user_data = {
        "id": user.id,
        "plateNumber": profile.get("plate_number") or meta.get("plateNumber", body.plate_number),
        "phoneNumber": profile.get("phone_number") or meta.get("phoneNumber", body.phone_number),
        "name": profile.get("name") or meta.get("name", ""),
        "notificationSettings": profile.get("notification_settings")
            or meta.get("notificationSettings", _DEFAULT_NOTIFICATIONS),
    }

    return {
        "success": True,
        "access_token": session.access_token,
        "user": user_data,
    }


@router.get("/me")
async def me(user: dict = Depends(current_user)):
    """Return the current authenticated user's profile from profiles table."""
    meta = user.get("user_metadata", {})

    profile = {}
    try:
        pr = (
            supabase.table("profiles")
            .select("*")
            .eq("id", user["id"])
            .execute()
        )
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
                or meta.get("notificationSettings", _DEFAULT_NOTIFICATIONS),
        }
    }


@router.post("/reset-password")
async def reset_password(body: ResetPasswordRequest):
    """
    Reset password (update phone number).
    Verifies old phone, then updates auth password and profiles.phone_number.
    """
    email = f"{body.plate_number.lower()}@onoipark.app"

    try:
        resp = supabase.auth.sign_in_with_password(
            {"email": email, "password": body.old_phone_number}
        )
        user = resp.user
        if user is None:
            raise HTTPException(
                status_code=401, detail="Неверный текущий номер телефона"
            )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=401, detail="Неверный текущий номер телефона"
        )

    try:
        supabase.auth.admin.update_user_by_id(
            user.id, {"password": body.new_phone_number}
        )
        supabase.auth.admin.update_user_by_id(
            user.id,
            {
                "user_metadata": {
                    **(user.user_metadata or {}),
                    "phoneNumber": body.new_phone_number,
                }
            },
        )
        supabase.table("profiles").update(
            {"phone_number": body.new_phone_number}
        ).eq("id", user.id).execute()
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Ошибка сброса пароля: {str(e)}"
        )

    return {"success": True, "message": "Пароль успешно обновлен"}


@router.post("/verify-user")
async def verify_user(body: SigninRequest):
    """Verify a user exists with given plate + phone. Used by mobile app password reset flow."""
    email = f"{body.plate_number.lower()}@onoipark.app"
    try:
        resp = supabase.auth.sign_in_with_password(
            {"email": email, "password": body.phone_number}
        )
        if resp.user is None:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        return {"success": True, "message": "Пользователь подтвержден"}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Неверный номер телефона")
