"""
QR flow tests:
  generate → validate (entry) → generate → validate (exit) →
  generate → validate same token again → 400 already_used
"""

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, call

import pytest
from jose import jwt

from tests.conftest import DRIVER_USER, ADMIN_USER, DRIVER_ID, PLATE

_SECRET = "test-jwt-secret-for-unit-tests-only"
_ALGO = "HS256"
_PARKING_ID = "parking-1"
_NONCE_ID = str(uuid.uuid4())


def _build_token(nonce_id: str = _NONCE_ID, user_id: str = DRIVER_ID):
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": user_id,
            "plt": PLATE,
            "kid": nonce_id,
            "exp": int((now + timedelta(minutes=15)).timestamp()),
            "iat": int(now.timestamp()),
            "iss": "onoipark-api",
        },
        _SECRET,
        algorithm=_ALGO,
    )


# ---------------------------------------------------------------------------
# Generate
# ---------------------------------------------------------------------------

def test_generate_returns_token(client_as_driver, mock_supabase):
    mock_supabase.execute.return_value = MagicMock(data=[{"id": _NONCE_ID}], count=1)

    resp = client_as_driver.get(
        "/api/qr/generate", headers={"Authorization": "Bearer fake"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "token" in body
    assert "expiresAt" in body

    # Verify the token is a valid JWT
    payload = jwt.decode(body["token"], _SECRET, algorithms=[_ALGO])
    assert payload["sub"] == DRIVER_ID
    assert payload["iss"] == "onoipark-api"


# ---------------------------------------------------------------------------
# Validate — entry path (no existing session, parking_id provided)
# ---------------------------------------------------------------------------

def test_validate_entry_no_session(client_as_admin, mock_supabase):
    token = _build_token()

    # nonce lookup → unused
    nonce_row = {"id": _NONCE_ID, "used": False, "user_id": DRIVER_ID}

    def _execute_side_effect():
        return MagicMock(data=[], count=0)

    # Configure mock to return nonce on first non-empty result
    results = iter(
        [
            MagicMock(data=[nonce_row], count=1),  # qr_nonces select
            MagicMock(data=[], count=0),           # nonce update (ignored return)
            MagicMock(data=[], count=0),           # waiting sessions
            MagicMock(data=[], count=0),           # active sessions
            MagicMock(data=[], count=0),           # bookings
            MagicMock(data=[{"id": str(uuid.uuid4())}], count=1),  # session insert
            MagicMock(data=[], count=0),           # spot update
        ]
    )
    mock_supabase.execute.side_effect = lambda: next(results)

    resp = client_as_admin.post(
        "/api/qr/validate",
        json={"token": token, "parkingId": _PARKING_ID, "spotNumber": 5},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["action"] == "entry"


# ---------------------------------------------------------------------------
# Validate — already_used
# ---------------------------------------------------------------------------

def test_validate_already_used_returns_400(client_as_admin, mock_supabase):
    token = _build_token()
    nonce_row = {"id": _NONCE_ID, "used": True, "user_id": DRIVER_ID}

    mock_supabase.execute.return_value = MagicMock(data=[nonce_row], count=1)

    resp = client_as_admin.post(
        "/api/qr/validate",
        json={"token": token, "parkingId": _PARKING_ID},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "already_used"


# ---------------------------------------------------------------------------
# Validate — expired token
# ---------------------------------------------------------------------------

def test_validate_expired_token_returns_400(client_as_admin, mock_supabase):
    now = datetime.now(timezone.utc)
    expired_token = jwt.encode(
        {
            "sub": DRIVER_ID,
            "plt": PLATE,
            "kid": _NONCE_ID,
            "exp": int((now - timedelta(minutes=1)).timestamp()),
            "iat": int((now - timedelta(minutes=16)).timestamp()),
            "iss": "onoipark-api",
        },
        _SECRET,
        algorithm=_ALGO,
    )

    resp = client_as_admin.post(
        "/api/qr/validate",
        json={"token": expired_token, "parkingId": _PARKING_ID},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "expired"


# ---------------------------------------------------------------------------
# Validate — exit path (active session found)
# ---------------------------------------------------------------------------

def test_validate_exit_active_session(client_as_admin, mock_supabase):
    token = _build_token()
    session_id = str(uuid.uuid4())
    nonce_row = {"id": _NONCE_ID, "used": False, "user_id": DRIVER_ID}
    active_session = {
        "id": session_id,
        "user_id": DRIVER_ID,
        "parking_id": _PARKING_ID,
        "spot_number": 3,
        "status": "active",
        "entered_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
    }
    parking_row = {"price_per_hour": 100, "free_minutes": 60}

    results = iter(
        [
            MagicMock(data=[nonce_row], count=1),          # nonce select
            MagicMock(data=[], count=0),                    # nonce update
            MagicMock(data=[], count=0),                    # waiting sessions
            MagicMock(data=[active_session], count=1),      # active sessions
            MagicMock(data=[parking_row], count=1),         # parkings select for cost
            MagicMock(data=[], count=0),                    # session update (exiting)
            MagicMock(data=[], count=0),                    # spot update
        ]
    )
    mock_supabase.execute.side_effect = lambda: next(results)

    resp = client_as_admin.post(
        "/api/qr/validate",
        json={"token": token, "parkingId": _PARKING_ID, "spotNumber": 3},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["action"] == "exit"
    assert "cost" in body
