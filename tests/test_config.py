from app.config import DEFAULT_ALLOWED_EXTENSIONS, get_settings
from app.services.ai import AIService


def test_settings_defaults(monkeypatch):
    monkeypatch.delenv("ALLOWED_EXTENSIONS", raising=False)
    monkeypatch.delenv("CHAT_PROVIDER", raising=False)
    monkeypatch.delenv("TRANSCRIPTION_PROVIDER", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.delenv("GROQ_TRANSCRIPTION_MODEL", raising=False)
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.chat_provider == "gemini"
    assert settings.transcription_provider == "groq"
    assert settings.gemini_model == "gemini-2.5-flash"
    assert settings.groq_transcription_model == "whisper-large-v3-turbo"
    assert settings.allowed_extensions == frozenset(DEFAULT_ALLOWED_EXTENSIONS)


def test_allowed_extensions_are_normalized(monkeypatch):
    monkeypatch.setenv("ALLOWED_EXTENSIONS", ".MP3, wav, mp4")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.allowed_extensions == frozenset({"mp3", "wav", "mp4"})


def test_direct_audio_limit_uses_new_name(monkeypatch):
    monkeypatch.setenv("DIRECT_AUDIO_MAX_MB", "30")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.audio_chunk_max_mb == 30
    assert settings.audio_chunk_max_bytes == 30 * 1024 * 1024


def test_configured_services_can_be_constructed(monkeypatch):
    monkeypatch.setenv("CHAT_PROVIDER", "gemini")
    monkeypatch.setenv("TRANSCRIPTION_PROVIDER", "groq")
    get_settings.cache_clear()

    service = AIService(get_settings())

    assert service is not None

