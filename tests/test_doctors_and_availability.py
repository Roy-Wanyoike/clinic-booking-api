"""Doctors listing + derived availability endpoint tests."""

from datetime import datetime, timedelta

from app.services.slots import clinic_now


def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    datetime.fromisoformat(body["clinic_time"])  # parses


def test_five_doctors_seeded(client):
    resp = client.get("/doctors")
    assert resp.status_code == 200
    doctors = resp.json()
    assert len(doctors) == 5
    assert all(d["slot_minutes"] == 30 for d in doctors)
    names = {d["name"] for d in doctors}
    assert "Dr. Brian Kimani" in names


def test_doctor_detail(client):
    resp = client.get("/doctors/2")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Dr. Brian Kimani"
    assert body["working_start"] == "09:00:00"
    assert body["working_end"] == "17:00:00"


def test_doctor_detail_unknown_404(client):
    resp = client.get("/doctors/999")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_availability_full_working_day_grid(client, slot):
    """09:00-17:00 with 30-minute slots = 16 free slots, 09:00..16:30."""
    resp = client.get("/doctors/2/availability", params={"date": slot(3, 0)[:10]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 16
    starts = [s["start_time"] for s in body["available_slots"]]
    assert starts[0].endswith("T09:00:00")
    assert starts[-1].endswith("T16:30:00")
    # every slot is exactly 30 minutes
    for s in body["available_slots"]:
        start = datetime.fromisoformat(s["start_time"])
        end = datetime.fromisoformat(s["end_time"])
        assert end - start == timedelta(minutes=30)


def test_availability_excludes_booked_slots(client, patient, slot):
    client.post(
        "/appointments",
        json={
            "doctor_id": 2,
            "patient_id": patient["id"],
            "start_time": slot(3, 10),
        },
    )
    resp = client.get("/doctors/2/availability", params={"date": slot(3, 0)[:10]})
    body = resp.json()
    starts = [s["start_time"] for s in body["available_slots"]]
    assert slot(3, 10) not in starts
    assert body["count"] == 15


def test_availability_hides_slots_inside_lead_time_window(client, fake_now):
    """With the clock frozen at 10:00, slots before 11:00 cannot be booked
    (60-minute lead rule), so availability starts at 11:00."""
    resp = client.get(
        "/doctors/2/availability", params={"date": fake_now.date().isoformat()}
    )
    assert resp.status_code == 200
    body = resp.json()
    starts = [s["start_time"] for s in body["available_slots"]]
    # 16 grid slots minus 4 hidden (09:00, 09:30, 10:00, 10:30) = 12
    assert body["count"] == 12
    assert starts[0].endswith("T11:00:00")
    assert all(s > "2026-11-02T10:30" for s in starts)


def test_availability_past_date_rejected(client, slot):
    past = (clinic_now() - timedelta(days=1)).date().isoformat()
    resp = client.get("/doctors/2/availability", params={"date": past})
    assert resp.status_code == 422
    assert "past" in resp.json()["error"]["message"]


def test_availability_unknown_doctor_404(client, slot):
    resp = client.get("/doctors/999/availability", params={"date": slot(3, 0)[:10]})
    assert resp.status_code == 404


def test_availability_requires_date_param(client):
    resp = client.get("/doctors/2/availability")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
