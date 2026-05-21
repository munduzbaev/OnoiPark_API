"""
Gate router — /gate/scan

Driver scans the static QR displayed at the barrier (KPP).
Security comes from the driver's Bearer token — no secret in the gate QR.
Gate mapping is hardcoded; expand GATE_TO_PARKING as new barriers are installed.
"""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.deps import current_user
from app.models.schemas import GateScanRequest
from app.services.parking import compute_cost, finalize_completed
from app.supabase_client import supabase

router = APIRouter(prefix="/gate", tags=["gate"])

GATE_TO_PARKING: dict[str, str] = {
    "gate-1": "parking-1",
}


def _parse_gate_id(raw: str) -> str:
    """Accept bare 'gate-1' or JSON '{"gate":"gate-1"}' — return the bare id."""
    stripped = raw.strip()
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict) and "gate" in parsed:
            return str(parsed["gate"])
    except (ValueError, TypeError):
        pass
    return stripped


@router.post("/scan")
async def gate_scan(
    body: GateScanRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(current_user),
):
    """
    Called by the mobile app when the driver scans the gate QR.
    Determines entry or exit and updates parking_sessions accordingly.
    parking_sessions is in the Supabase Realtime publication — status changes
    trigger the local bridge that opens the Arduino-controlled barrier.
    """
    gate_id = _parse_gate_id(body.gate_id)
    parking_id = GATE_TO_PARKING.get(gate_id)
    if not parking_id:
        raise HTTPException(
            status_code=400,
            detail={"code": "unknown_gate", "message": "Неизвестные ворота"},
        )

    driver_user_id = user["id"]
    now = datetime.now(timezone.utc).isoformat()

    # ── Look up active session at this parking ────────────────────────────────
    try:
        active_r = (
            supabase.table("parking_sessions")
            .select("*")
            .eq("user_id", driver_user_id)
            .eq("parking_id", parking_id)
            .eq("status", "active")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # ── EXIT ──────────────────────────────────────────────────────────────────
    if active_r.data:
        s = active_r.data[0]
        cost = 0.0
        entered = s.get("entered_at")
        if entered:
            try:
                pr = (
                    supabase.table("parkings")
                    .select("price_per_hour, free_minutes")
                    .eq("id", parking_id)
                    .execute()
                )
                if pr.data:
                    p = pr.data[0]
                    cost = compute_cost(
                        entered,
                        float(p.get("price_per_hour", 100)),
                        int(p.get("free_minutes", 60)),
                    )
            except Exception:
                pass

        try:
            supabase.table("parking_sessions").update(
                {"status": "exiting", "exited_at": now, "cost": cost}
            ).eq("id", s["id"]).execute()

            if s.get("spot_number"):
                supabase.table("spots").update(
                    {"status": "available", "booked_by": None}
                ).eq("parking_id", parking_id).eq("number", s["spot_number"]).execute()
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

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

    # ── ENTRY ─────────────────────────────────────────────────────────────────
    spot_number: int | None = None
    booking_id: str | None = None

    # Check for valid active booking at this parking
    try:
        booking_r = (
            supabase.table("bookings")
            .select("*")
            .eq("user_id", driver_user_id)
            .eq("parking_id", parking_id)
            .eq("status", "active")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if booking_r.data:
        b = booking_r.data[0]
        exp = b.get("expires_at")
        if exp:
            exp_dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
            if exp_dt >= datetime.now(timezone.utc):
                spot_number = b.get("spot_number")
                booking_id = str(b["id"])

    # Auto-assign first available spot if no booking
    if spot_number is None:
        try:
            sr = (
                supabase.table("spots")
                .select("number")
                .eq("parking_id", parking_id)
                .eq("status", "available")
                .order("number")
                .limit(1)
                .execute()
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

        if not sr.data:
            raise HTTPException(
                status_code=400,
                detail={"code": "no_spots", "message": "Нет свободных мест"},
            )
        spot_number = sr.data[0]["number"]

    # Create active session + mark spot occupied
    try:
        ins = (
            supabase.table("parking_sessions")
            .insert(
                {
                    "user_id": driver_user_id,
                    "parking_id": parking_id,
                    "spot_number": spot_number,
                    "status": "active",
                    "entered_at": now,
                }
            )
            .execute()
        )
        supabase.table("spots").update(
            {"status": "occupied", "booked_by": driver_user_id}
        ).eq("parking_id", parking_id).eq("number", spot_number).execute()

        if booking_id:
            supabase.table("bookings").update(
                {"status": "completed"}
            ).eq("id", booking_id).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    session_id = ins.data[0]["id"] if ins.data else "unknown"

    return {
        "action": "entry",
        "session_id": str(session_id),
        "spot_number": spot_number,
        "message": f"Въезд разрешён. Место {spot_number}",
    }
