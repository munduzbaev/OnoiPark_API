"""
QR router — /qr/generate, /qr/validate

JWT-signed one-shot token system:
  generate  → mobile app calls this to get a QR payload
  validate  → scanner (dashboard / tablet) calls this to let a car in or out
"""

from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from jose import jwt, JWTError, ExpiredSignatureError

from app.config import settings
from app.deps import current_user, current_admin
from app.models.schemas import ValidateQRRequest
from app.services.parking import finalize_completed
from app.supabase_client import supabase

router = APIRouter(prefix="/qr", tags=["qr"])

_ALGORITHM = "HS256"
_TTL_MINUTES = 15


@router.get("/generate")
async def generate_qr(user: dict = Depends(current_user)):
    """
    Generate a JWT-signed QR token with a one-shot nonce.
    Called by the mobile app; returned token is encoded in the QR image.
    """
    meta = user.get("user_metadata", {})
    plate_number = meta.get("plateNumber", "")

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=_TTL_MINUTES)

    # Persist nonce to prevent replay
    try:
        nonce_resp = (
            supabase.table("qr_nonces")
            .insert(
                {
                    "user_id": user["id"],
                    "used": False,
                    "expires_at": expires_at.isoformat(),
                }
            )
            .execute()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка создания QR: {str(e)}")

    nonce_id = nonce_resp.data[0]["id"]

    payload = {
        "sub": user["id"],
        "plt": plate_number,
        "kid": str(nonce_id),
        "exp": int(expires_at.timestamp()),
        "iat": int(now.timestamp()),
        "iss": "onoipark-api",
    }
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=_ALGORITHM)

    return {
        "token": token,
        "expiresAt": expires_at.isoformat(),
    }


@router.post("/validate")
async def validate_qr(
    body: ValidateQRRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(current_admin),
):
    """
    Validate a QR token and trigger entry or exit.
    Called by the dashboard scanner or a future tablet UI.
    Caller must have role 'admin' or 'scanner'.
    """
    # 1 — Decode and verify JWT
    try:
        payload = jwt.decode(
            body.token,
            settings.JWT_SECRET,
            algorithms=[_ALGORITHM],
            options={"verify_iss": True},
            issuer="onoipark-api",
        )
    except ExpiredSignatureError:
        raise HTTPException(status_code=400, detail={"code": "expired", "message": "QR код истёк"})
    except JWTError:
        raise HTTPException(
            status_code=400, detail={"code": "invalid_token", "message": "Недействительный QR код"}
        )

    driver_user_id: str = payload["sub"]
    nonce_id: str = payload["kid"]

    # 2 — Check nonce is not already used
    try:
        nr = (
            supabase.table("qr_nonces")
            .select("*")
            .eq("id", nonce_id)
            .execute()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not nr.data:
        raise HTTPException(
            status_code=400, detail={"code": "invalid_token", "message": "Нонс не найден"}
        )

    nonce = nr.data[0]
    if nonce["used"]:
        raise HTTPException(
            status_code=400,
            detail={"code": "already_used", "message": "QR код уже использован"},
        )

    # 3 — Mark nonce used
    now = datetime.now(timezone.utc).isoformat()
    try:
        supabase.table("qr_nonces").update(
            {"used": True, "used_at": now}
        ).eq("id", nonce_id).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    parking_id = body.parking_id
    spot_number = body.spot_number

    # 4 — Determine action based on driver's current session state
    try:
        # Check for 'waiting' session
        waiting_r = (
            supabase.table("parking_sessions")
            .select("*")
            .eq("user_id", driver_user_id)
            .eq("status", "waiting")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        # Check for 'active' session
        active_r = (
            supabase.table("parking_sessions")
            .select("*")
            .eq("user_id", driver_user_id)
            .eq("status", "active")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        # Check for active booking
        booking_r = (
            supabase.table("bookings")
            .select("*")
            .eq("user_id", driver_user_id)
            .eq("status", "active")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # --- Case A: waiting session → transition to active (entry) ---
    if waiting_r.data:
        s = waiting_r.data[0]
        eff_spot = spot_number or s.get("spot_number")
        eff_parking = parking_id or s.get("parking_id")
        try:
            supabase.table("parking_sessions").update(
                {
                    "status": "active",
                    "entered_at": now,
                    "parking_id": eff_parking,
                    "spot_number": eff_spot,
                }
            ).eq("id", s["id"]).execute()
            if eff_parking and eff_spot:
                supabase.table("spots").update(
                    {"status": "occupied", "booked_by": driver_user_id}
                ).eq("parking_id", eff_parking).eq("number", eff_spot).execute()
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

        return {
            "action": "entry",
            "session_id": str(s["id"]),
            "message": "Въезд разрешён",
        }

    # --- Case B: active session → transition to exiting (exit) ---
    if active_r.data:
        s = active_r.data[0]
        entered = s.get("entered_at")
        cost = 0.0
        if entered and s.get("parking_id"):
            try:
                pr = supabase.table("parkings").select("price_per_hour, free_minutes").eq(
                    "id", s["parking_id"]
                ).execute()
                if pr.data:
                    p = pr.data[0]
                    entered_dt = datetime.fromisoformat(entered.replace("Z", "+00:00"))
                    duration_minutes = (datetime.now(timezone.utc) - entered_dt).total_seconds() / 60
                    billable = max(0.0, duration_minutes - float(p.get("free_minutes", 60)))
                    cost = round(billable / 60 * float(p.get("price_per_hour", 100)), 2)
            except Exception:
                pass

        try:
            supabase.table("parking_sessions").update(
                {
                    "status": "exiting",
                    "exited_at": now,
                    "cost": cost,
                }
            ).eq("id", s["id"]).execute()

            if s.get("parking_id") and s.get("spot_number"):
                supabase.table("spots").update(
                    {"status": "available", "booked_by": None}
                ).eq("parking_id", s["parking_id"]).eq("number", s["spot_number"]).execute()
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

        # Finalize to 'completed' after 5-second gate-open window
        background_tasks.add_task(finalize_completed, str(s["id"]))

        return {
            "action": "exit",
            "session_id": str(s["id"]),
            "cost": cost,
            "message": (
                "Выезд разрешён — парковка бесплатна"
                if cost == 0
                else f"Выезд разрешён — стоимость {cost:.0f} сом"
            ),
        }

    # --- Case C: active booking → create session directly in active (entry) ---
    if booking_r.data:
        b = booking_r.data[0]
        exp = b.get("expires_at")
        if exp:
            exp_dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
            if exp_dt < datetime.now(timezone.utc):
                # Expired booking — fall through to no_active_booking
                pass
            else:
                eff_spot = spot_number or b.get("spot_number")
                eff_parking = parking_id or b.get("parking_id")
                try:
                    ins = (
                        supabase.table("parking_sessions")
                        .insert(
                            {
                                "user_id": driver_user_id,
                                "parking_id": eff_parking,
                                "spot_number": eff_spot,
                                "status": "active",
                                "entered_at": now,
                            }
                        )
                        .execute()
                    )
                    supabase.table("bookings").update(
                        {"status": "completed"}
                    ).eq("id", b["id"]).execute()
                    if eff_parking and eff_spot:
                        supabase.table("spots").update(
                            {"status": "occupied", "booked_by": driver_user_id}
                        ).eq("parking_id", eff_parking).eq("number", eff_spot).execute()
                except Exception as e:
                    raise HTTPException(status_code=500, detail=str(e))

                session_id = ins.data[0]["id"] if ins.data else "unknown"
                return {
                    "action": "entry",
                    "session_id": str(session_id),
                    "message": "Въезд разрешён",
                }

    # --- Case D: no session or booking ---
    # Create a fresh active session (direct entry without prior booking)
    eff_spot = spot_number
    eff_parking = parking_id
    if eff_parking:
        try:
            ins = (
                supabase.table("parking_sessions")
                .insert(
                    {
                        "user_id": driver_user_id,
                        "parking_id": eff_parking,
                        "spot_number": eff_spot,
                        "status": "active",
                        "entered_at": now,
                    }
                )
                .execute()
            )
            if eff_spot:
                supabase.table("spots").update(
                    {"status": "occupied", "booked_by": driver_user_id}
                ).eq("parking_id", eff_parking).eq("number", eff_spot).execute()

            session_id = ins.data[0]["id"] if ins.data else "unknown"
            return {
                "action": "entry",
                "session_id": str(session_id),
                "message": "Въезд разрешён",
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    raise HTTPException(
        status_code=400,
        detail={
            "code": "no_active_booking",
            "message": "Нет активной брони или сессии",
        },
    )
