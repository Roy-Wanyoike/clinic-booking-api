"""Pydantic request/response schemas."""

from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


def _reject_timezone_offset(field: str, value: datetime) -> datetime:
    """All times are clinic-local (Africa/Nairobi) wall-clock times.

    A timezone-aware value is ambiguous (whose timezone?), so we reject it
    with an actionable message instead of silently converting.
    """
    if value.tzinfo is not None:
        raise ValueError(
            f"{field} must be clinic-local wall-clock time WITHOUT a timezone "
            "offset, e.g. 2026-11-05T09:00:00 (the clinic operates in Africa/Nairobi)"
        )
    return value


class DoctorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    specialty: str
    working_start: time
    working_end: time
    slot_minutes: int


class PatientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=32)


class PatientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    phone: str | None
    created_at: datetime


class AppointmentCreate(BaseModel):
    doctor_id: int
    patient_id: int
    start_time: datetime

    @field_validator("start_time")
    @classmethod
    def clinic_local_start(cls, value: datetime) -> datetime:
        return _reject_timezone_offset("start_time", value)


class AppointmentReschedule(BaseModel):
    start_time: datetime

    @field_validator("start_time")
    @classmethod
    def clinic_local_start(cls, value: datetime) -> datetime:
        return _reject_timezone_offset("start_time", value)


class AppointmentCancel(BaseModel):
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("reason must not be blank")
        return value


class AppointmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    doctor_id: int
    patient_id: int
    start_time: datetime
    end_time: datetime
    status: str
    cancel_reason: str | None
    cancelled_at: datetime | None
    created_at: datetime


class AppointmentWithDoctorOut(BaseModel):
    """Patient-facing appointment view with doctor details embedded."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    start_time: datetime
    end_time: datetime
    status: str
    cancel_reason: str | None
    doctor: DoctorOut


class AvailabilitySlot(BaseModel):
    start_time: datetime
    end_time: datetime


class AvailabilityOut(BaseModel):
    doctor_id: int
    date: date
    slot_minutes: int
    available_slots: list[AvailabilitySlot]
    count: int


class AppointmentListOut(BaseModel):
    patient_id: int
    status_filter: str
    count: int
    appointments: list[AppointmentWithDoctorOut]


StatusFilter = Literal["upcoming", "cancelled", "all"]
