"""Concurrency: the partial unique index guarantees a single winner.

The friendly app-level overlap check handles the common case; these tests
prove the database constraint is the real authority when two requests race
for the same slot between the check and the commit.
"""

import threading
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.exceptions import SlotTakenError
from app.models import Appointment, AppointmentStatus
from app.services import booking


def test_concurrent_bookings_have_exactly_one_winner(db, patient, other_patient, slot):
    """Two patients race for the same slot: one books, one gets a conflict."""
    from datetime import datetime

    start = datetime.fromisoformat(slot(3, 9))
    barrier = threading.Barrier(2)
    results = []

    def worker(patient_id: int):
        session = SessionLocal()  # independent connection per "request"
        try:
            barrier.wait(timeout=10)
            booking.book_appointment(
                session, doctor_id=2, patient_id=patient_id, start_time=start
            )
            results.append("booked")
        except SlotTakenError:
            results.append("conflict")
        finally:
            session.close()

    threads = [
        threading.Thread(target=worker, args=(patient["id"],)),
        threading.Thread(target=worker, args=(other_patient["id"],)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert sorted(results) == ["booked", "conflict"], results

    # exactly one ACTIVE appointment persisted for that slot
    check = SessionLocal()
    try:
        active = list(
            check.scalars(
                select(Appointment).where(
                    Appointment.doctor_id == 2,
                    Appointment.start_time == start,
                    Appointment.status == AppointmentStatus.BOOKED.value,
                )
            ).all()
        )
        assert len(active) == 1
    finally:
        check.close()


def test_unique_index_blocks_duplicate_but_allows_rebook_after_cancel(
    db, patient, slot
):
    """Constraint-level proof: duplicate active booking rejected; after
    cancelling the first, the slot is bookable again."""
    from datetime import datetime

    start = datetime.fromisoformat(slot(3, 9))
    end = start + timedelta(minutes=30)

    first = Appointment(
        doctor_id=2,
        patient_id=patient["id"],
        start_time=start,
        end_time=end,
        status=AppointmentStatus.BOOKED.value,
    )
    db.add(first)
    db.commit()

    duplicate = Appointment(
        doctor_id=2,
        patient_id=patient["id"],
        start_time=start,
        end_time=end,
        status=AppointmentStatus.BOOKED.value,
    )
    db.add(duplicate)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    # cancel -> the partial index no longer covers the old row
    first.status = AppointmentStatus.CANCELLED.value
    db.commit()

    rebook = Appointment(
        doctor_id=2,
        patient_id=patient["id"],
        start_time=start,
        end_time=end,
        status=AppointmentStatus.BOOKED.value,
    )
    db.add(rebook)
    db.commit()  # must NOT raise
    db.refresh(rebook)
    assert rebook.id is not None
