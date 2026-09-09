from app.database import get_db
from app.main import app


def test_health_reports_ok_when_database_is_reachable(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_health_reports_unhealthy_when_database_is_unreachable(client):
    class _BrokenSession:
        def execute(self, *args, **kwargs):
            raise ConnectionError("simulated: database unreachable")

        def close(self):
            pass

    def _broken_get_db():
        db = _BrokenSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _broken_get_db
    try:
        res = client.get("/api/health")
    finally:
        del app.dependency_overrides[get_db]

    assert res.status_code == 503
    body = res.json()
    assert body["status"] == "unhealthy"


def test_health_logs_at_error_level_when_database_is_unreachable(client, caplog):
    """This is what makes the failure loud rather than silent - once
    SENTRY_DSN is configured, the LoggingIntegration wired up in
    sentry_config.py turns any ERROR-level log record into a Sentry
    event automatically, the same mechanism every other failure path in
    this app already relies on."""

    class _BrokenSession:
        def execute(self, *args, **kwargs):
            raise ConnectionError("simulated: database unreachable")

        def close(self):
            pass

    def _broken_get_db():
        db = _BrokenSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _broken_get_db
    try:
        with caplog.at_level("ERROR"):
            client.get("/api/health")
    finally:
        del app.dependency_overrides[get_db]

    error_records = [r for r in caplog.records if r.levelname == "ERROR"]
    assert any("health.database_unreachable" in r.message for r in error_records)
