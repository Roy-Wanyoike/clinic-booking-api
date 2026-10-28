"""Doctor endpoints: listing and derived availability."""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.exceptions import NotFoundError
from app.models import Doctor
from app.schemas import AvailabilityOut, AvailabilitySlot, DoctorOut
from app.services import booking

router = APIRouter(prefix="/doctors", tags=["doctors"])


def _get_doctor_or_404(db: Session, doctor_id: int) -> Doctor:
    doctor = db.get(Doctor, doctor_id)
    if doctor is None:
        raise NotFoundError(f"doctor with id {doctor_id} does not exist")
    return doctor


@router.get("", response_model=list[DoctorOut])
def list_doctors(db: Session = Depends(get_db)):
    """All doctors with their working hours and slot length."""
    return booking.list_doctors(db)


@router.get("/{doctor_id}", response_model=DoctorOut)
def get_doctor(doctor_id: int, db: Session = Depends(get_db)):
    return _get_doctor_or_404(db, doctor_id)


@router.get("/{doctor_id}/availability", response_model=AvailabilityOut)
def get_availability(
    doctor_id: int,
    date: date = Query(..., description="Clinic-local date to inspect, YYYY-MM-DD"),
    db: Session = Depends(get_db),
):
    """All free 30-minute slots for a doctor on a given date.

    Slots that are booked, in the past, or inside the 60-minute booking
    lead-time window are excluded.
    """
    doctor = _get_doctor_or_404(db, doctor_id)
    slots = booking.get_availability(db, doctor, date)
    return AvailabilityOut(
        doctor_id=doctor.id,
        date=date,
        slot_minutes=doctor.slot_minutes,
        available_slots=[
            AvailabilitySlot(start_time=start, end_time=end) for start, end in slots
        ],
        count=len(slots),
    )
