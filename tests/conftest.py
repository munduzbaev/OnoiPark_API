"""
Test fixtures.

The Supabase client and auth deps are mocked so tests run without a live
Supabase project.  Set SUPABASE_SERVICE_ROLE_KEY and SUPABASE_ANON_KEY to
dummy values via env or a .env.test file — pydantic-settings loads them.
"""

import os
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# --- Provide dummy env vars before the app is imported ---
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-key")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-unit-tests-only")

from app.main import app  # noqa: E402  (must come after env setup)
from app.deps import current_user, current_admin  # noqa: E402

# ---------------------------------------------------------------------------
# Shared fake identities
# ---------------------------------------------------------------------------

DRIVER_ID = str(uuid.uuid4())
ADMIN_ID = str(uuid.uuid4())
PLATE = "A1234BC"

DRIVER_USER = {
    "id": DRIVER_ID,
    "email": f"{PLATE}@onoipark.app",
    "user_metadata": {"plateNumber": PLATE, "phoneNumber": "0700000001", "name": "Test Driver"},
    "role": "driver",
}

ADMIN_USER = {
    "id": ADMIN_ID,
    "email": "admin@onoipark.app",
    "user_metadata": {"plateNumber": "ADMIN001", "phoneNumber": "0700000000", "name": "Admin"},
    "role": "admin",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    """TestClient with dependency overrides reset after each test."""
    app.dependency_overrides = {}
    with TestClient(app) as c:
        yield c
    app.dependency_overrides = {}


@pytest.fixture
def driver_token():
    return "driver-bearer-token"


@pytest.fixture
def admin_token():
    return "admin-bearer-token"


@pytest.fixture
def client_as_driver(driver_token):
    """TestClient where current_user resolves to DRIVER_USER."""
    app.dependency_overrides[current_user] = lambda: DRIVER_USER
    with TestClient(app) as c:
        yield c
    app.dependency_overrides = {}


@pytest.fixture
def client_as_admin(admin_token):
    """TestClient where both current_user and current_admin resolve to ADMIN_USER."""
    app.dependency_overrides[current_user] = lambda: ADMIN_USER
    app.dependency_overrides[current_admin] = lambda: ADMIN_USER
    with TestClient(app) as c:
        yield c
    app.dependency_overrides = {}


@pytest.fixture(autouse=True)
def mock_supabase():
    """
    Replace the supabase singleton with a MagicMock for every test.
    Tests that need specific return values can configure mock_supabase further.
    """
    mock = MagicMock()
    # Make chained calls return mock by default so attribute access doesn't break
    mock.table.return_value = mock
    mock.select.return_value = mock
    mock.insert.return_value = mock
    mock.update.return_value = mock
    mock.delete.return_value = mock
    mock.upsert.return_value = mock
    mock.eq.return_value = mock
    mock.in_.return_value = mock
    mock.gte.return_value = mock
    mock.lte.return_value = mock
    mock.order.return_value = mock
    mock.limit.return_value = mock
    mock.range.return_value = mock
    mock.execute.return_value = MagicMock(data=[], count=0)

    with patch("app.supabase_client.supabase", mock), \
         patch("app.routers.auth.supabase", mock), \
         patch("app.routers.parkings.supabase", mock), \
         patch("app.routers.sessions.supabase", mock), \
         patch("app.routers.bookings.supabase", mock), \
         patch("app.routers.qr.supabase", mock), \
         patch("app.routers.admin.supabase", mock), \
         patch("app.main.supabase", mock):
        yield mock
