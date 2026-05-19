from types import SimpleNamespace

from app.services.ai import _wait_for_gemini_file


class FakeFiles:
    def __init__(self):
        self.calls = 0

    def get(self, *, name):
        self.calls += 1
        assert name == "files/audio-1"
        return SimpleNamespace(name=name, state="ACTIVE")


def test_wait_for_gemini_file_polls_until_active(monkeypatch):
    fake_client = SimpleNamespace(files=FakeFiles())
    uploaded_file = SimpleNamespace(name="files/audio-1", state="PROCESSING")
    monkeypatch.setattr("app.services.ai.time.sleep", lambda _: None)

    active_file = _wait_for_gemini_file(
        fake_client,
        uploaded_file,
        timeout_seconds=10,
        poll_interval_seconds=0,
    )

    assert active_file.state == "ACTIVE"
    assert fake_client.files.calls == 1

