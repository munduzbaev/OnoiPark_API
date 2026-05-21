"""Shared parking helpers used by both the QR and gate routers."""

import asyncio
from datetime import datetime, timezone

from app.supabase_client import supabase


def compute_cost(entered_iso: str, price_per_hour: float, free_minutes: int) -> float:
    dt = datetime.fromisoformat(entered_iso.replace("Z", "+00:00"))
    duration_minutes = (datetime.now(timezone.utc) - dt).total_seconds() / 60
    billable = max(0.0, duration_minutes - free_minutes)
    return round(billable / 60 * price_per_hour, 2)


async def finalize_completed(session_id: str) -> None:
    """Background: mark session 'completed' after 5-second gate-open window."""
    await asyncio.sleep(5)
    try:
        supabase.table("parking_sessions").update(
            {"status": "completed"}
        ).eq("id", session_id).execute()
    except Exception:
        pass
