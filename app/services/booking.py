"""Booking business rules.

All endpoint handlers are thin wrappers over these functions, so the rules
live in one testable place with no HTTP concepts (no status codes here —
services raise domain exceptions that app/main.py maps to HTTP responses).
"""

from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.exceptions import (
    BookingValidationError,
    DuplicateResourceError,
    InvalidStateError,
    NotFoundError,
    PatientSlotConflictError,
    SlotTakenError,
)
from app.models import Appointment, AppointmentStatus, Doctor, Patient
from app.services.slots import build_slot_grid, clinic_now, is_slot_aligned


# --------------------------------------------------------------------------
# lookups / simple resources
# --------------------------------------------------------------------------

def _get_or_404(db: Session, model, entity_id: int, label: str):
    obj = db.get(model, entity_id)
    if obj is None:
        raise NotFoundError(f"{label} with id {entity_id} does not exist")
    return obj


def list_doctors(db: Session) -> list[Doctor]:
    return list(db.scalars(select(Doctor).order_by(Doctor.id)).all())


def create_patient(db: Session, data: dict) -> Patient:
    patient = Patient(**data)
    db.add(patient)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DuplicateResourceError(
            f"a patient with email '{data.get('email')}' is already registered"
        )
    db.refresh(patient)
    return patient


# --------------------------------------------------------------------------
# availability
# --------------------------------------------------------------------------

def get_availability(
    db: Session, doctor: Doctor, day: date
) -> list[tuple[datetime, datetime]]:
    """Free, *bookable* slots for one doctor on one date.

    A slot is listed only if it:
      * lies on the doctor's slot grid inside working hours,
      * has no active (booked) appointment overlapping it,
      * starts at least ``min_lead_minutes`` in the future (bonus rule) —
        slots that cannot actually be booked are hidden rather than shown.
    """
    now = clinic_now()
    if day < now.date():
        raise BookingValidationError(
            f"cannot check availability for a past date ({day.isoformat()})"
        )

    grid = build_slot_grid(
        doctor.working_start, doctor.working_end, day, doctor.slot_minutes
    )

    day_start = datetime.combine(day, time.min)
    day_end = day_start + timedelta(days=1)
    booked = list(
        db.scalars(
            select(Appointment).where(
                Appointment.doctor_id == doctor.id,
                Appointment.status == AppointmentStatus.BOOKED.value,
                Appointment.start_time < day_end,
                Appointment.end_time > day_start,
            )
        ).all()
    )

    min_start = now + timedelta(minutes=settings.min_lead_minutes)
    free: list[tuple[datetime, datetime]] = []
    for start, end in grid:
        if start < min_start:
            continue  # in the past or inside the lead-time window
        if any(b.start_time < end and b.end_time > start for b in booked):
            continue  # already taken
        free.append((start, end))
    return free


# --------------------------------------------------------------------------
# shared slot validation (used by booking AND rescheduling)
# --------------------------------------------------------------------------

def _validate_slot(doctor: Doctor, start: datetime, end: datetime, now: datetime) -> None:
    """Structural validation shared by fresh bookings and reschedules.

    Raises BookingValidationError (-> HTTP 422) with a specific, actionable
    message for every rule from the brief.
    """
    slot_minutes = doctor.slot_minutes

    if not is_slot_aligned(start, slot_minutes):
        raise BookingValidationError(
            f"start_time must fall on a {slot_minutes}-minute slot boundary "
            f"(e.g. 09:00 or 09:30), got {start.strftime('%H:%M')}"
        )

    window_start = datetime.combine(start.date(), doctor.working_start)
    window_end = datetime.combine(start.date(), doctor.working_end)
    if start < window_start or end > window_end:
        raise BookingValidationError(
            f"slot {start.strftime('%H:%M')}-{end.strftime('%H:%M')} is outside "
            f"{doctor.name}'s working hours "
            f"({doctor.working_start.strftime('%H:%M')}-{doctor.working_end.strftime('%H:%M')})"
        )

    if start < now:
        raise BookingValidationError(
            f"start_time {start.isoformat()} is in the past; pick a future slot"
        )

    min_start = now + timedelta(minutes=settings.min_lead_minutes)
    if start < min_start:
        raise BookingValidationError(
            f"bookings must start at least {settings.min_lead_minutes} minutes "
            f"from now (earliest bookable start: {min_start.strftime('%Y-%m-%dT%H:%M')})"
        )


def _assert_no_overlap(
    db: Session,
    *,
    doctor_id: int | None,
    patient_id: int | None,
    exclude_id: int | None,
    start: datetime,
    end: datetime,
    who: str,
) -> None:
    """Friendly pre-check for overlapping ACTIVE appointments.

    This check makes the common case return a helpful 409; the partial unique
    index on (doctor_id, start_time) remains the authoritative guard against
    true concurrent races (see tests/test_concurrency.py).
    """
    stmt = select(Appointment).where(
        Appointment.status == AppointmentStatus.BOOKED.value,
        Appointment.start_time < end,
        Appointment.end_time > start,
    )
    if doctor_id is not None:
        stmt = stmt.where(Appointment.doctor_id == doctor_id)
    if patient_id is not None:
        stmt = stmt.where(Appointment.patient_id == patient_id)
    if exclude_id is not None:
        stmt = stmt.where(Appointment.id != exclude_id)

    clash = db.scalars(stmt).first()
    if clash is None:
        return

    if who == "doctor":
        raise SlotTakenError(
            f"doctor {doctor_id} is already booked from "
            f"{clash.start_time.isoformat()} to {clash.end_time.isoformat()}"
        )
    raise PatientSlotConflictError(
        f"patient {patient_id} already has an appointment from "
        f"{clash.start_time.isoformat()} to {clash.end_time.isoformat()}"
    )


# --------------------------------------------------------------------------
# booking / cancellation / rescheduling
# --------------------------------------------------------------------------

def book_appointment(
    db: Session, *, doctor_id: int, patient_id: int, start_time: datetime
) -> Appointment:
    doctor = _get_or_404(db, Doctor, doctor_id, "doctor")
    patient = _get_or_404(db, Patient, patient_id, "patient")

    now = clinic_now()
    end_time = start_time + timedelta(minutes=doctor.slot_minutes)

    # 1. structural validation -> 422 with a specific message
    _validate_slot(doctor, start_time, end_time, now)

    # 2. conflict checks -> 409 (doctor double-booked / patient double-booked)
    _assert_no_overlap(
        db, doctor_id=doctor.id, patient_id=None, exclude_id=None,
        start=start_time, end=end_time, who="doctor",
    )
    _assert_no_overlap(
        db, doctor_id=None, patient_id=patient.id, exclude_id=None,
        start=start_time, end=end_time, who="patient",
    )

    appointment = Appointment(
        doctor_id=doctor.id,
        patient_id=patient.id,
        start_time=start_time,
        end_time=end_time,
        status=AppointmentStatus.BOOKED.value,
    )
    db.add(appointment)
    try:
        db.commit()
    except IntegrityError:
        # Lost a race: another request booked the same slot between our
        # overlap check and this commit. The partial unique index caught it.
        db.rollback()
        raise SlotTakenError(
            f"slot {start_time.isoformat()} for doctor {doctor.id} was just taken"
        )
    db.refresh(appointment)
    return appointment


def cancel_appointment(db: Session, appointment_id: int, reason: str) -> Appointment:
    appointment = _get_or_404(db, Appointment, appointment_id, "appointment")

    if appointment.status == AppointmentStatus.CANCELLED.value:
        raise InvalidStateError(
            f"appointment {appointment_id} is already cancelled"
        )

    appointment.status = AppointmentStatus.CANCELLED.value
    appointment.cancel_reason = reason
    appointment.cancelled_at = clinic_now()
    db.commit()
    db.refresh(appointment)
    # No slot bookkeeping needed: the partial unique index only covers
    # status='booked', so the slot is automatically bookable again.
    return appointment


def reschedule_appointment(
    db: Session, appointment_id: int, new_start: datetime
) -> Appointment:
    appointment = _get_or_404(db, Appointment, appointment_id, "appointment")

    if appointment.status == AppointmentStatus.CANCELLED.value:
        raise InvalidStateError(
            f"appointment {appointment_id} is cancelled and cannot be "
            "rescheduled; book a new slot instead"
        )

    doctor = db.get(Doctor, appointment.doctor_id)
    new_end = new_start + timedelta(minutes=doctor.slot_minutes)
    now = clinic_now()

    if new_start == appointment.start_time:
        raise BookingValidationError(
            f"appointment already starts at {new_start.isoformat()}"
        )

    # Validated exactly like a fresh booking (brief requirement).
    _validate_slot(doctor, new_start, new_end, now)

    _assert_no_overlap(
        db, doctor_id=doctor.id, patient_id=None, exclude_id=appointment.id,
        start=new_start, end=new_end, who="doctor",
    )
    _assert_no_overlap(
        db, doctor_id=None, patient_id=appointment.patient_id, exclude_id=appointment.id,
        start=new_start, end=new_end, who="patient",
    )

    # Single UPDATE = atomic. If another active booking already occupies the
    # target slot (race), the unique index rejects the whole statement and
    # the original slot is left untouched.
    appointment.start_time = new_start
    appointment.end_time = new_end
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise SlotTakenError(
            f"slot {new_start.isoformat()} for doctor {doctor.id} was just taken"
        )
    db.refresh(appointment)
    return appointment


def list_patient_appointments(
    db: Session, patient_id: int, status_filter: str
) -> list[Appointment]:
    """Bonus endpoint backing query: upcoming (default), cancelled, or all,
    sorted by start time ascending."""
    _get_or_404(db, Patient, patient_id, "patient")

    stmt = (
        select(Appointment)
        .options(joinedload(Appointment.doctor))
        .where(Appointment.patient_id == patient_id)
        .order_by(Appointment.start_time.asc())
    )
    if status_filter == "upcoming":
        stmt = stmt.where(
            Appointment.status == AppointmentStatus.BOOKED.value,
            Appointment.start_time >= clinic_now(),
        )
    elif status_filter == "cancelled":
        stmt = stmt.where(Appointment.status == AppointmentStatus.CANCELLED.value)

    return list(db.scalars(stmt).all())
