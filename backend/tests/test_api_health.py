"""T3: /health phản ánh trạng thái DB thật (ok / degraded / down)."""
import app.main as m
from fastapi.testclient import TestClient


def test_health_ok():
    r = TestClient(m.app).get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["features_loaded"] > 0


def test_health_degraded_when_catalog_empty(monkeypatch):
    class _R:
        def scalar_one(self):
            return 0

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, *a):
            return _R()

    class _Eng:
        def connect(self):
            return _Conn()

    monkeypatch.setattr(m, "get_engine", lambda: _Eng())
    r = TestClient(m.app).get("/health")
    assert r.status_code == 503
    assert r.json()["status"] == "degraded"


def test_health_down_when_db_errors(monkeypatch):
    def _boom():
        raise RuntimeError("no db")

    monkeypatch.setattr(m, "get_engine", _boom)
    r = TestClient(m.app).get("/health")
    assert r.status_code == 503
    assert r.json()["status"] == "db_unavailable"
