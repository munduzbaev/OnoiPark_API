"""
Auth flow tests: signup → signin → me
"""

import uuid
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from tests.conftest import DRIVER_USER, PLATE


def _make_user(uid=None, plate=PLATE):
    uid = uid or str(uuid.uuid4())
    m = MagicMock()
    m.id = uid
    m.email = f"{plate}@onoipark.app"
    m.user_metadata = {"plateNumber": plate, "phoneNumber": "0700000001", "name": "Test"}
    return m


def _make_session(user):
    s = MagicMock()
    s.access_token = "fake-access-token"
    s.user = user
    r = MagicMock()
    r.session = s
    r.user = user
    return r


# ---------------------------------------------------------------------------
# Signup
# ---------------------------------------------------------------------------

def test_signup_success(client: TestClient, mock_supabase):
    user_obj = _make_user()
    mock_supabase.auth.admin.create_user.return_value = MagicMock(user=user_obj)
    # profiles.select returns empty (no duplicate)
    mock_supabase.execute.return_value = MagicMock(data=[], count=0)

    resp = client.post(
        "/api/auth/signup",
        json={"plateNumber": PLATE, "phoneNumber": "0700000001", "name": "Test"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["user"]["plateNumber"] == PLATE


def test_signup_duplicate_plate(client: TestClient, mock_supabase):
    # profiles.select returns an existing row
    mock_supabase.execute.return_value = MagicMock(data=[{"id": "existing-id"}], count=1)

    resp = client.post(
        "/api/auth/signup",
        json={"plateNumber": PLATE, "phoneNumber": "0700000001", "name": "Test"},
    )
    assert resp.status_code == 400
    assert "зарегистрирован" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Signin
# ---------------------------------------------------------------------------

def test_signin_success(client: TestClient, mock_supabase):
    user_obj = _make_user()
    session_resp = _make_session(user_obj)
    mock_supabase.auth.sign_in_with_password.return_value = session_resp
    # profiles.select → empty (no profile, will back-fill)
    mock_supabase.execute.return_value = MagicMock(data=[], count=0)

    resp = client.post(
        "/api/auth/signin",
        json={"plateNumber": PLATE, "phoneNumber": "0700000001"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert "access_token" in body


def test_signin_wrong_credentials(client: TestClient, mock_supabase):
    mock_supabase.auth.sign_in_with_password.side_effect = Exception("Invalid credentials")

    resp = client.post(
        "/api/auth/signin",
        json={"plateNumber": PLATE, "phoneNumber": "wrong"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# /me
# ---------------------------------------------------------------------------

def test_me_returns_profile(client_as_driver: TestClient, mock_supabase):
    mock_supabase.execute.return_value = MagicMock(
        data=[
            {
                "plate_number": PLATE,
                "phone_number": "0700000001",
                "name": "Test Driver",
                "notification_settings": {},
            }
        ],
        count=1,
    )

    resp = client_as_driver.get(
        "/api/auth/me", headers={"Authorization": "Bearer fake-token"}
    )
    assert resp.status_code == 200
    assert resp.json()["user"]["plateNumber"] == PLATE
