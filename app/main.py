"""FastAPI application factory: routers, error handlers, startup seeding."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import Base, SessionLocal, engine
from app.exceptions import BookingError
from app.routers import appointments, doctors, patients
from app.seed import seed_demo_data
from app.services.slots import clinic_now

# Seed activity should be visible in deployment logs (Render log stream).
logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Create missing tables and seed demo data (idempotent).

    Doctors plus a small reviewer-facing demo dataset (patients and upcoming
    bookings) are installed on an empty database — see app/seed.py.
    """
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_demo_data(db)
    yield


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description=(
        "REST API for booking 30-minute doctor appointments at a small clinic. "
        "Patients pick a free slot from a doctor's working hours; booked slots "
        "can be cancelled or rescheduled."
    ),
    lifespan=lifespan,
)


@app.exception_handler(BookingError)
async def booking_error_handler(_: Request, exc: BookingError):
    """Every domain error becomes {"error": {code, message}} + proper status."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.error_code, "message": exc.message}},
    )


@app.exception_handler(RequestValidationError)
async def request_validation_handler(_: Request, exc: RequestValidationError):
    """Keep framework-level 422s in the same error envelope as domain errors."""
    parts = []
    for err in exc.errors():
        loc = ".".join(str(piece) for piece in err.get("loc", ()) if piece != "body")
        parts.append(f"{loc}: {err.get('msg')}")
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "; ".join(parts) or "invalid request payload",
            }
        },
    )


app.include_router(doctors.router)
app.include_router(patients.router)
app.include_router(appointments.router)


@app.get("/", tags=["meta"])
def root():
    return {
        "service": settings.app_name,
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health", tags=["meta"])
def health():
    """Liveness probe used by the Render health check."""
    return {"status": "ok", "clinic_time": clinic_now().isoformat()}
