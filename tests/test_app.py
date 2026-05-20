from fastapi.testclient import TestClient

from app import db
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


def test_create_chat_reuses_current_empty_chat(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    get_settings.cache_clear()

    with TestClient(app) as client:
        first = client.post("/api/chats").json()["chat"]
        second = client.post(
            "/api/chats",
            json={"current_chat_id": first["id"]},
        ).json()["chat"]
        chats = client.get("/api/chats").json()["chats"]

    assert second["id"] == first["id"]
    assert len(chats) == 1


def test_create_chat_makes_new_chat_after_messages(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    get_settings.cache_clear()

    with TestClient(app) as client:
        first = client.post("/api/chats").json()["chat"]
        db.add_message(first["id"], "user", "Hello")
        second = client.post(
            "/api/chats",
            json={"current_chat_id": first["id"]},
        ).json()["chat"]
        chats = client.get("/api/chats").json()["chats"]

    assert second["id"] != first["id"]
    assert len(chats) == 2
