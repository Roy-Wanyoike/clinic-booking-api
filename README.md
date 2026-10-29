# Clinic Booking API

[![CI/CD](https://github.com/roy-wanyoike/clinic-booking-api/actions/workflows/ci.yml/badge.svg)](https://github.com/roy-wanyoike/clinic-booking-api/actions/workflows/ci.yml)

A REST API for a small clinic (5 doctors) where patients book 30-minute
appointment slots online. Built with **FastAPI + SQLAlchemy 2 + PostgreSQL**,
deployed on **Render**, with a **GitHub Actions** pipeline that tests every PR
and auto-deploys `main`.

- **Live API:** [clinic-booking-api-4k36.onrender.com](https://clinic-booking-api-4k36.onrender.com)
- **Interactive docs:** `/docs` (Swagger UI, generated from OpenAPI)
- **AI reflection (Section 4):** [AI_REFLECTION.md](./AI_REFLECTION.md)

---

## Demo data — try the live API in 60 seconds

The deployed API boots with a small **demo dataset** (idempotent startup
seeding, see decision D8): 4 registered patients and 5 upcoming booked
appointments spread across the 5 doctors, plus one soft-cancelled appointment
preserved with its audit trail (`cancel_reason` + `cancelled_at`). Demo
bookings are real rows in PostgreSQL — not mocks — and they auto-refresh to
upcoming dates if the service is idle for a long time, so they never go
stale.

Paste these into a browser (replace `YYYY-MM-DD` with tomorrow's date):

1. [Doctors & working hours](https://clinic-booking-api-4k36.onrender.com/doctors)
2. [Doctor 2's free slots](https://clinic-booking-api-4k36.onrender.com/doctors/2/availability?date=YYYY-MM-DD)
   — the 09:00 slot is already taken by a demo booking
3. [Patient 1's upcoming appointments](https://clinic-booking-api-4k36.onrender.com/patients/1/appointments)
   — two demo bookings with doctor details embedded
4. [Patient 2's full history](https://clinic-booking-api-4k36.onrender.com/patients/2/appointments?status=all)
   — includes the cancelled appointment and its reason
5. Then book, cancel or reschedule anything from
   [/docs](https://clinic-booking-api-4k36.onrender.com/docs) — the demo
   patients (ids 1-4) are ready to use, and cancelling a demo booking frees
   its slot immediately.

Set `SEED_DEMO_DATA=0` to boot without the demo dataset (doctor seeding still
runs).

---

## 1. System design

### 1.1 Requirements analysis

From the scenario, the system must guarantee that: a doctor's day is divided
into 30-minute slots inside *their* working hours; a patient can see free
slots for a doctor on a date; a booked slot can never be double-booked —
including when two requests race for the last slot; patients can cancel (with
a reason) and reschedule; nothing in the past can be booked. The clinic is
small today but wants to grow, so correctness rules live in one layer and the
data model avoids anything that breaks when volume increases.

### 1.2 Architecture

```
Client / Swagger UI
        │
        ▼
FastAPI routers  ── thin HTTP layer (status codes, docs, dependency wiring)
        │
        ▼
Booking service  ── all business rules (slot math, validation, conflicts)
        │
        ▼
PostgreSQL       ── source of truth; partial unique index guards the race
```

Routers contain no business logic; the service layer contains no HTTP
concepts. Services raise domain exceptions (`SlotTakenError`,
`BookingValidationError`, …) that one global handler maps to
`{"error": {"code", "message"}}` with the right status — so every failure in
the API is consistent and every rule is unit-testable without HTTP.

### 1.3 Data model

```mermaid
erDiagram
    DOCTOR ||--o{ APPOINTMENT : works
    PATIENT ||--o{ APPOINTMENT : books

    DOCTOR {
        int    id PK
        string name
        string specialty
        time   working_start "clinic-local"
        time   working_end   "clinic-local"
        int    slot_minutes  "30"
    }
    PATIENT {
        int    id PK
        string name
        string email UK
        string phone
    }
    APPOINTMENT {
        int      id PK
        int      doctor_id FK
        int      patient_id FK
        datetime start_time "clinic-local, grid-aligned"
        datetime end_time   "start + doctor.slot_minutes"
        string   status     "booked | cancelled"
        string   cancel_reason
        datetime cancelled_at
        datetime created_at
    }
```

**There is deliberately no `Slot` table.** Availability is *derived* on read:
generate the doctor's slot grid for the requested date, subtract active
appointments. Cancellation frees a slot automatically because "taken" is
defined by `status = 'booked'`, not by mutating slot rows.

**The concurrency guarantee is a partial unique index:**

```sql
CREATE UNIQUE INDEX uq_doctor_slot_active
ON appointments (doctor_id, start_time)
WHERE status = 'booked';
```

At most one *active* booking can exist per `(doctor, start_time)` — enforced
by the database, not by application discipline. Cancelled rows fall outside
the index, which is exactly why a cancelled slot becomes bookable again with
zero extra bookkeeping. Both PostgreSQL (production) and SQLite (tests)
support partial indexes, so the guarantee is identical in both.

### 1.4 Key decisions & trade-offs

| # | Decision | Why | Trade-off accepted |
|---|----------|-----|--------------------|
| D1 | **Derived availability** (no slot rows) | Removes slot/appointment state-sync bugs; cancel & reschedule need no slot bookkeeping | Recomputing the grid per request costs a few ms for one doctor-day; fine at this scale, and the unique index keeps it correct under load |
| D2 | **DB constraint as the source of truth** for double-booking | App-level checks alone are racy (check-then-insert window); DB-only gives ugly 500s | We pay for both: friendly app-level 409s *and* the index as the ultimate arbiter (proven by `tests/test_concurrency.py`) |
| D3 | **Naive clinic-local datetimes** (Africa/Nairobi, UTC+3, no DST) | The clinic operates in one timezone; wall-clock times match how staff and patients think | Multi-timezone expansion would require storing UTC + a per-clinic tz column — noted in the schema's design, cheap to migrate |
| D4 | **Soft cancellation** (`status`, `reason`, `cancelled_at`) | Preserves audit history ("why did this patient no-show?"); frees the slot via the partial index | Slightly larger table than hard deletes; trivially partitionable later |
| D5 | **Reschedule keeps the same doctor**, validated like a fresh booking | Matches the real workflow (you move a consultation, you don't silently switch doctors); single atomic `UPDATE` means a colliding target slot rolls back the whole move | Switching doctors requires cancel + rebook; easy to relax later |
| D6 | **Patient double-booking guard** (409 across doctors) | The brief doesn't ask, but a patient in two places at once is a data-quality bug | Slightly stricter than required; typed as its own error code |
| D7 | **Slots inside the 60-minute lead window are hidden** from availability | Never advertise a slot the booking endpoint would reject | "Free" and "bookable" differ by definition; documented here |
| D8 | **Seeding a demo dataset at startup** (idempotent) | A fresh deployment is instantly demo-able: reviewers see doctors, patients and upcoming bookings instead of empty tables | In production this would move to a migration/admin step; `SEED_DEMO_DATA=0` disables the demo rows |
| D9 | **Auth is out of scope** | The brief describes one booking flow without logins; `patient_id` identifies the caller | Production would add JWT/OAuth and scope every appointment mutation to the caller |

### 1.5 Error model

All errors share one envelope, so clients parse one shape:

```json
{ "error": { "code": "SLOT_TAKEN", "message": "doctor 2 is already booked from ..." } }
```

| HTTP | Code | Meaning |
|------|------|---------|
| 404 | `NOT_FOUND` | doctor / patient / appointment does not exist |
| 409 | `SLOT_TAKEN` | the doctor's slot is already booked (or was just taken in a race) |
| 409 | `PATIENT_DOUBLE_BOOKED` | the patient already has an active appointment overlapping that time |
| 409 | `INVALID_STATE` | e.g. cancelling an already-cancelled appointment, rescheduling a cancelled one |
| 409 | `DUPLICATE` | e.g. patient email already registered |
| 422 | `VALIDATION_ERROR` | off-grid time, outside working hours, in the past, inside the 60-min lead window, blank cancel reason, timezone-offset value |

Status-code logic: **404** = the resource itself is missing; **422** = the
slot/request is structurally invalid; **409** = valid request, but the state
of the world conflicts with it.

### 1.6 Scaling path ("starting small but want to grow")

1. **More doctors/patients** — stateless API + managed Postgres scales
   horizontally; the per-request work stays O(doctors' day).
2. **Hot availability reads** — cache the derived grid per
   `(doctor, date)` with event invalidation on booking/cancel/reschedule.
3. **Multiple clinic branches / timezones** — store UTC + per-clinic tz (D3).
4. **Notifications** — outbox table + worker for SMS/email confirmations
   (Kenyan context: SMS-first via Africa's Talking).
5. **Auth & roles** — OAuth2/JWT; receptionist vs patient scopes.

---

## 2. Running locally

```bash
git clone https://github.com/roy-wanyoike/clinic-booking-api.git
cd clinic-booking-api

python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Optional: point at PostgreSQL; default is a local SQLite file.
# export DATABASE_URL=postgresql+psycopg2://user:pass@localhost:5432/clinicdb

uvicorn app.main:app --reload
# -> http://127.0.0.1:8000  (Swagger UI at /docs)
```

On startup the app creates tables and seeds a **demo dataset**: the 5 clinic
doctors, 4 demo patients and upcoming bookings (idempotent — runs only when
missing, see [Demo data](#demo-data--try-the-live-api-in-60-seconds)). You
can register your own patients through the API right away. Example journey:

```bash
# register a patient
curl -X POST localhost:8000/patients -H 'Content-Type: application/json' \
  -d '{"name": "Wanjiku Mwangi", "email": "wanjiku@example.com", "phone": "+254722000111"}'

# see doctor 2's free slots two days ahead
curl "localhost:8000/doctors/2/availability?date=$(date -d '+2 days' +%F)"

# book one
curl -X POST localhost:8000/appointments -H 'Content-Type: application/json' \
  -d '{"doctor_id": 2, "patient_id": 1, "start_time": "<paste-a-free-slot>"}'

# cancel / reschedule
curl -X PATCH localhost:8000/appointments/1/cancel -H 'Content-Type: application/json' \
  -d '{"reason": "Feeling better"}'
curl -X PATCH localhost:8000/appointments/2/reschedule -H 'Content-Type: application/json' \
  -d '{"start_time": "<another-free-slot>"}'
```

All times are clinic-local (Africa/Nairobi) wall-clock values, e.g.
`2026-11-05T09:00:00`. Values carrying a timezone offset are rejected with an
explanation (decision D3).

## 3. API reference

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/doctors` | all doctors + working hours |
| GET | `/doctors/{id}` | one doctor |
| GET | `/doctors/{id}/availability?date=YYYY-MM-DD` | free 30-min slots for that date |
| POST | `/patients` | register a patient |
| POST | `/appointments` | book a slot (201) |
| PATCH | `/appointments/{id}/cancel` | cancel with reason |
| PATCH | `/appointments/{id}/reschedule` | move to a new slot |
| GET | `/patients/{id}/appointments?status=upcoming\|cancelled\|all` | **bonus** — sorted by date |
| GET | `/health` | liveness probe |

Validation performed by `POST /appointments` (and identically by
reschedule): doctor & patient exist → 404; grid-aligned 30-minute start →
422; inside the doctor's working hours → 422; not in the past → 422; at
least 60 minutes ahead (bonus) → 422; doctor slot free → 409; patient not
already booked then → 409.

Response example (`POST /appointments`, 201):

```json
{
  "id": 1,
  "doctor_id": 2,
  "patient_id": 1,
  "start_time": "2026-11-05T09:00:00",
  "end_time": "2026-11-05T09:30:00",
  "status": "booked",
  "cancel_reason": null,
  "cancelled_at": null,
  "created_at": "2026-10-29T07:12:40.123456"
}
```

## 4. Testing

50 tests cover: the full slot-grid math, every validation branch of booking,
cancellation (slot freed + re-bookable + double-cancel 409), rescheduling
(moves, conflicts, state errors, original preserved on failure), the bonus
endpoints, timezone-offset rejection, the **demo-seed lifecycle**
(installation, idempotency, dirty-database reset, stale-booking refresh) and
**a true multi-threaded race** where two connections book the same slot and
exactly one wins (`tests/test_concurrency.py`).

```bash
pip install -r requirements-dev.txt
pytest --cov=app --cov-report=term-missing
```

Locally the suite runs on a file-based SQLite DB (zero setup); in CI it runs
against real PostgreSQL (see below) to prove the models and constraints on
the production engine. Time-dependent rules are tested deterministically by
freezing the service clock (`fake_now` fixture).

## 5. Deployment & CI/CD (Section 3)

- **Live URL:** https://clinic-booking-api-4k36.onrender.com
- **Deploy branch:** `main`. Every merged PR (i.e. push to `main`) triggers a
  deployment after the test job passes.
- **Provider:** Render — web service + free PostgreSQL, provisioned by the
  committed blueprint [`render.yaml`](./render.yaml).

**Pipeline** (`.github/workflows/ci.yml`):

| Trigger | Job | What it does |
|---------|-----|--------------|
| any pull request | `test` | installs deps, spins up a PostgreSQL 16 service container, runs `pytest --cov` |
| push to `main` | `test` | same gate on the merged code |
| push to `main`, tests green | `deploy` | POSTs to the Render **Deploy Hook** (`RENDER_DEPLOY_HOOK` secret) → Render builds and releases the new code |

Render is also configured with `autoDeploy: true` and a `/health` health
check as a second safety net. To reproduce the deployment:

1. Push this repo to GitHub.
2. Render dashboard → **New + → Blueprint** → pick the repo — the web service
   and database in `render.yaml` are provisioned automatically.
3. Copy the service's **Deploy Hook URL** into repo secrets as
   `RENDER_DEPLOY_HOOK` so the pipeline's deploy job can trigger releases.

A `Dockerfile` is included for portability (Fly.io, ECS, anything that runs
containers).

## 6. Ambiguities → decisions log

| Ambiguity in the brief | Decision |
|---|---|
| "That slot must not be available to others" — how strongly? | Enforced by a DB partial unique index, not just application checks (D2) |
| Cancel "with a reason" — optional? | Required and non-blank; stored with a timestamp for audit (D4) |
| Reschedule — can it change doctors? | Same doctor only; doctor switch = cancel + rebook (D5) |
| Do slots inside the 1-hour lead window appear in availability? | No — availability lists only bookable slots (D7) |
| Which timezone do naive times belong to? | Clinic-local Africa/Nairobi; offset-bearing values rejected (D3) |
| Slot length configurable? | Stored per doctor (`slot_minutes`, default 30) — the schema already supports other lengths |
| Weekends / holidays? | Not modelled — doctors' `working_*` columns are the single source; holiday calendars are future work |

## 7. Future improvements

JWT auth with per-patient scoping (D9) · lunch-break / multi-window working
hours · holiday calendars · notification outbox + SMS · pagination on list
endpoints · request rate limiting · structured JSON logs with request IDs.

## 8. AI reflection

See [AI_REFLECTION.md](./AI_REFLECTION.md) for what AI was used for, where it
helped, where it was wrong, and which decisions were made without it.
