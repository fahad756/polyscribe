from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency is declared, this keeps imports graceful.
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv()


TRUE_VALUES = {"1", "true", "yes", "on"}
DEFAULT_ALLOWED_EXTENSIONS = {
    "mp3",
    "mp4",
    "mpeg",
    "mpga",
    "m4a",
    "wav",
    "webm",
    "mov",
    "mkv",
    "aac",
    "ogg",
    "flac",
}


def _bool_from_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in TRUE_VALUES


def _int_from_env(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(value, minimum)


def _extensions_from_env() -> frozenset[str]:
    raw = os.getenv("ALLOWED_EXTENSIONS")
    if not raw:
        return frozenset(DEFAULT_ALLOWED_EXTENSIONS)
    values = {
        value.strip().lower().lstrip(".")
        for value in raw.split(",")
        if value.strip()
    }
    return frozenset(values or DEFAULT_ALLOWED_EXTENSIONS)


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_env: str
    chat_provider: str
    transcription_provider: str
    gemini_api_key: str
    gemini_model: str
    groq_api_key: str
    groq_transcription_model: str
    database_path: Path
    upload_dir: Path
    max_upload_mb: int
    audio_chunk_max_mb: int
    keep_uploads: bool
    ffmpeg_segment_seconds: int
    allowed_extensions: frozenset[str]
    request_timeout_seconds: int
    max_chat_context_chars: int
    app_password: str
    secret_key: str
    secure_cookies: bool
    session_max_age_seconds: int

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def audio_chunk_max_bytes(self) -> int:
        return self.audio_chunk_max_mb * 1024 * 1024


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    app_env = os.getenv("APP_ENV", "development").strip().lower()
    return Settings(
        app_name=os.getenv("APP_NAME", "PolyScribe"),
        app_env=app_env,
        chat_provider=os.getenv("CHAT_PROVIDER", "gemini").strip().lower(),
        transcription_provider=os.getenv("TRANSCRIPTION_PROVIDER", "groq").strip().lower(),
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip(),
        groq_api_key=os.getenv("GROQ_API_KEY", "").strip(),
        groq_transcription_model=os.getenv(
            "GROQ_TRANSCRIPTION_MODEL",
            "whisper-large-v3-turbo",
        ).strip(),
        database_path=Path(os.getenv("DATABASE_PATH", "runtime/polyscribe.db")),
        upload_dir=Path(os.getenv("UPLOAD_DIR", "runtime/uploads")),
        max_upload_mb=_int_from_env("MAX_UPLOAD_MB", 200),
        audio_chunk_max_mb=_int_from_env(
            "DIRECT_AUDIO_MAX_MB",
            24,
        ),
        keep_uploads=_bool_from_env("KEEP_UPLOADS", False),
        ffmpeg_segment_seconds=_int_from_env("FFMPEG_SEGMENT_SECONDS", 1200, 60),
        allowed_extensions=_extensions_from_env(),
        request_timeout_seconds=_int_from_env("REQUEST_TIMEOUT_SECONDS", 180, 10),
        max_chat_context_chars=_int_from_env("MAX_CHAT_CONTEXT_CHARS", 60000, 2000),
        app_password=os.getenv("APP_PASSWORD", ""),
        secret_key=os.getenv("SECRET_KEY", "change-me-for-production"),
        secure_cookies=_bool_from_env("SECURE_COOKIES", app_env == "production"),
        session_max_age_seconds=_int_from_env("SESSION_MAX_AGE_SECONDS", 86400),
    )


def ensure_runtime_paths(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
