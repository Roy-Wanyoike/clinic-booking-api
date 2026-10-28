"""Bonus endpoint: GET /patients/{id}/appointments (upcoming, sorted)."""


def test_upcoming_appointments_sorted_and_filtered(
    client, patient, slot, make_booking
):
    a = make_booking(doctor_id=2, days_ahead=3, hour=9)
    b = make_booking(doctor_id=2, days_ahead=1, hour=9)
    c = make_booking(doctor_id=2, days_ahead=2, hour=9)
    client.patch(f"/appointments/{b['id']}/cancel", json={"reason": "Cannot make it"})

    resp = client.get(f"/patients/{patient['id']}/appointments")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2  # the cancelled one is excluded
    starts = [appt["start_time"] for appt in body["appointments"]]
    assert starts == sorted(starts)
    assert slot(2, 9) in starts and slot(3, 9) in starts and slot(1, 9) not in starts
    assert all(appt["status"] == "booked" for appt in body["appointments"])
    assert a["id"] in {appt["id"] for appt in body["appointments"]}
    assert c["id"] in {appt["id"] for appt in body["appointments"]}


def test_cancelled_filter_returns_reason_and_doctor(client, patient, make_booking):
    appt = make_booking(doctor_id=2, days_ahead=1, hour=14)
    client.patch(
        f"/appointments/{appt['id']}/cancel", json={"reason": "Travelling upcountry"}
    )

    resp = client.get(
        f"/patients/{patient['id']}/appointments", params={"status": "cancelled"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    entry = body["appointments"][0]
    assert entry["status"] == "cancelled"
    assert entry["cancel_reason"] == "Travelling upcountry"
    assert entry["doctor"]["name"] == "Dr. Brian Kimani"


def test_all_filter_includes_every_appointment(client, patient, make_booking):
    make_booking(doctor_id=2, days_ahead=1, hour=9)
    cancelled = make_booking(doctor_id=2, days_ahead=2, hour=9)
    client.patch(
        f"/appointments/{cancelled['id']}/cancel", json={"reason": "Change of plans"}
    )

    resp = client.get(
        f"/patients/{patient['id']}/appointments", params={"status": "all"}
    )
    assert resp.status_code == 200
    assert resp.json()["count"] == 2


def test_invalid_status_filter_rejected(client, patient):
    resp = client.get(
        f"/patients/{patient['id']}/appointments", params={"status": "whenever"}
    )
    assert resp.status_code == 422


def test_unknown_patient_404(client):
    resp = client.get("/patients/999/appointments")
    assert resp.status_code == 404
