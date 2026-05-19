from app.config import DEFAULT_ALLOWED_EXTENSIONS, get_settings


def test_settings_defaults(monkeypatch):
    monkeypatch.delenv("ALLOWED_EXTENSIONS", raising=False)
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.openai_text_model == "gpt-5-mini"
    assert settings.openai_transcription_model == "gpt-4o-mini-transcribe"
    assert settings.allowed_extensions == frozenset(DEFAULT_ALLOWED_EXTENSIONS)


def test_allowed_extensions_are_normalized(monkeypatch):
    monkeypatch.setenv("ALLOWED_EXTENSIONS", ".MP3, wav, mp4")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.allowed_extensions == frozenset({"mp3", "wav", "mp4"})

