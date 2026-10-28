# Section 4 — AI Reflection

> **Note to self before submitting:** replace every `[bracketed]` placeholder
> with my own experience, and delete this note. The team uses AI daily — the
> goal is an accurate picture of how I actually worked, not a perfect story.

## 1. What I used AI for across the four sections

- **Section 1 (design):** as a sounding board for the two big calls — whether
  to persist slot rows or derive availability, and how to make
  double-booking safe under concurrent requests. I asked it to attack my
  draft design and to name failure modes I hadn't considered.
- **Section 2 (API):** scaffolding FastAPI/SQLAlchemy boilerplate (Pydantic
  schemas, dependency wiring), generating a first-pass test matrix, and
  reviewing my error messages for tone ("does a receptionist understand
  this?").
- **Section 3 (deploy/CI):** GitHub Actions YAML structure, the PostgreSQL
  service-container block, and Render blueprint fields — the syntax is fiddly
  and AI saved real time.
- **Section 4 (this file):** help structuring the reflection.

Everything AI produced was reviewed and tested before it landed; the test
suite (44 tests) is the arbiter, not the AI.

## 2. One example where an AI suggestion improved my work

My first plan for double-booking prevention was application-level: check
availability, then insert. I asked AI:

> "I'm building a clinic booking API in FastAPI + PostgreSQL. My plan:
> SELECT overlapping active appointments, and if none, INSERT. Walk through
> how this fails when two requests race for the same slot, and propose a fix
> that keeps cancel/reschedule simple."

It walked through the check-then-insert race window concretely and proposed a
**partial unique index** on `(doctor_id, start_time) WHERE status =
'booked'` with the application mapping the resulting `IntegrityError` to a
friendly 409. That's materially better than what I had: the database becomes
the source of truth, cancel/reschedule need no slot bookkeeping, and the
index works identically on SQLite (tests) and PostgreSQL (production). I
added a genuine two-thread race test to prove it.

## 3. One example where AI output was wrong or incomplete, and how I caught it

Early in design, AI suggested pre-generating slot rows for the next 30 days
with a `booked` flag. It sounded productive, but reviewing the proposal
against the requirements I found three real problems: (1) cancelling or
rescheduling must mutate a slot row in the same transaction as the
appointment or the two drift out of sync; (2) "which 30 days?" — the table
needs a rolling-window generator job; (3) it pushes timezone logic into
stored rows. Derived availability (grid computed from working hours minus
active appointments) has none of those failure modes, so I rejected the
suggestion and documented the reasoning in the README.

Smaller catch: AI-generated code used `datetime.utcnow()`, deprecated in
Python 3.12 — the deprecation warning surfaced on the first test run and I
replaced it with a timezone-explicit helper.

## 4. Two decisions I made without AI — and why I trusted my judgment

1. **Naive clinic-local datetimes (Africa/Nairobi) instead of storing UTC.**
   Nairobi has no DST and the clinic runs in one place, so wall-clock times
   match how staff and patients think; converting everywhere would add
   complexity with no payoff at this scale. I trusted this because it's
   domain reasoning — [I know the deployment context] — and the migration
   path to UTC-per-clinic is written down if the clinic grows.
2. **Reschedule keeps the same doctor.** In a real clinic, "move my
   appointment" means moving *that* consultation; switching doctors is a
   cancel-and-rebook. Keeping the endpoint single-purpose made validation
   cleaner (one doctor's working hours, one overlap check) and matches user
   intent. I trusted my judgment here because it's a product-behaviour call,
   not a technical one — [add a sentence on your own experience with similar
   product decisions].
