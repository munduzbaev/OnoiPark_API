"""
Session flow tests: booking → entry → exit
"""

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest

from tests.conftest import DRIVER_USER, ADMIN_USER, DRIVER_ID, PLATE

_PARKING_ID = "parking-1"
_SPOT_NUMBER = 7
_SESSION_ID = str(uuid.uuid4())
_BOOKING_ID = str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Create booking
# ---------------------------------------------------------------------------

def test_create_booking_available_spot(client_as_driver, mock_supabase):
    spot_row = {"id": f"{_PARKING_ID}-spot-{_SPOT_NUMBER}", "number": _SPOT_NUMBER,
                "status": "available", "parking_id": _PARKING_ID}
    booking_row = {
        "id": _BOOKING_ID,
        "user_id": DRIVER_ID,
        "parking_id": _PARKING_ID,
        "spot_number": _SPOT_NUMBER,
        "status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
    }
    results = iter([
        MagicMock(data=[spot_row], count=1),       # spots select
        MagicMock(data=[booking_row], count=1),    # bookings insert
        MagicMock(data=[], count=0),               # spots update (booked)
        MagicMock(data=[{"name": "Test Parking"}], count=1),  # parkings name
    ])
    mock_supabase.execute.side_effect = lambda: next(results)

    resp = client_as_driver.post(
        "/api/bookings/create",
        json={"parkingId": _PARKING_ID, "spotNumber": _SPOT_NUMBER},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["booking"]["spotNumber"] == _SPOT_NUMBER


def test_create_booking_occupied_spot(client_as_driver, mock_supabase):
    spot_row = {"id": f"{_PARKING_ID}-spot-{_SPOT_NUMBER}", "number": _SPOT_NUMBER,
                "status": "occupied", "parking_id": _PARKING_ID}
    mock_supabase.execute.return_value = MagicMock(data=[spot_row], count=1)

    resp = client_as_driver.post(
        "/api/bookings/create",
        json={"parkingId": _PARKING_ID, "spotNumber": _SPOT_NUMBER},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Cancel booking
# ---------------------------------------------------------------------------

def test_cancel_booking(client_as_driver, mock_supabase):
    booking_row = {
        "id": _BOOKING_ID,
        "user_id": DRIVER_ID,
        "parking_id": _PARKING_ID,
        "spot_number": _SPOT_NUMBER,
        "status": "active",
    }
    results = iter([
        MagicMock(data=[booking_row], count=1),  # bookings select
        MagicMock(data=[], count=0),             # bookings update (cancelled)
        MagicMock(data=[], count=0),             # spots update (available)
    ])
    mock_supabase.execute.side_effect = lambda: next(results)

    resp = client_as_driver.post(
        "/api/bookings/cancel",
        json={"bookingId": _BOOKING_ID},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True


# ---------------------------------------------------------------------------
# Manual start (admin)
# ---------------------------------------------------------------------------

def test_manual_start_session(client_as_admin, mock_supabase):
    parking_row = {"id": _PARKING_ID, "name": "Test Parking",
                   "price_per_hour": 100, "free_minutes": 60}
    session_row = {
        "id": _SESSION_ID,
        "user_id": DRIVER_ID,
        "parking_id": _PARKING_ID,
        "spot_number": _SPOT_NUMBER,
        "status": "active",
        "entered_at": datetime.now(timezone.utc).isoformat(),
    }
    results = iter([
        MagicMock(data=[{"id": DRIVER_ID}], count=1),     # profiles select by plate
        MagicMock(data=[parking_row], count=1),            # parkings select
        MagicMock(data=[{"number": _SPOT_NUMBER}], count=1),  # spots (auto-assign)
        MagicMock(data=[session_row], count=1),            # sessions insert
        MagicMock(data=[], count=0),                       # spots update (occupied)
    ])
    mock_supabase.execute.side_effect = lambda: next(results)

    resp = client_as_admin.post(
        "/api/admin/sessions/manual-start",
        json={"plateNumber": PLATE, "parkingId": _PARKING_ID},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["session"]["status"] == "active"


# ---------------------------------------------------------------------------
# Manual end with cost computation
# ---------------------------------------------------------------------------

def test_manual_end_session_computes_cost(client_as_admin, mock_supabase):
    entered = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    session_row = {
        "id": _SESSION_ID,
        "user_id": DRIVER_ID,
        "parking_id": _PARKING_ID,
        "spot_number": _SPOT_NUMBER,
        "status": "active",
        "entered_at": entered,
        "cost": 0,
    }
    parking_row = {"id": _PARKING_ID, "name": "Test", "price_per_hour": 100, "free_minutes": 60}
    results = iter([
        MagicMock(data=[session_row], count=1),   # sessions select
        MagicMock(data=[parking_row], count=1),   # parkings select
        MagicMock(data=[], count=0),              # sessions update
        MagicMock(data=[], count=0),              # spots update
    ])
    mock_supabase.execute.side_effect = lambda: next(results)

    resp = client_as_admin.post(
        "/api/admin/sessions/manual-end",
        json={"sessionId": _SESSION_ID},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    # 2h session - 1h free = 1h billable @ 100/h = 100 сом
    assert body["cost"] == pytest.approx(100.0, abs=1.0)


# ---------------------------------------------------------------------------
# Active session endpoint
# ---------------------------------------------------------------------------

def test_active_session_none(client_as_driver, mock_supabase):
    mock_supabase.execute.return_value = MagicMock(data=[], count=0)

    resp = client_as_driver.get(
        "/api/sessions/active", headers={"Authorization": "Bearer fake"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["session"] is None
    assert body["parking"] is None
