from __future__ import annotations

import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile

from app.config import Settings


DIRECT_MEDIA_EXTENSIONS = {".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".wav", ".webm"}
READ_CHUNK_SIZE = 1024 * 1024


class MediaError(RuntimeError):
    """Raised when an uploaded media file cannot be accepted or prepared."""


@dataclass(frozen=True)
class SavedUpload:
    path: Path
    original_filename: str
    size_bytes: int
    extension: str


@dataclass(frozen=True)
class PreparedMedia:
    paths: list[Path]
    cleanup_dir: Path | None = None


def secure_filename(filename: str) -> str:
    name = Path(filename or "upload").name
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return name or f"upload_{uuid.uuid4().hex}"


def extension_for(filename: str) -> str:
    return Path(filename).suffix.lower().lstrip(".")


async def save_upload(file: UploadFile, settings: Settings) -> SavedUpload:
    original_filename = secure_filename(file.filename or "upload")
    extension = extension_for(original_filename)
    if extension not in settings.allowed_extensions:
        allowed = ", ".join(sorted(settings.allowed_extensions))
        raise MediaError(f"Unsupported file type '.{extension}'. Allowed: {allowed}.")

    destination = settings.upload_dir / f"{uuid.uuid4().hex}_{original_filename}"
    total = 0

    try:
        with destination.open("wb") as output:
            while True:
                chunk = await file.read(READ_CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > settings.max_upload_bytes:
                    raise MediaError(
                        f"File is too large. Maximum upload size is {settings.max_upload_mb} MB."
                    )
                output.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise

    if total == 0:
        destination.unlink(missing_ok=True)
        raise MediaError("Uploaded file is empty.")

    return SavedUpload(
        path=destination,
        original_filename=original_filename,
        size_bytes=total,
        extension=extension,
    )


def prepare_for_transcription(path: Path, settings: Settings) -> PreparedMedia:
    suffix = path.suffix.lower()
    if path.stat().st_size <= settings.audio_chunk_max_bytes and suffix in DIRECT_MEDIA_EXTENSIONS:
        return PreparedMedia(paths=[path])

    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is None:
        raise MediaError(
            "This file needs ffmpeg for audio extraction or chunking. Install ffmpeg on the server."
        )

    cleanup_dir = settings.upload_dir / f"chunks_{uuid.uuid4().hex}"
    cleanup_dir.mkdir(parents=True, exist_ok=True)
    output_pattern = cleanup_dir / "chunk_%03d.mp3"
    command = [
        ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-b:a",
        "48k",
        "-f",
        "segment",
        "-segment_time",
        str(settings.ffmpeg_segment_seconds),
        "-reset_timestamps",
        "1",
        str(output_pattern),
    ]

    completed = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
        timeout=max(300, settings.request_timeout_seconds * 2),
    )
    if completed.returncode != 0:
        shutil.rmtree(cleanup_dir, ignore_errors=True)
        detail = (completed.stderr or "ffmpeg failed").strip()
        raise MediaError(f"Could not extract audio from this file: {detail}")

    chunks = sorted(cleanup_dir.glob("chunk_*.mp3"))
    if not chunks:
        shutil.rmtree(cleanup_dir, ignore_errors=True)
        raise MediaError("No audio track was found in the uploaded file.")

    too_large = [chunk.name for chunk in chunks if chunk.stat().st_size > settings.audio_chunk_max_bytes]
    if too_large:
        shutil.rmtree(cleanup_dir, ignore_errors=True)
        raise MediaError(
            "The converted audio chunks are still too large. Reduce FFMPEG_SEGMENT_SECONDS."
        )

    return PreparedMedia(paths=chunks, cleanup_dir=cleanup_dir)


def cleanup_media(saved_upload: SavedUpload, prepared: PreparedMedia | None, settings: Settings) -> None:
    if prepared and prepared.cleanup_dir:
        shutil.rmtree(prepared.cleanup_dir, ignore_errors=True)
    if not settings.keep_uploads:
        saved_upload.path.unlink(missing_ok=True)
