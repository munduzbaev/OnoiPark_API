"""
Parkings router — /parkings, /parkings/{id}/spots
"""

from fastapi import APIRouter, HTTPException
from app.supabase_client import supabase

router = APIRouter(prefix="/parkings", tags=["parkings"])

_SEED_PARKINGS = [
    {
        "id": "parking-1",
        "name": "Университетская парковка",
        "address": "ул. Ленина, 1, Ош",
        "lat": 40.5283,
        "lng": 72.7985,
        "total_spots": 120,
        "price_per_hour": 100,
        "free_minutes": 60,
        "features": ["Охрана", "Видеонаблюдение", "Освещение"],
    },
    {
        "id": "parking-2",
        "name": 'Парковка у ресторана "Звезда"',
        "address": "пр. Масалиева, 15, Ош",
        "lat": 40.5310,
        "lng": 72.8020,
        "total_spots": 60,
        "price_per_hour": 100,
        "free_minutes": 60,
        "features": ["Крытая", "Охрана"],
    },
    {
        "id": "parking-3",
        "name": 'ТЦ "Центральный"',
        "address": "ул. Кыргызстан, 45, Ош",
        "lat": 40.5250,
        "lng": 72.7950,
        "total_spots": 200,
        "price_per_hour": 100,
        "free_minutes": 60,
        "features": ["Крытая", "Охрана", "Зарядка EV"],
    },
]


def _seed_parkings_and_spots():
    """Insert seed parkings and all their spots (all available)."""
    for p in _SEED_PARKINGS:
        supabase.table("parkings").upsert(p).execute()
        spots = [
            {
                "id": f"{p['id']}-spot-{i}",
                "parking_id": p["id"],
                "number": i,
                "status": "available",
            }
            for i in range(1, p["total_spots"] + 1)
        ]
        # Insert in chunks to avoid request size limits
        chunk = 100
        for start in range(0, len(spots), chunk):
            supabase.table("spots").upsert(spots[start : start + chunk]).execute()


def _count_available(parking_id: str) -> int:
    try:
        r = (
            supabase.table("spots")
            .select("id", count="exact")
            .eq("parking_id", parking_id)
            .eq("status", "available")
            .execute()
        )
        return r.count or 0
    except Exception:
        return 0


@router.get("")
async def list_parkings():
    """Return all parkings with live available_spots count."""
    try:
        resp = supabase.table("parkings").select("*").execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    rows = resp.data or []

    if not rows:
        _seed_parkings_and_spots()
        try:
            resp = supabase.table("parkings").select("*").execute()
            rows = resp.data or []
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    parkings = []
    for r in rows:
        available = _count_available(r["id"])
        parkings.append(
            {
                "id": r["id"],
                "name": r["name"],
                "address": r.get("address", ""),
                "totalSpots": r["total_spots"],
                "availableSpots": available,
                "pricePerHour": int(r.get("price_per_hour", 100)),
                "price": int(r.get("price_per_hour", 100)),
                "features": r.get("features") or [],
                "latitude": r.get("lat"),
                "longitude": r.get("lng"),
                "lat": r.get("lat"),
                "lng": r.get("lng"),
            }
        )

    return {"parkings": parkings}


@router.get("/{parking_id}/spots")
async def get_parking_spots(parking_id: str):
    """Return all spots for a specific parking."""
    try:
        pr = supabase.table("parkings").select("id").eq("id", parking_id).execute()
        if not pr.data:
            raise HTTPException(status_code=404, detail="Парковка не найдена")

        sr = (
            supabase.table("spots")
            .select("*")
            .eq("parking_id", parking_id)
            .order("number")
            .execute()
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    spots = [
        {
            "id": s["id"],
            "number": s["number"],
            "status": s["status"],
            "parkingId": s["parking_id"],
            "bookedBy": s.get("booked_by"),
        }
        for s in (sr.data or [])
    ]

    return {"spots": spots}
