"""PATCH /appointments/{id}/reschedule — rescheduling tests."""


def test_reschedule_moves_appointment_and_frees_old_slot(
    client, patient, slot, make_booking
):
    appt = make_booking(doctor_id=2, days_ahead=2, hour=10)

    resp = client.patch(
        f"/appointments/{appt['id']}/reschedule",
        json={"start_time": slot(3, 9)},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["start_time"] == slot(3, 9)
    assert body["end_time"] == slot(3, 9, 30)
    assert body["status"] == "booked"

    # old slot is listed as available again...
    old_day = slot(2, 0)[:10]
    old_avail = client.get("/doctors/2/availability", params={"date": old_day}).json()
    old_starts = [s["start_time"] for s in old_avail["available_slots"]]
    assert slot(2, 10) in old_starts

    # ...and the new slot is taken
    new_day = slot(3, 0)[:10]
    new_avail = client.get("/doctors/2/availability", params={"date": new_day}).json()
    new_starts = [s["start_time"] for s in new_avail["available_slots"]]
    assert slot(3, 9) not in new_starts


def test_reschedule_to_taken_slot_conflict_keeps_original(
    client, patient, other_patient, slot, make_booking
):
    target = make_booking(doctor_id=2, days_ahead=2, hour=10)                    # 10:00
    mover = make_booking(
        doctor_id=2, days_ahead=2, hour=11, patient_id=other_patient["id"]
    )                                                                            # 11:00

    resp = client.patch(
        f"/appointments/{mover['id']}/reschedule",
        json={"start_time": slot(2, 10)},  # already taken by `target`
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "SLOT_TAKEN"

    # the failed move must not have disturbed the original booking
    listing = client.get(
        f"/patients/{other_patient['id']}/appointments"
    ).json()["appointments"]
    assert listing[0]["start_time"] == slot(2, 11)


def test_reschedule_cancelled_appointment_rejected(client, make_booking):
    appt = make_booking(doctor_id=2, days_ahead=2, hour=10)
    client.patch(f"/appointments/{appt['id']}/cancel", json={"reason": "Gone"})

    resp = client.patch(
        f"/appointments/{appt['id']}/reschedule",
        json={"start_time": "2026-11-05T09:00:00"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "INVALID_STATE"
    assert "cancelled" in resp.json()["error"]["message"]


def test_reschedule_off_grid_rejected(client, make_booking, slot):
    appt = make_booking(doctor_id=2, days_ahead=2, hour=10)
    resp = client.patch(
        f"/appointments/{appt['id']}/reschedule",
        json={"start_time": slot(3, 9, 15)},
    )
    assert resp.status_code == 422
    assert "slot boundary" in resp.json()["error"]["message"]


def test_reschedule_outside_working_hours_rejected(client, make_booking, slot):
    appt = make_booking(doctor_id=2, days_ahead=2, hour=10)
    resp = client.patch(
        f"/appointments/{appt['id']}/reschedule",
        json={"start_time": slot(3, 7)},  # doctor starts at 09:00
    )
    assert resp.status_code == 422
    assert "working hours" in resp.json()["error"]["message"]


def test_reschedule_inside_lead_time_rejected(client, patient, make_booking, fake_now):
    """Frozen clock at 10:00 -> 10:30 the same day is inside the lead window."""
    # Book far in the future of the FROZEN clock (fake_now is active for the
    # whole test, so the original booking must be relative to it too).
    resp = client.post(
        "/appointments",
        json={
            "doctor_id": 2,
            "patient_id": patient["id"],
            "start_time": "2026-11-04T16:00:00",
        },
    )
    assert resp.status_code == 201, resp.text
    appt = resp.json()

    resp = client.patch(
        f"/appointments/{appt['id']}/reschedule",
        json={"start_time": "2026-11-02T10:30:00"},
    )
    assert resp.status_code == 422
    assert "at least 60 minutes" in resp.json()["error"]["message"]


def test_reschedule_to_same_start_rejected(client, make_booking, slot):
    appt = make_booking(doctor_id=2, days_ahead=2, hour=10)
    resp = client.patch(
        f"/appointments/{appt['id']}/reschedule",
        json={"start_time": slot(2, 10)},
    )
    assert resp.status_code == 422
    assert "already starts" in resp.json()["error"]["message"]


def test_reschedule_unknown_appointment_404(client, slot):
    resp = client.patch(
        "/appointments/9999/reschedule", json={"start_time": slot(3, 9)}
    )
    assert resp.status_code == 404


def test_reschedule_patient_conflict_across_doctors(client, patient, slot, make_booking):
    """Patient holds 10:00 with doctor 2; their 11:00 with doctor 4 cannot
    move onto their own 10:00 booking."""
    make_booking(doctor_id=2, days_ahead=2, hour=10)
    other = make_booking(doctor_id=4, days_ahead=2, hour=11)  # 09:00-13:00

    resp = client.patch(
        f"/appointments/{other['id']}/reschedule",
        json={"start_time": slot(2, 10)},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "PATIENT_DOUBLE_BOOKED"
