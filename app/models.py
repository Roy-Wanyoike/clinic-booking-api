"""Domain models: Doctor, Patient, Appointment.

Design notes
------------
* There is deliberately **no Slot table**. Availability is *derived* from each
  doctor's working hours minus active appointments. This removes an entire
  class of state-sync bugs (slot rows drifting out of sync with bookings) and
  keeps cancel/reschedule trivial: cancelling an appointment automatically
  frees the time again.
* Double-booking is prevented at the **database level** by a partial unique
  index on ``(doctor_id, start_time)`` limited to rows whose status is
  ``booked``. Application-level checks produce friendly 409 responses, but the
  index is the ultimate source of truth under concurrent requests, on both
  PostgreSQL and SQLite (both support partial indexes).
* Cancellation is a **soft state change** (status + reason + timestamp), never
  a DELETE, so the audit history of the appointment survives.
"""

from datetime import datetime, time, timezone
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, Index, String, Time, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _utcnow() -> datetime:
    """Naive UTC timestamp (deprecation-free on Python 3.12+)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AppointmentStatus(str, Enum):
    BOOKED = "booked"
    CANCELLED = "cancelled"


class Doctor(Base):
    __tablename__ = "doctors"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    specialty: Mapped[str] = mapped_column(String(120), nullable=False)

    # Working hours are stored per doctor (clinic-local wall clock).
    working_start: Mapped[time] = mapped_column(Time, nullable=False)
    working_end: Mapped[time] = mapped_column(Time, nullable=False)

    # Slot length in minutes (brief specifies 30; stored per doctor so the
    # same schema supports other slot sizes later).
    slot_minutes: Mapped[int] = mapped_column(nullable=False, default=30)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow
    )

    appointments: Mapped[list["Appointment"]] = relationship(back_populates="doctor")


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow
    )

    appointments: Mapped[list["Appointment"]] = relationship(back_populates="patient")


class Appointment(Base):
    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(primary_key=True)

    doctor_id: Mapped[int] = mapped_column(
        ForeignKey("doctors.id"), nullable=False, index=True
    )
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id"), nullable=False, index=True
    )

    # Clinic-local naive datetimes (see README "Design decisions").
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    end_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # Stored as a plain string ("booked" / "cancelled") rather than a native
    # DB enum so the partial-index WHERE clause behaves identically on both
    # SQLite (tests) and PostgreSQL (production).
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=AppointmentStatus.BOOKED.value, index=True
    )

    cancel_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow
    )

    doctor: Mapped[Doctor] = relationship(back_populates="appointments")
    patient: Mapped[Patient] = relationship(back_populates="appointments")

    __table_args__ = (
        # The concurrency guarantee: at most ONE active booking per
        # (doctor, start_time). Cancelled rows are excluded from the index,
        # so a cancelled slot becomes bookable again with no extra work.
        Index(
            "uq_doctor_slot_active",
            "doctor_id",
            "start_time",
            unique=True,
            postgresql_where=text("status = 'booked'"),
            sqlite_where=text("status = 'booked'"),
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<Appointment id={self.id} doctor={self.doctor_id} start={self.start_time} status={self.status}>"
