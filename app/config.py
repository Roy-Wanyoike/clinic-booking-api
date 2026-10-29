"""Application configuration via environment variables (12-factor style).

The same settings object drives local development (SQLite by default so the
project runs with zero setup) and production (PostgreSQL provisioned by
Render, injected as DATABASE_URL).
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # SQLAlchemy connection string.
    #   local dev : sqlite:///./clinic_booking.db (default, zero setup)
    #   production: postgresql://... (set by render.yaml from the managed DB)
    database_url: str = "sqlite:///./clinic_booking.db"

    # The clinic operates in a single timezone. All datetimes accepted by the
    # API and stored in the database are naive *clinic-local* wall-clock times.
    clinic_timezone: str = "Africa/Nairobi"

    # Bonus rule: bookings must start at least this many minutes in the future.
    min_lead_minutes: int = 60

    # Fallback slot length in minutes; each doctor may override it.
    slot_minutes: int = 30

    # Title shown in OpenAPI docs.
    app_name: str = "Clinic Booking API"

    # Browser origins allowed to call the API from JavaScript (comma-
    # separated). Default "*" keeps the hosted demo consumable from any
    # static host (e.g. the Vercel-hosted frontend/ demo); production would
    # pin this to the real frontend origins, e.g.
    # CORS_ORIGINS=https://clinic-demo.vercel.app,https://clinic.example.com
    cors_origins: str = "*"


settings = Settings()

# Fail fast on misconfiguration (12-factor): a DATABASE_URL that SQLAlchemy
# cannot possibly parse should crash at startup with a helpful message, not
# deep inside the first query.
_KNOWN_DB_SCHEMES = ("sqlite", "postgresql", "postgres", "mysql", "mssql", "oracle")

_scheme = settings.database_url.split(":", 1)[0].split("+", 1)[0].lower()
if _scheme not in _KNOWN_DB_SCHEMES:
    raise RuntimeError(
        f"DATABASE_URL '{settings.database_url}' is not a valid SQLAlchemy URL. "
        "Expected e.g. sqlite:///./clinic_booking.db or "
        "postgresql://user:password@host:5432/dbname"
    )
