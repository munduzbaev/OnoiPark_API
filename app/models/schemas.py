"""
Pydantic models that mirror the TypeScript types from OnoiPark_Dashboard.

JSON responses use camelCase to match what the existing clients expect,
while Python code uses snake_case internally.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


# ---------------------------------------------------------------------------
# Base with camelCase alias
# ---------------------------------------------------------------------------

class CamelModel(BaseModel):
    """Base model that outputs camelCase JSON keys."""
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


# ---------------------------------------------------------------------------
# Response models (matching OnoiPark_Dashboard/src/app/lib/types.ts)
# ---------------------------------------------------------------------------

class Parking(CamelModel):
    id: str
    name: str
    address: str
    total_spots: int
    available_spots: int
    price_per_hour: int
    features: list[str] | None = None
    latitude: float | None = None
    longitude: float | None = None
    lat: float | None = None
    lng: float | None = None
    price: int | None = None


class Spot(CamelModel):
    id: str
    parking_id: str | None = None
    number: int
    status: Literal["available", "occupied", "booked"]
    plate_number: str | None = None
    user_id: str | None = None
    booked_by: str | None = None


class ActiveSession(CamelModel):
    id: str
    user_id: str | None = None
    plate_number: str
    driver_name: str | None = None
    parking_id: str
    parking_name: str
    spot_id: str | None = None
    spot_number: int | None = None
    start_time: str
    price_per_hour: int | None = None
    free_duration: int | None = None
    free_until: str | None = None
    status: str
    cost: int | None = None
    location: dict | None = None


class Booking(CamelModel):
    id: str
    user_id: str | None = None
    plate_number: str
    parking_id: str
    parking_name: str
    spot_number: int
    start_time: str
    end_time: str | None = None
    expires_at: str | None = None
    status: Literal["active", "cancelled", "completed"]


class HistoryEntry(CamelModel):
    id: str
    plate_number: str
    parking_name: str
    spot_number: int | None = None
    start_time: str
    end_time: str
    duration: float
    cost: float


class UserProfile(CamelModel):
    id: str
    plate_number: str
    phone_number: str
    name: str | None = None
    created_at: str | None = None
    payment_methods: list | None = None
    notification_settings: dict | None = None


class QRPayload(CamelModel):
    token: str
    expires_at: str | None = None


class QRData(CamelModel):
    """Matches QRData from the dashboard types.ts."""
    user_id: str
    plate_number: str
    name: str
    timestamp: str


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class SignupRequest(CamelModel):
    plate_number: str
    phone_number: str
    name: str


class SigninRequest(CamelModel):
    plate_number: str
    phone_number: str


class ResetPasswordRequest(CamelModel):
    plate_number: str
    old_phone_number: str
    new_phone_number: str


class CreateBookingRequest(CamelModel):
    parking_id: str
    spot_number: int


class StartSessionRequest(CamelModel):
    parking_id: str
    spot_number: int | None = None
    plate_number: str | None = None
    driver_name: str | None = None
    user_id: str | None = None
    qr_code: str | None = None
    location: dict | None = None


class EndSessionRequest(CamelModel):
    session_id: str | None = None


class ValidateQRRequest(CamelModel):
    token: str
    parking_id: str
    spot_number: int | None = None


class CancelBookingRequest(CamelModel):
    booking_id: str


class UpdateSettingsRequest(CamelModel):
    notification_settings: dict | None = None


class ManualStartRequest(CamelModel):
    plate_number: str
    parking_id: str
    spot_number: int | None = None


class ManualEndRequest(CamelModel):
    session_id: str


class GateScanRequest(CamelModel):
    gate_id: str
