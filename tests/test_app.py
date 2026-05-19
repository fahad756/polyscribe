from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app


def test_index_and_health_load(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    get_settings.cache_clear()

    with TestClient(app) as client:
        index = client.get("/")
        health = client.get("/healthz")

    assert index.status_code == 200
    assert "PolyScribe" in index.text
    assert health.json() == {"ok": True}

