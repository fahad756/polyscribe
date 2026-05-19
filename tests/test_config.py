from app.config import DEFAULT_ALLOWED_EXTENSIONS, get_settings


def test_settings_defaults(monkeypatch):
    monkeypatch.delenv("ALLOWED_EXTENSIONS", raising=False)
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    monkeypatch.delenv("LOCAL_WHISPER_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.ai_provider == "local"
    assert settings.local_whisper_model == "base"
    assert settings.ollama_model == "llama3.2:3b"
    assert settings.gemini_model == "gemini-2.5-flash"
    assert settings.openai_text_model == "gpt-5-mini"
    assert settings.openai_transcription_model == "gpt-4o-mini-transcribe"
    assert settings.allowed_extensions == frozenset(DEFAULT_ALLOWED_EXTENSIONS)


def test_allowed_extensions_are_normalized(monkeypatch):
    monkeypatch.setenv("ALLOWED_EXTENSIONS", ".MP3, wav, mp4")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.allowed_extensions == frozenset({"mp3", "wav", "mp4"})


def test_direct_audio_limit_prefers_new_name(monkeypatch):
    monkeypatch.setenv("OPENAI_AUDIO_MAX_MB", "12")
    monkeypatch.setenv("DIRECT_AUDIO_MAX_MB", "30")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.audio_chunk_max_mb == 30
    assert settings.openai_audio_max_bytes == settings.audio_chunk_max_bytes
