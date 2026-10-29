"""CORS: the static frontend demo (Vercel) consumes the API from the browser,
so cross-origin requests must be allowed and preflighted correctly."""

from fastapi.testclient import TestClient

FRONTEND_ORIGIN = "https://clinic-booking-demo.vercel.app"


def test_cors_preflight_get(client: TestClient):
    resp = client.options(
        "/doctors",
        headers={
            "Origin": FRONTEND_ORIGIN,
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "*"
    assert "GET" in resp.headers["access-control-allow-methods"]


def test_cors_preflight_patch(client: TestClient):
    """Cancel/reschedule are PATCHes — the browser preflights those too."""
    resp = client.options(
        "/appointments/1/cancel",
        headers={
            "Origin": FRONTEND_ORIGIN,
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "*"
    assert "PATCH" in resp.headers["access-control-allow-methods"]
    assert "content-type" in resp.headers["access-control-allow-headers"].lower()


def test_cors_origin_echoed_on_actual_response(client: TestClient):
    resp = client.get("/doctors", headers={"Origin": FRONTEND_ORIGIN})
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "*"
