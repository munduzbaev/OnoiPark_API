"""
Admin router — /admin/sessions/all, /admin/history, /admin/users,
               /admin/sessions/manual-start, /admin/sessions/manual-end
"""

from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from app.deps import current_admin
from app.models.schemas import ManualStartRequest, ManualEndRequest
from app.supabase_client import supabase

router = APIRouter(prefix="/admin", tags=["admin"])


def _compute_cost(entered_at: str, price_per_hour: float, free_minutes: int) -> float:
    dt = datetime.fromisoformat(entered_at.replace("Z", "+00:00"))
    duration_minutes = (datetime.now(timezone.utc) - dt).total_seconds() / 60
    billable = max(0.0, duration_minutes - free_minutes)
    return round(billable / 60 * price_per_hour, 2)


@router.get("/sessions/all")
async def admin_all_sessions(user: dict = Depends(current_admin)):
    """Return all active sessions (waiting / active / exiting), enriched with driver profile."""
    try:
        sr = (
            supabase.table("parking_sessions")
            .select("*")
            .in_("status", ["waiting", "active", "exiting"])
            .order("created_at", desc=True)
            .execute()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    sessions_raw = sr.data or []

    # Bulk-fetch profiles and parkings — single query each, no N+1
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

    sessions = []
    for s in sessions_raw:
        profile = profiles_map.get(s.get("user_id") or "", {})
        sessions.append(
            {
                "id": str(s["id"]),
                "userId": str(s["user_id"]) if s.get("user_id") else None,
                "plateNumber": profile.get("plate_number") or None,
                "driverName": profile.get("name") or None,
                "parkingId": s.get("parking_id"),
                "parkingName": parkings_map.get(s.get("parking_id") or "", s.get("parking_id", "")),
                "spotNumber": s.get("spot_number"),
                "status": s["status"],
                "enteredAt": s.get("entered_at"),
                "cost": float(s.get("cost", 0)),
            }
        )
    return sessions


@router.get("/history")
async def admin_history(
    user: dict = Depends(current_admin),
    plate_number: str | None = Query(None, alias="plateNumber"),
    from_date: str | None = Query(None, alias="fromDate"),
    to_date: str | None = Query(None, alias="toDate"),
    limit: int = Query(500),
    offset: int = Query(0),
):
    """Return completed sessions for all users, enriched with driver profile."""
    try:
        q = (
            supabase.table("parking_sessions")
            .select("*")
            .eq("status", "completed")
        )
        if from_date:
            q = q.gte("exited_at", from_date)
        if to_date:
            q = q.lte("exited_at", to_date)
        q = q.order("exited_at", desc=True).range(offset, offset + limit - 1)
        sr = q.execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    sessions_raw = sr.data or []

    # Bulk-fetch profiles and parkings to avoid N+1 and fragile FK aliases
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

    history = []
    for s in sessions_raw:
        profile = profiles_map.get(s.get("user_id") or "", {})
        plate = profile.get("plate_number", "")

        if plate_number and plate and plate_number.lower() not in plate.lower():
            continue

        parking_name = parkings_map.get(s.get("parking_id") or "", s.get("parking_id", ""))
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
                "plateNumber": plate,
                "parkingName": parking_name,
                "spotNumber": s.get("spot_number"),
                "startTime": entered,
                "endTime": exited,
                "duration": duration,
                "cost": float(s.get("cost", 0)),
            }
        )

    return {"history": history}


@router.get("/users")
async def admin_users(user: dict = Depends(current_admin)):
    """Return all registered users from the profiles table."""
    try:
        pr = (
            supabase.table("profiles")
            .select("id, plate_number, phone_number, name, role, created_at")
            .order("created_at", desc=True)
            .execute()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    users = [
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
    return users


@router.post("/sessions/manual-start")
async def manual_start(
    body: ManualStartRequest,
    user: dict = Depends(current_admin),
):
    """
    Dashboard ManualEntryPage — start a session without a QR code.
    Requires plate_number and parking_id.
    """
    # Resolve driver
    driver_id: str | None = None
    try:
        pr = (
            supabase.table("profiles")
            .select("id")
            .eq("plate_number", body.plate_number)
            .execute()
        )
        if pr.data:
            driver_id = pr.data[0]["id"]
    except Exception:
        pass

    # Get parking
    try:
        pkg = supabase.table("parkings").select("*").eq("id", body.parking_id).execute()
        if not pkg.data:
            raise HTTPException(status_code=404, detail="Парковка не найдена")
        parking = pkg.data[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    spot_number = body.spot_number
    if spot_number is None:
        try:
            sp = (
                supabase.table("spots")
                .select("number")
                .eq("parking_id", body.parking_id)
                .eq("status", "available")
                .order("number")
                .limit(1)
                .execute()
            )
            if sp.data:
                spot_number = sp.data[0]["number"]
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
            supabase.table("spots").update(
                {"status": "occupied", "booked_by": driver_id}
            ).eq("parking_id", body.parking_id).eq("number", spot_number).execute()
        except Exception:
            pass

    session = ins.data[0] if ins.data else {}
    return {
        "success": True,
        "session": {
            "id": str(session.get("id", "")),
            "userId": driver_id,
            "parkingId": body.parking_id,
            "parkingName": parking.get("name", ""),
            "spotNumber": spot_number,
            "status": "active",
            "enteredAt": now,
            "cost": 0,
        },
    }


@router.post("/sessions/manual-end")
async def manual_end(
    body: ManualEndRequest,
    user: dict = Depends(current_admin),
):
    """Dashboard ManualEntryPage — end a session without a QR code."""
    try:
        sr = (
            supabase.table("parking_sessions")
            .select("*")
            .eq("id", body.session_id)
            .execute()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not sr.data:
        raise HTTPException(status_code=404, detail="Сессия не найдена")

    s = sr.data[0]
    if s["status"] not in ("waiting", "active"):
        raise HTTPException(
            status_code=400, detail=f"Сессия уже завершена (status={s['status']})"
        )

    parking = {}
    if s.get("parking_id"):
        try:
            pr = supabase.table("parkings").select("*").eq("id", s["parking_id"]).execute()
            if pr.data:
                parking = pr.data[0]
        except Exception:
            pass

    price_per_hour = float(parking.get("price_per_hour", 100))
    free_minutes = int(parking.get("free_minutes", 60))
    cost = 0.0
    entered = s.get("entered_at")
    if entered:
        cost = _compute_cost(entered, price_per_hour, free_minutes)

    now = datetime.now(timezone.utc).isoformat()
    try:
        supabase.table("parking_sessions").update(
            {"status": "completed", "exited_at": now, "cost": cost}
        ).eq("id", body.session_id).execute()

        if s.get("parking_id") and s.get("spot_number"):
            supabase.table("spots").update(
                {"status": "available", "booked_by": None}
            ).eq("parking_id", s["parking_id"]).eq("number", s["spot_number"]).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "success": True,
        "cost": cost,
        "message": (
            "Парковка была бесплатной"
            if cost == 0
            else f"Стоимость: {cost:.0f} сом"
        ),
    }
