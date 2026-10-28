"""Shared pytest fixtures.

Isolation strategy: every test gets a fresh schema (drop_all/create_all) on a
file-based SQLite database, with the clinic's doctors re-seeded. A file DB
(instead of :memory:) is required so the concurrency tests can open several
independent connections and race for the same slot.

CI runs the very same suite against PostgreSQL (see .github/workflows/ci.yml)
to prove production parity of the models and constraints.
"""

import os
from datetime import datetime, timedelta
from uuid import uuid4

# MUST run before any `app` import: the engine reads DATABASE_URL at import
# time. Tests default to a local SQLite file; CI sets TEST_DATABASE_URL to a
# PostgreSQL URL to prove production parity.
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "sqlite:///./test_clinic.db"
)

import pytest
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import Patient
from app.seed import seed_doctors
from app.services.slots import clinic_now

# Fixed "now" for deterministic lead-time / past-slot tests: a Monday 10:00
# clinic time. Tests that use `fake_now` hardcode slot strings around it.
FAKE_NOW = datetime(2026, 11, 2, 10, 0, 0)


@pytest.fixture()
def db():
    """Fresh schema + the 5 seeded doctors for every test."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    seed_doctors(session)
    yield session
    session.close()


@pytest.fixture()
def client(db):
    """TestClient bound to the fresh database (lifespan intentionally not
    run — the db fixture owns schema creation and seeding)."""
    return TestClient(app)


@pytest.fixture()
def patient(client):
    """A registered patient (created through the real API)."""
    resp = client.post(
        "/patients",
        json={
            "name": "Jane Doe",
            "email": f"jane.{uuid4().hex[:8]}@example.com",
            "phone": "+254711222333",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture()
def slot():
    """ISO clinic-local timestamp for `days_ahead` days from now."""

    def _slot(days_ahead: int, hour: int, minute: int = 0) -> str:
        day = (clinic_now() + timedelta(days=days_ahead)).date()
        return f"{day.isoformat()}T{hour:02d}:{minute:02d}:00"

    return _slot


@pytest.fixture()
def fake_now(monkeypatch):
    """Freeze booking-service clock at FAKE_NOW for deterministic tests."""
    monkeypatch.setattr("app.services.booking.clinic_now", lambda: FAKE_NOW)
    return FAKE_NOW


@pytest.fixture()
def make_booking(client, patient, slot):
    """Happy-path booking factory returning the created appointment dict."""

    def _make(
        doctor_id: int = 2,
        days_ahead: int = 2,
        hour: int = 10,
        minute: int = 0,
        patient_id: int | None = None,
    ) -> dict:
        resp = client.post(
            "/appointments",
            json={
                "doctor_id": doctor_id,
                "patient_id": patient_id or patient["id"],
                "start_time": slot(days_ahead, hour, minute),
            },
        )
        assert resp.status_code == 201, resp.text
        return resp.json()

    return _make


@pytest.fixture()
def other_patient(client):
    """A second registered patient (for re-booking freed slots etc.)."""
    resp = client.post(
        "/patients",
        json={"name": "John Roe", "email": f"john.{uuid4().hex[:8]}@example.com"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()
