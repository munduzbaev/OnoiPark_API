"""
Sessions router — /sessions/active, /sessions/all, /sessions/start, /sessions/end
"""

from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException
from app.deps import current_user, current_admin
from app.models.schemas import StartSessionRequest, EndSessionRequest
from app.supabase_client import supabase

router = APIRouter(prefix="/sessions", tags=["sessions"])

_ACTIVE_STATUSES = ("waiting", "active", "exiting")


def _compute_cost(entered_at: datetime, price_per_hour: float, free_minutes: int) -> float:
    now = datetime.now(timezone.utc)
    duration_minutes = (now - entered_at).total_seconds() / 60
    billable_minutes = max(0.0, duration_minutes - free_minutes)
    return round(billable_minutes / 60 * price_per_hour, 2)


def _get_parking(parking_id: str) -> dict:
    r = supabase.table("parkings").select("*").eq("id", parking_id).execute()
    if not r.data:
        raise HTTPException(status_code=404, detail="Парковка не найдена")
    return r.data[0]


def _free_spot(parking_id: str, spot_number: int):
    supabase.table("spots").update(
        {"status": "available", "booked_by": None}
    ).eq("parking_id", parking_id).eq("number", spot_number).execute()


def _occupy_spot(parking_id: str, spot_number: int, user_id: str):
    supabase.table("spots").update(
        {"status": "occupied", "booked_by": user_id}
    ).eq("parking_id", parking_id).eq("number", spot_number).execute()


def _session_to_dict(s: dict, parking: dict | None = None) -> dict:
    entered = s.get("entered_at")
    return {
        "id": str(s["id"]),
        "userId": str(s["user_id"]) if s.get("user_id") else None,
        "parkingId": s.get("parking_id"),
        "parkingName": (parking or {}).get("name", s.get("parking_id", "")),
        "spotNumber": s.get("spot_number"),
        "startTime": entered,
        "freeUntil": (
            (datetime.fromisoformat(entered.replace("Z", "+00:00"))
             + timedelta(minutes=int((parking or {}).get("free_minutes", 60)))).isoformat()
            if entered else None
        ),
        "status": s["status"],
        "cost": float(s.get("cost", 0)),
        "enteredAt": entered,
        "exitedAt": s.get("exited_at"),
    }


@router.get("/active")
async def get_active_session(user: dict = Depends(current_user)):
    """Return the caller's active session and parking info."""
    try:
        sr = (
            supabase.table("parking_sessions")
            .select("*")
            .eq("user_id", user["id"])
            .in_("status", list(_ACTIVE_STATUSES))
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not sr.data:
        return {"session": None, "parking": None}

    s = sr.data[0]
    parking = None
    parking_resp = None
    if s.get("parking_id"):
        try:
            pr = supabase.table("parkings").select("*").eq("id", s["parking_id"]).execute()
            if pr.data:
                parking = pr.data[0]
                parking_resp = {
                    "id": parking["id"],
                    "name": parking["name"],
                    "address": parking.get("address", ""),
                    "pricePerHour": int(parking.get("price_per_hour", 100)),
                    "freeMinutes": int(parking.get("free_minutes", 60)),
                }
        except Exception:
            pass

    return {"session": _session_to_dict(s, parking), "parking": parking_resp}


@router.get("/all")
async def get_all_sessions(user: dict = Depends(current_admin)):
    """Admin/scanner only — return all currently active sessions, enriched with driver profile."""
    try:
        sr = (
            supabase.table("parking_sessions")
            .select("*")
            .in_("status", list(_ACTIVE_STATUSES))
            .order("created_at", desc=True)
            .execute()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    sessions_raw = sr.data or []

    # Bulk-fetch profiles and parkings to avoid N+1 queries
    user_ids = list({s["user_id"] for s in sessions_raw if s.get("user_id")})
    parking_ids = list({s["parking_id"] for s in sessions_raw if s.get("parking_id")})

    profiles_map: dict = {}
    if user_ids:
        try:
            pr = (
                supabase.table("profiles")
                .select("id, plate_number, name")
                .in_("id", user_ids)
                .execute()
            )
            profiles_map = {p["id"]: p for p in (pr.data or [])}
        except Exception:
            pass

    parkings_map: dict = {}
    if parking_ids:
        try:
            pkr = (
                supabase.table("parkings")
                .select("id, name")
                .in_("id", parking_ids)
                .execute()
            )
            parkings_map = {p["id"]: p["name"] for p in (pkr.data or [])}
        except Exception:
            pass

    result = []
    for s in sessions_raw:
        profile = profiles_map.get(s.get("user_id") or "", {})
        session = _session_to_dict(s)
        session["plateNumber"] = profile.get("plate_number") or None
        session["driverName"] = profile.get("name") or None
        session["parkingName"] = parkings_map.get(s.get("parking_id") or "", s.get("parking_id", ""))
        result.append(session)

    return result


@router.post("/start")
async def start_session(
    body: StartSessionRequest,
    user: dict = Depends(current_admin),
):
    """
    Admin/scanner only — start a parking session for a driver identified by plate_number.
    """
    plate = body.plate_number
    if not plate:
        raise HTTPException(status_code=400, detail="plate_number is required")

    # Resolve driver user_id from plate
    driver_id: str | None = None
    try:
        pr = (
            supabase.table("profiles")
            .select("id")
            .eq("plate_number", plate)
            .execute()
        )
        if pr.data:
            driver_id = pr.data[0]["id"]
    except Exception:
        pass

    parking = _get_parking(body.parking_id)

    spot_number = body.spot_number
    if spot_number is None:
        # Auto-assign first available spot
        try:
            sr = (
                supabase.table("spots")
                .select("number")
                .eq("parking_id", body.parking_id)
                .eq("status", "available")
                .order("number")
                .limit(1)
                .execute()
            )
            if sr.data:
                spot_number = sr.data[0]["number"]
        except Exception:
            pass

    now = datetime.now(timezone.utc).isoformat()

    try:
        ins = (
            supabase.table("parking_sessions")
            .insert(
                {
                    "user_id": driver_id,
                    "parking_id": body.parking_id,
                    "spot_number": spot_number,
                    "status": "active",
                    "entered_at": now,
                }
            )
            .execute()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if driver_id and spot_number:
        try:
            _occupy_spot(body.parking_id, spot_number, driver_id)
        except Exception:
            pass

    session = ins.data[0] if ins.data else {"id": "unknown", "status": "active"}

    return {
        "success": True,
        "session": _session_to_dict(session, parking),
    }


@router.post("/end")
async def end_session(
    body: EndSessionRequest = EndSessionRequest(),
    user: dict = Depends(current_admin),
):
    """Admin/scanner only — end an active session and compute cost."""
    # Find session
    try:
        if body.session_id:
            sr = (
                supabase.table("parking_sessions")
                .select("*")
                .eq("id", body.session_id)
                .execute()
            )
        else:
            raise HTTPException(status_code=400, detail="session_id is required")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not sr.data:
        raise HTTPException(status_code=404, detail="Сессия не найдена")

    s = sr.data[0]
    if s["status"] not in ("waiting", "active"):
        raise HTTPException(
            status_code=400, detail=f"Сессия уже завершена (status={s['status']})"
        )

    parking = _get_parking(s["parking_id"])
    price_per_hour = float(parking.get("price_per_hour", 100))
    free_minutes = int(parking.get("free_minutes", 60))

    entered_at = s.get("entered_at")
    cost = 0.0
    if entered_at:
        dt = datetime.fromisoformat(entered_at.replace("Z", "+00:00"))
        cost = _compute_cost(dt, price_per_hour, free_minutes)

    now_iso = datetime.now(timezone.utc).isoformat()

    try:
        supabase.table("parking_sessions").update(
            {
                "status": "completed",
                "exited_at": now_iso,
                "cost": cost,
            }
        ).eq("id", s["id"]).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if s.get("parking_id") and s.get("spot_number"):
        try:
            _free_spot(s["parking_id"], s["spot_number"])
        except Exception:
            pass

    message = (
        "Парковка была бесплатной"
        if cost == 0
        else f"Стоимость парковки: {cost:.0f} сом"
    )

    return {
        "success": True,
        "session": {**_session_to_dict(s, parking), "status": "completed", "cost": cost},
        "cost": cost,
        "message": message,
    }
