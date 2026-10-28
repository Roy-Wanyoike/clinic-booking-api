"""POST /appointments — booking validation and conflict tests."""


def test_book_valid_slot(client, patient, slot):
    resp = client.post(
        "/appointments",
        json={
            "doctor_id": 2,
            "patient_id": patient["id"],
            "start_time": slot(2, 9),
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "booked"
    assert body["start_time"] == slot(2, 9)
    assert body["end_time"] == slot(2, 9, 30)  # 30-minute slot derived server-side
    assert body["cancel_reason"] is None
    assert body["id"] > 0


def test_same_slot_cannot_be_booked_twice(client, patient, slot):
    payload = {
        "doctor_id": 2,
        "patient_id": patient["id"],
        "start_time": slot(2, 10),
    }
    assert client.post("/appointments", json=payload).status_code == 201

    resp = client.post("/appointments", json=payload)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "SLOT_TAKEN"


def test_off_grid_start_rejected(client, patient, slot):
    """09:10 is not a 30-minute grid boundary."""
    resp = client.post(
        "/appointments",
        json={
            "doctor_id": 2,
            "patient_id": patient["id"],
            "start_time": slot(2, 9, 10),
        },
    )
    assert resp.status_code == 422
    assert "slot boundary" in resp.json()["error"]["message"]


def test_start_before_working_hours_rejected(client, patient, slot):
    """Doctor 2 starts at 09:00; 08:00 is aligned but too early."""
    resp = client.post(
        "/appointments",
        json={
            "doctor_id": 2,
            "patient_id": patient["id"],
            "start_time": slot(2, 8),
        },
    )
    assert resp.status_code == 422
    assert "working hours" in resp.json()["error"]["message"]


def test_slot_overrunning_working_hours_rejected(client, patient, slot):
    """A slot starting at closing time would end after hours."""
    resp = client.post(
        "/appointments",
        json={
            "doctor_id": 2,  # works 09:00-17:00
            "patient_id": patient["id"],
            "start_time": slot(2, 17),
        },
    )
    assert resp.status_code == 422
    assert "working hours" in resp.json()["error"]["message"]


def test_past_slot_rejected(client, patient, slot):
    resp = client.post(
        "/appointments",
        json={
            "doctor_id": 2,
            "patient_id": patient["id"],
            "start_time": slot(-1, 10),
        },
    )
    assert resp.status_code == 422
    assert "past" in resp.json()["error"]["message"]


def test_booking_inside_lead_time_window_rejected(client, patient, fake_now):
    """Bonus rule: clock frozen at 10:00 -> a 10:30 slot is <60 minutes away."""
    resp = client.post(
        "/appointments",
        json={
            "doctor_id": 2,
            "patient_id": patient["id"],
            "start_time": "2026-11-02T10:30:00",
        },
    )
    assert resp.status_code == 422
    assert "at least 60 minutes" in resp.json()["error"]["message"]


def test_earliest_bookable_start_is_allowed(client, patient, fake_now):
    """Exactly 60 minutes ahead (11:00 with clock at 10:00) is bookable."""
    resp = client.post(
        "/appointments",
        json={
            "doctor_id": 2,
            "patient_id": patient["id"],
            "start_time": "2026-11-02T11:00:00",
        },
    )
    assert resp.status_code == 201, resp.text


def test_unknown_doctor_404(client, patient, slot):
    resp = client.post(
        "/appointments",
        json={
            "doctor_id": 999,
            "patient_id": patient["id"],
            "start_time": slot(2, 9),
        },
    )
    assert resp.status_code == 404
    assert "doctor" in resp.json()["error"]["message"]


def test_unknown_patient_404(client, slot):
    resp = client.post(
        "/appointments",
        json={"doctor_id": 2, "patient_id": 999, "start_time": slot(2, 9)},
    )
    assert resp.status_code == 404
    assert "patient" in resp.json()["error"]["message"]


def test_timezone_aware_start_rejected(client, patient, slot):
    """Times must be clinic-local naive values; offsets are ambiguous here."""
    naive = slot(2, 9)
    resp = client.post(
        "/appointments",
        json={
            "doctor_id": 2,
            "patient_id": patient["id"],
            "start_time": f"{naive}+03:00",
        },
    )
    assert resp.status_code == 422
    assert "timezone" in resp.json()["error"]["message"]


def test_patient_cannot_hold_two_slots_at_same_time(client, patient, slot):
    """Same patient, two different doctors, same time -> conflict."""
    first = client.post(
        "/appointments",
        json={
            "doctor_id": 2,  # 09:00-17:00
            "patient_id": patient["id"],
            "start_time": slot(2, 10),
        },
    )
    assert first.status_code == 201

    resp = client.post(
        "/appointments",
        json={
            "doctor_id": 4,  # Dr. David Otieno, 09:00-13:00
            "patient_id": patient["id"],
            "start_time": slot(2, 10),
        },
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "PATIENT_DOUBLE_BOOKED"
