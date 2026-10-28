"""Domain exceptions mapped to consistent HTTP error responses.

Every business-rule failure is raised as one of these and translated by a
global exception handler (see app/main.py) into:

    {"error": {"code": "<MACHINE_READABLE_CODE>", "message": "<human text>"}}

with the correct HTTP status (404 / 409 / 422).
"""

from http import HTTPStatus


class BookingError(Exception):
    """Base class for all domain errors."""

    status_code: int = HTTPStatus.BAD_REQUEST
    error_code: str = "BOOKING_ERROR"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NotFoundError(BookingError):
    status_code = HTTPStatus.NOT_FOUND
    error_code = "NOT_FOUND"


class BookingValidationError(BookingError):
    """Slot is structurally invalid (off-grid, out of hours, in the past...)."""

    status_code = HTTPStatus.UNPROCESSABLE_ENTITY
    error_code = "VALIDATION_ERROR"


class SlotTakenError(BookingError):
    """The doctor already has an active appointment in this slot."""

    status_code = HTTPStatus.CONFLICT
    error_code = "SLOT_TAKEN"


class PatientSlotConflictError(BookingError):
    """The patient already has an active appointment in this time range."""

    status_code = HTTPStatus.CONFLICT
    error_code = "PATIENT_DOUBLE_BOOKED"


class DuplicateResourceError(BookingError):
    """A unique resource constraint was violated (e.g. patient email)."""

    status_code = HTTPStatus.CONFLICT
    error_code = "DUPLICATE"


class InvalidStateError(BookingError):
    """Operation not allowed for the appointment's current state (e.g. cancel
    an already-cancelled appointment)."""

    status_code = HTTPStatus.CONFLICT
    error_code = "INVALID_STATE"
