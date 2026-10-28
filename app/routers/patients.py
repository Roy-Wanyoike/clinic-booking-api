"""Patient endpoints: registration and their appointments (bonus)."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import (
    AppointmentListOut,
    PatientCreate,
    PatientOut,
    StatusFilter,
)
from app.services import booking

router = APIRouter(prefix="/patients", tags=["patients"])


@router.post("", response_model=PatientOut, status_code=201)
def create_patient(payload: PatientCreate, db: Session = Depends(get_db)):
    """Register a patient. Email must be unique."""
    return booking.create_patient(db, payload.model_dump())


@router.get("/{patient_id}/appointments", response_model=AppointmentListOut)
def list_patient_appointments(
    patient_id: int,
    status: StatusFilter = Query(
        "upcoming", description="upcoming (default) | cancelled | all"
    ),
    db: Session = Depends(get_db),
):
    """Bonus: a patient's appointments sorted by date (soonest first).

    ``upcoming`` returns active appointments from now onwards and excludes
    cancelled ones.
    """
    appointments = booking.list_patient_appointments(db, patient_id, status)
    return AppointmentListOut(
        patient_id=patient_id,
        status_filter=status,
        count=len(appointments),
        appointments=appointments,
    )
