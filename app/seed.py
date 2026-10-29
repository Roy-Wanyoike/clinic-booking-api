"""Seed data: the clinic's 5 doctors plus a demo dataset for reviewers.

Startup seeding is idempotent and runs from ``app.main.lifespan``:

1. The 5 clinic doctors are inserted when the doctors table is empty.
2. The demo dataset (4 patients + upcoming booked appointments + one
   soft-cancelled history row) is installed when the marker patient
   (``aisha.mwikali@example.com``) is missing — i.e. on a fresh database or
   when only ad-hoc manual test data exists. This path deliberately RESETS
   patients/appointments so reviewers always land on a clean, deterministic
   dataset (patients get ids 1-4).
3. On later boots, if every demo booking has drifted into the past, they are
   regenerated for the following days — the live API always shows *upcoming*
   appointments no matter when a reviewer opens it.

Demo data can be disabled with ``SEED_DEMO_DATA=0`` (doctor seeding still
runs). Rows created by real users are never touched by the refresh logic.
"""

import logging
import os
from datetime import datetime, time, timedelta

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.models import Appointment, AppointmentStatus, Doctor, Patient
from app.services.slots import build_slot_grid, clinic_now

logger = logging.getLogger("clinic.seed")

SEED_DOCTORS = [
    {"name": "Dr. Amina Okoth",   "specialty": "General Medicine", "working_start": time(8, 0),  "working_end": time(16, 0)},
    {"name": "Dr. Brian Kimani",  "specialty": "Paediatrics",      "working_start": time(9, 0),  "working_end": time(17, 0)},
    {"name": "Dr. Grace Wanjiru", "specialty": "Dermatology",      "working_start": time(10, 0), "working_end": time(18, 0)},
    {"name": "Dr. David Otieno",  "specialty": "Cardiology",       "working_start": time(9, 0),  "working_end": time(13, 0)},
    {"name": "Dr. Fatuma Ali",    "specialty": "General Medicine", "working_start": time(14, 0), "working_end": time(20, 0)},
]

# Demo patients (Kenyan names, example.com emails). The first email doubles
# as the marker that decides whether the demo dataset needs installing.
DEMO_PATIENTS = [
    {"name": "Aisha Mwikali", "email": "aisha.mwikali@example.com", "phone": "+254712345678"},
    {"name": "Peter Njoroge", "email": "peter.njoroge@example.com", "phone": "+254723456789"},
    {"name": "Mercy Achieng", "email": "mercy.achieng@example.com", "phone": "+254734567890"},
    {"name": "Daniel Kiptoo", "email": "daniel.kiptoo@example.com", "phone": None},
]

MARKER_EMAIL = DEMO_PATIENTS[0]["email"]

# (doctor name, demo patient email, days from today, hour, minute) — every
# entry sits on the doctor's 30-minute grid inside their working hours.
# Offsets 1 and 2 keep each booking in the bookable future (well past the
# 60-minute lead window) no matter when the service boots.
DEMO_BOOKINGS: list[tuple[str, str, int, int, int]] = [
    ("Dr. Brian Kimani",  "aisha.mwikali@example.com", 1, 9,  0),
    ("Dr. Amina Okoth",   "peter.njoroge@example.com", 1, 10, 30),
    ("Dr. Fatuma Ali",    "mercy.achieng@example.com", 1, 14, 0),
    ("Dr. Grace Wanjiru", "daniel.kiptoo@example.com", 2, 11, 0),
    ("Dr. David Otieno",  "aisha.mwikali@example.com", 2, 9,  30),
]

# A soft-cancelled historical booking: shows reviewers the audit trail
# (status + cancel_reason + cancelled_at) without occupying a live slot.
DEMO_CANCELLATION = (
    "Dr. Amina Okoth",
    "peter.njoroge@example.com",
    "Patient called to reschedule — will rebook next week.",
)


def seed_doctors(db: Session) -> int:
    """Insert the clinic's doctors if (and only if) the table is empty.

    Returns the number of doctors added.
    """
    existing = db.scalar(select(func.count()).select_from(Doctor)) or 0
    if existing > 0:
        return 0

    db.add_all([Doctor(**doctor, slot_minutes=30) for doctor in SEED_DOCTORS])
    db.commit()
    return len(SEED_DOCTORS)


def seed_demo_data(db: Session) -> None:
    """Seed doctors + the reviewer demo dataset (idempotent).

    Called once at application startup; safe to call repeatedly.
    """
    added = seed_doctors(db)
    if added:
        logger.info("seeded %d clinic doctors", added)

    if os.getenv("SEED_DEMO_DATA", "").strip().lower() in {"0", "false", "no"}:
        logger.info("SEED_DEMO_DATA disabled — skipping demo dataset")
        return

    now = clinic_now()
    marker = db.scalar(select(Patient).where(Patient.email == MARKER_EMAIL))
    if marker is None:
        _reset_and_seed_demo(db, now)
    else:
        _refresh_stale_bookings(db, now)


# --------------------------------------------------------------------------
# internals
# --------------------------------------------------------------------------

def _reset_and_seed_demo(db: Session, now: datetime) -> None:
    """Install the demo dataset from a clean slate.

    Wipes any pre-existing patients/appointments (leftover manual test rows)
    so the demo starts deterministic: patients get ids 1-4 and the bookings
    below never clash with stale data.
    """
    db.execute(delete(Appointment))
    db.execute(delete(Patient))
    if db.bind.dialect.name == "postgresql":
        # DELETE does not rewind identity sequences on PostgreSQL, and the
        # README points reviewers at /patients/1/appointments, so restart
        # them. SQLite (tests) reuses rowids automatically.
        db.execute(text("ALTER SEQUENCE patients_id_seq RESTART WITH 1"))
        db.execute(text("ALTER SEQUENCE appointments_id_seq RESTART WITH 1"))
    db.flush()

    db.add_all([Patient(**data) for data in DEMO_PATIENTS])
    db.flush()  # assign patient ids before booking
    patients = {p.email: p for p in db.scalars(select(Patient)).all()}
    doctors = {d.name: d for d in db.scalars(select(Doctor)).all()}

    for doctor_name, patient_email, day_offset, hour, minute in DEMO_BOOKINGS:
        doctor, patient = doctors[doctor_name], patients[patient_email]
        day = (now + timedelta(days=day_offset)).date()
        slot = _free_slot(db, doctor, day, time(hour, minute))
        if slot is None:  # pragma: no cover — day fully booked is unrealistic
            logger.warning("no free demo slot for %s on %s", doctor_name, day)
            continue
        start, end = slot
        db.add(Appointment(
            doctor_id=doctor.id,
            patient_id=patient.id,
            start_time=start,
            end_time=end,
            status=AppointmentStatus.BOOKED.value,
        ))

    # Historical soft-cancelled appointment (the audit-trail demo row).
    cancel_doctor, cancel_email, reason = DEMO_CANCELLATION
    doctor, patient = doctors[cancel_doctor], patients[cancel_email]
    yesterday = (now - timedelta(days=1)).date()
    db.add(Appointment(
        doctor_id=doctor.id,
        patient_id=patient.id,
        start_time=datetime.combine(yesterday, time(10, 0)),
        end_time=datetime.combine(yesterday, time(10, 30)),
        status=AppointmentStatus.CANCELLED.value,
        cancel_reason=reason,
        cancelled_at=datetime.combine(yesterday, time(8, 31)),
        created_at=now - timedelta(days=2),
    ))

    db.commit()
    logger.info(
        "seeded demo dataset: %d patients, %d bookings + 1 cancelled",
        len(DEMO_PATIENTS), len(DEMO_BOOKINGS),
    )


def _refresh_stale_bookings(db: Session, now: datetime) -> None:
    """Regenerate demo bookings once they have all drifted into the past.

    Only rows owned by the demo patients are touched, and only when *none* of
    them lies in the future — if a reviewer re-booked a demo patient into a
    future slot, that booking is preserved as-is.
    """
    demo_ids = list(db.scalars(
        select(Patient.id).where(
            Patient.email.in_([p["email"] for p in DEMO_PATIENTS])
        )
    ))
    if not demo_ids:
        return

    booked = list(db.scalars(select(Appointment).where(
        Appointment.patient_id.in_(demo_ids),
        Appointment.status == AppointmentStatus.BOOKED.value,
    )))
    if any(a.start_time >= now for a in booked):
        return  # at least one demo booking is still upcoming — nothing to do

    for appointment in booked:
        db.delete(appointment)
    db.flush()

    patients = {p.email: p for p in db.scalars(select(Patient)).all()}
    doctors = {d.name: d for d in db.scalars(select(Doctor)).all()}
    planned = 0
    for doctor_name, patient_email, day_offset, hour, minute in DEMO_BOOKINGS:
        doctor, patient = doctors[doctor_name], patients[patient_email]
        day = (now + timedelta(days=day_offset)).date()
        slot = _free_slot(db, doctor, day, time(hour, minute))
        if slot is None:  # pragma: no cover
            continue
        start, end = slot
        db.add(Appointment(
            doctor_id=doctor.id,
            patient_id=patient.id,
            start_time=start,
            end_time=end,
            status=AppointmentStatus.BOOKED.value,
        ))
        planned += 1

    db.commit()
    if planned:
        logger.info("refreshed %d stale demo bookings to upcoming dates", planned)


def _free_slot(
    db: Session, doctor: Doctor, day, preferred: time
) -> tuple[datetime, datetime] | None:
    """First free grid slot on ``day`` starting at/after ``preferred``.

    Walks forward on the doctor's slot grid; if the whole day is taken it
    tries the following days (up to a week), so demo data never collides with
    a booking made by a real user.
    """
    for _ in range(7):
        day_start = datetime.combine(day, time.min)
        day_end = day_start + timedelta(days=1)
        booked = list(db.scalars(select(Appointment).where(
            Appointment.doctor_id == doctor.id,
            Appointment.status == AppointmentStatus.BOOKED.value,
            Appointment.start_time < day_end,
            Appointment.end_time > day_start,
        )))
        for start, end in build_slot_grid(
            doctor.working_start, doctor.working_end, day, doctor.slot_minutes
        ):
            if start.time() < preferred:
                continue
            if not any(b.start_time < end and b.end_time > start for b in booked):
                return start, end
        day += timedelta(days=1)
        preferred = doctor.working_start
    return None
