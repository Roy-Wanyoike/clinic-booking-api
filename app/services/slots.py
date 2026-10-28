"""Slot-grid helpers: pure date/time logic with no database access.

All datetimes in this service are naive *clinic-local* wall-clock values
(see README -> "Design decisions" for why).
"""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.config import settings


def clinic_now() -> datetime:
    """Current wall-clock time in the clinic's timezone as a naive datetime,
    matching how datetimes are stored."""
    return datetime.now(ZoneInfo(settings.clinic_timezone)).replace(tzinfo=None)


def is_slot_aligned(start: datetime, slot_minutes: int) -> bool:
    """True when the start falls exactly on the slot grid (e.g. :00 / :30
    for 30-minute slots)."""
    minutes_of_day = start.hour * 60 + start.minute
    return (
        minutes_of_day % slot_minutes == 0
        and start.second == 0
        and start.microsecond == 0
    )


def build_slot_grid(
    working_start: time, working_end: time, day: date, slot_minutes: int
) -> list[tuple[datetime, datetime]]:
    """Generate every (start, end) slot for one day inside the working window.

    A slot must fit entirely within working hours: for 09:00-17:00 hours the
    last slot starts at 16:30. A doctor with a lunch break is modelled as a
    shorter working window today (see README -> future improvements).
    """
    grid: list[tuple[datetime, datetime]] = []
    cursor = datetime.combine(day, working_start)
    window_end = datetime.combine(day, working_end)
    step = timedelta(minutes=slot_minutes)

    while cursor + step <= window_end:
        grid.append((cursor, cursor + step))
        cursor += step
    return grid
