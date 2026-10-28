"""Appointment endpoints: book, cancel, reschedule (the brief's core)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import (
    AppointmentCancel,
    AppointmentCreate,
    AppointmentOut,
    AppointmentReschedule,
)
from app.services import booking

router = APIRouter(prefix="/appointments", tags=["appointments"])


@router.post("", response_model=AppointmentOut, status_code=201)
def book_appointment(payload: AppointmentCreate, db: Session = Depends(get_db)):
    """Book a 30-minute slot.

    Validates that the slot:
      * falls inside the doctor's working hours (404 if the doctor doesn't exist),
      * is aligned to the doctor's slot grid,
      * is not in the past and starts at least 60 minutes from now,
      * is not already taken (409).
    """
    return booking.book_appointment(db, **payload.model_dump())


@router.patch("/{appointment_id}/cancel", response_model=AppointmentOut)
def cancel_appointment(
    appointment_id: int, payload: AppointmentCancel, db: Session = Depends(get_db)
):
    """Cancel an appointment with a reason. The slot becomes bookable again.

    Returns 409 if the appointment was already cancelled.
    """
    return booking.cancel_appointment(db, appointment_id, payload.reason)


@router.patch("/{appointment_id}/reschedule", response_model=AppointmentOut)
def reschedule_appointment(
    appointment_id: int, payload: AppointmentReschedule, db: Session = Depends(get_db)
):
    """Move an appointment to a new slot with the same doctor.

    The new slot is validated exactly like a fresh booking; the original slot
    is released automatically. Returns 409 if the appointment is cancelled or
    the target slot is taken.
    """
    return booking.reschedule_appointment(db, appointment_id, payload.start_time)
