"""Seed data: the clinic's 5 doctors.

Seeding is idempotent — doctors are only inserted when the table is empty —
and runs once at application startup (see app/main.py lifespan). This keeps
a fresh deployment instantly usable without manual admin steps. Patients are
NOT seeded; they are created through POST /patients.
"""

from datetime import time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Doctor

SEED_DOCTORS = [
    {"name": "Dr. Amina Okoth",   "specialty": "General Medicine", "working_start": time(8, 0),  "working_end": time(16, 0)},
    {"name": "Dr. Brian Kimani",  "specialty": "Paediatrics",      "working_start": time(9, 0),  "working_end": time(17, 0)},
    {"name": "Dr. Grace Wanjiru", "specialty": "Dermatology",      "working_start": time(10, 0), "working_end": time(18, 0)},
    {"name": "Dr. David Otieno",  "specialty": "Cardiology",       "working_start": time(9, 0),  "working_end": time(13, 0)},
    {"name": "Dr. Fatuma Ali",    "specialty": "General Medicine", "working_start": time(14, 0), "working_end": time(20, 0)},
]


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
