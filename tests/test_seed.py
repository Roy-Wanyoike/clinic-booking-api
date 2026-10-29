"""Demo seed lifecycle: installation, idempotency, junk reset, stale refresh.

These tests exercise app/seed.py directly (the lifespan does not run under
TestClient — the `db` fixture owns schema creation and doctor seeding, which
matches how the test suite isolates itself).
"""

import logging
from datetime import timedelta

from sqlalchemy import select

from app.models import Appointment, AppointmentStatus, Doctor, Patient
from app.seed import DEMO_PATIENTS, MARKER_EMAIL, seed_demo_data
from app.services.slots import clinic_now, is_slot_aligned

logging.getLogger("clinic.seed").setLevel(logging.CRITICAL)

DEMO_EMAILS = {p["email"] for p in DEMO_PATIENTS}


def _appointments(db) -> list[Appointment]:
    return list(db.scalars(select(Appointment)).all())


def test_seed_installs_demo_dataset(db):
    seed_demo_data(db)

    patients = db.scalars(select(Patient)).all()
    assert {p.email for p in patients} == DEMO_EMAILS
    assert sorted(p.id for p in patients) == [1, 2, 3, 4]  # deterministic ids

    booked = [a for a in _appointments(db) if a.status == "booked"]
    cancelled = [a for a in _appointments(db) if a.status == "cancelled"]
    assert len(booked) == 5
    assert len(cancelled) == 1

    now = clinic_now()
    assert all(a.start_time >= now for a in booked)  # all upcoming
    assert all(a.start_time < now for a in cancelled)  # history row

    # every demo booking sits on the doctor's grid inside working hours
    for a in booked:
        doctor = db.get(Doctor, a.doctor_id)
        assert is_slot_aligned(a.start_time, doctor.slot_minutes)
        assert doctor.working_start <= a.start_time.time()
        assert a.end_time.time() <= doctor.working_end

    # audit trail on the cancelled row
    cancelled_row = cancelled[0]
    assert cancelled_row.cancel_reason  # non-empty reason
    assert cancelled_row.cancelled_at is not None


def test_seed_is_idempotent(db):
    seed_demo_data(db)
    first_patients = {p.email for p in db.scalars(select(Patient)).all()}
    first_appointments = sorted(
        (a.doctor_id, a.patient_id, a.start_time) for a in _appointments(db)
    )

    seed_demo_data(db)  # second boot: marker exists, nothing stale

    second_patients = {p.email for p in db.scalars(select(Patient)).all()}
    second_appointments = sorted(
        (a.doctor_id, a.patient_id, a.start_time) for a in _appointments(db)
    )
    assert first_patients == second_patients == DEMO_EMAILS
    assert first_appointments == second_appointments
    assert len(second_appointments) == 6  # 5 booked + 1 cancelled


def test_seed_resets_leftover_manual_test_data(db):
    """A dirty database (e.g. leftover curl experiments) is wiped so reviewers
    land on the deterministic demo dataset instead of junk rows."""
    junk = Patient(name="Leftover Test", email="leftover@example.com")
    db.add(junk)
    db.flush()
    now = clinic_now()
    db.add(Appointment(
        doctor_id=1,
        patient_id=junk.id,
        start_time=now + timedelta(days=3),
        end_time=now + timedelta(days=3, minutes=30),
        status=AppointmentStatus.BOOKED.value,
    ))
    db.commit()

    seed_demo_data(db)

    emails = {p.email for p in db.scalars(select(Patient)).all()}
    assert "leftover@example.com" not in emails
    assert emails == DEMO_EMAILS
    for a in _appointments(db):
        assert a.patient_id in (1, 2, 3, 4)  # junk appointment gone


def test_seed_refreshes_stale_demo_bookings(db, monkeypatch):
    """After time passes, the demo bookings are regenerated in the future so
    the 'upcoming' view never goes empty for reviewers."""
    seed_demo_data(db)

    month_later = clinic_now() + timedelta(days=30)
    monkeypatch.setattr("app.seed.clinic_now", lambda: month_later)
    seed_demo_data(db)

    booked = [
        a for a in _appointments(db)
        if a.status == AppointmentStatus.BOOKED.value
    ]
    assert len(booked) == 5
    assert all(a.start_time >= month_later for a in booked)

    # the cancelled history row is intentionally preserved (audit demo)
    cancelled = [
        a for a in _appointments(db)
        if a.status == AppointmentStatus.CANCELLED.value
    ]
    assert len(cancelled) == 1


def test_refresh_keeps_future_bookings_made_by_reviewers(db, monkeypatch):
    """If a reviewer booked a demo patient into a future slot, the refresh
    must not touch anything — it only regenerates when *every* demo booking
    is already in the past."""
    seed_demo_data(db)
    aisha = db.scalar(select(Patient).where(Patient.email == MARKER_EMAIL))

    month_later = clinic_now() + timedelta(days=30)
    monkeypatch.setattr("app.seed.clinic_now", lambda: month_later)

    # a reviewer re-books Aisha one day after the (frozen) clock — i.e. a
    # demo-patient row that is still upcoming when the refresh runs
    reviewer_slot = month_later + timedelta(days=1)
    db.add(Appointment(
        doctor_id=1,
        patient_id=aisha.id,
        start_time=reviewer_slot,
        end_time=reviewer_slot + timedelta(minutes=30),
        status=AppointmentStatus.BOOKED.value,
    ))
    db.commit()

    seed_demo_data(db)  # refresh sees Aisha's future booking -> early return

    aisha_booked = db.scalars(select(Appointment).where(
        Appointment.patient_id == aisha.id,
        Appointment.status == AppointmentStatus.BOOKED.value,
    )).all()
    starts = {a.start_time for a in aisha_booked}
    assert reviewer_slot in starts  # reviewer's booking survived
    assert len(aisha_booked) == 3  # 2 original demo bookings + 1 (untouched)


def test_demo_data_visible_through_the_api(db, client):
    """What a reviewer actually sees: a patient's upcoming list is populated
    and the taken slot disappears from the doctor's availability grid."""
    seed_demo_data(db)

    aisha = db.scalar(select(Patient).where(Patient.email == MARKER_EMAIL))
    resp = client.get(f"/patients/{aisha.id}/appointments?status=upcoming")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2  # Aisha holds two demo bookings
    assert all(
        appt["doctor"]["name"] in {"Dr. Brian Kimani", "Dr. David Otieno"}
        for appt in body["appointments"]
    )

    # Brian's first morning slot tomorrow is taken by a demo booking
    brian = db.scalar(select(Doctor).where(Doctor.name == "Dr. Brian Kimani"))
    day = (clinic_now() + timedelta(days=1)).date().isoformat()
    resp = client.get(f"/doctors/{brian.id}/availability?date={day}")
    assert resp.status_code == 200
    starts = [slot["start_time"] for slot in resp.json()["available_slots"]]
    assert starts, "availability grid should still list free slots"
    assert not any(s.endswith("T09:00:00") for s in starts)

    # ...and the same slot is bookable-free again after cancellation
    appt_id = body["appointments"][0]["id"]
    resp = client.patch(
        f"/appointments/{appt_id}/cancel",
        json={"reason": "Reviewer testing cancellation"},
    )
    assert resp.status_code == 200
    resp = client.get(f"/doctors/{brian.id}/availability?date={day}")
    starts = [slot["start_time"] for slot in resp.json()["available_slots"]]
    assert any(s.endswith("T09:00:00") for s in starts)
