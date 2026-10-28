"""PATCH /appointments/{id}/cancel — cancellation tests."""


def test_cancel_success(client, make_booking, slot):
    appt = make_booking(doctor_id=2, days_ahead=2, hour=10)

    resp = client.patch(
        f"/appointments/{appt['id']}/cancel", json={"reason": "Patient recovered"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "cancelled"
    assert body["cancel_reason"] == "Patient recovered"
    assert body["cancelled_at"] is not None


def test_cancelled_slot_becomes_bookable_again(client, patient, other_patient, slot, make_booking):
    appt = make_booking(doctor_id=2, days_ahead=3, hour=11)
    cancel = client.patch(
        f"/appointments/{appt['id']}/cancel", json={"reason": "Schedule conflict"}
    )
    assert cancel.status_code == 200

    # 1. availability lists the freed slot again
    day = slot(3, 0)[:10]
    avail = client.get("/doctors/2/availability", params={"date": day}).json()
    starts = [s["start_time"] for s in avail["available_slots"]]
    assert slot(3, 11) in starts

    # 2. another patient can book it
    rebook = client.post(
        "/appointments",
        json={
            "doctor_id": 2,
            "patient_id": other_patient["id"],
            "start_time": slot(3, 11),
        },
    )
    assert rebook.status_code == 201, rebook.text


def test_cancel_twice_conflict(client, make_booking):
    appt = make_booking(doctor_id=2, days_ahead=2, hour=9)
    first = client.patch(
        f"/appointments/{appt['id']}/cancel", json={"reason": "Duplicate request"}
    )
    assert first.status_code == 200

    second = client.patch(
        f"/appointments/{appt['id']}/cancel", json={"reason": "Yet another reason"}
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "INVALID_STATE"
    assert "already cancelled" in second.json()["error"]["message"]


def test_cancel_blank_reason_rejected(client, make_booking):
    appt = make_booking(doctor_id=2, days_ahead=2, hour=13)
    resp = client.patch(f"/appointments/{appt['id']}/cancel", json={"reason": "   "})
    assert resp.status_code == 422


def test_cancel_missing_reason_rejected(client, make_booking):
    appt = make_booking(doctor_id=2, days_ahead=2, hour=13, minute=30)
    resp = client.patch(f"/appointments/{appt['id']}/cancel", json={})
    assert resp.status_code == 422


def test_cancel_unknown_appointment_404(client):
    resp = client.patch("/appointments/9999/cancel", json={"reason": "Nope"})
    assert resp.status_code == 404
