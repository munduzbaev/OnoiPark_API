"""
Bookings router — /bookings/list, /bookings/create, /bookings/cancel
"""

from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException
from app.deps import current_user
from app.models.schemas import CreateBookingRequest, CancelBookingRequest
from app.supabase_client import supabase

router = APIRouter(prefix="/bookings", tags=["bookings"])


def _booking_to_dict(b: dict, parking_name: str = "") -> dict:
    return {
        "id": str(b["id"]),
        "userId": str(b["user_id"]),
        "parkingId": b["parking_id"],
        "parkingName": parking_name,
        "spotNumber": b["spot_number"],
        "createdAt": b.get("created_at"),
        "expiresAt": b.get("expires_at"),
        "status": b["status"],
    }


@router.get("/list")
async def list_bookings(user: dict = Depends(current_user)):
    """Return all active bookings for the current user."""
    try:
        br = (
            supabase.table("bookings")
            .select("*")
            .eq("user_id", user["id"])
            .eq("status", "active")
            .order("created_at", desc=True)
            .execute()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Expire bookings whose expires_at has passed
    now = datetime.now(timezone.utc)
    active = []
    for b in (br.data or []):
        exp = b.get("expires_at")
        if exp:
            exp_dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
            if exp_dt < now:
                try:
                    supabase.table("bookings").update({"status": "expired"}).eq("id", b["id"]).execute()
                    supabase.table("spots").update(
                        {"status": "available", "booked_by": None}
                    ).eq("parking_id", b["parking_id"]).eq("number", b["spot_number"]).execute()
                except Exception:
                    pass
                continue
        active.append(b)

    # Enrich with parking names
    parking_names: dict[str, str] = {}
    parking_ids = list({b["parking_id"] for b in active})
    if parking_ids:
        try:
            pr = supabase.table("parkings").select("id, name").in_("id", parking_ids).execute()
            parking_names = {p["id"]: p["name"] for p in (pr.data or [])}
        except Exception:
            pass

    bookings = [_booking_to_dict(b, parking_names.get(b["parking_id"], "")) for b in active]
    return {"bookings": bookings}


@router.post("/create")
async def create_booking(
    body: CreateBookingRequest,
    user: dict = Depends(current_user),
):
    """Create a 15-minute booking for an available spot."""
    # Check spot availability
    try:
        sr = (
            supabase.table("spots")
            .select("*")
            .eq("parking_id", body.parking_id)
            .eq("number", body.spot_number)
            .execute()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not sr.data:
        raise HTTPException(status_code=404, detail="Место не найдено")

    spot = sr.data[0]
    if spot["status"] != "available":
        raise HTTPException(
            status_code=409,
            detail=f"Место {body.spot_number} недоступно (статус: {spot['status']})",
        )

    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(minutes=15)).isoformat()

    try:
        ins = (
            supabase.table("bookings")
            .insert(
                {
                    "user_id": user["id"],
                    "parking_id": body.parking_id,
                    "spot_number": body.spot_number,
                    "status": "active",
                    "expires_at": expires_at,
                }
            )
            .execute()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Mark spot as booked
    try:
        supabase.table("spots").update(
            {"status": "booked", "booked_by": user["id"]}
        ).eq("parking_id", body.parking_id).eq("number", body.spot_number).execute()
    except Exception:
        pass

    booking = ins.data[0] if ins.data else {}
    parking_name = ""
    try:
        pr = supabase.table("parkings").select("name").eq("id", body.parking_id).execute()
        if pr.data:
            parking_name = pr.data[0]["name"]
    except Exception:
        pass

    return {"success": True, "booking": _booking_to_dict(booking, parking_name)}


@router.post("/cancel")
async def cancel_booking(
    body: CancelBookingRequest,
    user: dict = Depends(current_user),
):
    """Cancel an existing booking and free the spot."""
    try:
        br = (
            supabase.table("bookings")
            .select("*")
            .eq("id", body.booking_id)
            .eq("user_id", user["id"])
            .execute()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not br.data:
        raise HTTPException(status_code=404, detail="Бронирование не найдено")

    booking = br.data[0]
    if booking["status"] != "active":
        raise HTTPException(
            status_code=400, detail="Бронирование уже отменено или завершено"
        )

    try:
        supabase.table("bookings").update({"status": "cancelled"}).eq("id", body.booking_id).execute()
        supabase.table("spots").update(
            {"status": "available", "booked_by": None}
        ).eq("parking_id", booking["parking_id"]).eq("number", booking["spot_number"]).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"success": True, "message": "Бронирование отменено"}
