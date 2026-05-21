from __future__ import annotations

import random
import re
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import Settings


SYSTEM_PROMPT = """You are PolyScribe, a focused transcription and translation assistant.

Core behavior:
- Translate between any languages when the user asks for translation.
- Preserve meaning, tone, names, numbers, formatting, and paragraph breaks.
- If the source language is not named, infer it.
- If the target language is missing, ask one concise clarifying question.
- If the user asks about uploaded media, use the transcript already present in the conversation.
- Treat transcript context as authoritative. Do not invent details that are not in the transcript.
- If the answer is not supported by the transcript, say the transcript does not contain enough information.
- Do not pretend to process files that have not been uploaded through the app.
"""

RETRYABLE_GEMINI_MARKERS = (
    "429",
    "500",
    "503",
    "504",
    "capacity",
    "deadline",
    "high demand",
    "internal",
    "overloaded",
    "rate limit",
    "resource_exhausted",
    "temporarily",
    "timeout",
    "unavailable",
)


class AIServiceError(RuntimeError):
    """Raised when an external AI service cannot complete a request."""


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    chunk_count: int
    source_language: str = ""


@dataclass(frozen=True)
class TranscribedPart:
    text: str
    language: str = ""
    suspicious: bool = False
    reason: str = ""


class AIService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._chat_provider = GeminiChatProvider(settings)
        self._transcription_provider = GroqTranscriptionProvider(settings)

        if settings.chat_provider != "gemini":
            raise AIServiceError("CHAT_PROVIDER must be 'gemini'.")
        if settings.transcription_provider != "groq":
            raise AIServiceError("TRANSCRIPTION_PROVIDER must be 'groq'.")

    def chat(self, messages: list[dict[str, Any]]) -> str:
        return self._chat_provider.chat(messages)

    def answer_from_transcript(
        self,
        prompt: str,
        transcript: str,
        filename: str,
    ) -> str:
        return self._chat_provider.answer_from_transcript(prompt, transcript, filename)

    def transcribe_paths(
        self,
        paths: list[Path],
        prompt: str = "",
        language: str = "",
    ) -> TranscriptionResult:
        return self._transcription_provider.transcribe_paths(paths, prompt, language)


class GeminiChatProvider:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client: Any | None = None

    @property
    def client(self) -> Any:
        if not self.settings.gemini_api_key:
            raise AIServiceError("GEMINI_API_KEY is not configured on the server.")
        if self._client is None:
            try:
                from google import genai
            except ImportError as exc:
                raise AIServiceError(
                    "Gemini chat needs google-genai. Install dependencies with "
                    "'pip install -r requirements.txt'."
                ) from exc

            self._client = genai.Client(api_key=self.settings.gemini_api_key)
        return self._client

    def chat(self, messages: list[dict[str, Any]]) -> str:
        prompt = (
            f"{SYSTEM_PROMPT}\n\n"
            "Continue this conversation. Answer only the latest user request.\n\n"
            f"{_render_conversation(messages, self.settings.max_chat_context_chars)}"
        )
        response = self._generate_content(prompt, "Gemini request failed")

        text = _response_text(response)
        if not text:
            raise AIServiceError("Gemini returned an empty response.")
        return text

    def answer_from_transcript(self, prompt: str, transcript: str, filename: str) -> str:
        clean_prompt = prompt.strip()
        if not clean_prompt:
            return f"Transcript: {filename}\n\n{transcript.strip()}"
        if _is_direct_transcript_request(clean_prompt):
            return transcript.strip()

        instruction = (
            f"{SYSTEM_PROMPT}\n\n"
            "The user uploaded an audio/video file. A dedicated speech-to-text service "
            "has already produced the transcript below. Follow the user's instruction "
            "using this transcript as source material. If the user asks for the direct "
            "transcript, return the transcript text without adding commentary. Do not "
            "invent details that are not supported by the transcript.\n\n"
            f"File: {filename}\n\n"
            f"User instruction:\n{clean_prompt}\n\n"
            f"Transcript:\n{transcript}"
        )
        response = self._generate_content(
            instruction,
            "Gemini transcript response failed",
        )

        text = _response_text(response)
        if not text:
            raise AIServiceError("Gemini returned an empty response.")
        return text

    def _generate_content(self, contents: str, failure_message: str) -> Any:
        last_error: Exception | None = None
        models = self._model_sequence()
        attempts = max(self.settings.gemini_retry_attempts, 1)

        for model in models:
            for attempt in range(1, attempts + 1):
                try:
                    return self.client.models.generate_content(
                        model=model,
                        contents=contents,
                    )
                except Exception as exc:
                    last_error = exc
                    if not _is_retryable_gemini_error(exc):
                        raise AIServiceError(f"{failure_message}: {exc}") from exc
                    if attempt < attempts:
                        time.sleep(self._retry_delay(attempt))

        if last_error is None:
            raise AIServiceError(f"{failure_message}: no Gemini model configured.")
        raise AIServiceError(
            f"{failure_message} after retries: {last_error}"
        ) from last_error

    def _model_sequence(self) -> tuple[str, ...]:
        models: list[str] = []
        for model in (self.settings.gemini_model, *self.settings.gemini_fallback_models):
            model = model.strip()
            if model and model not in models:
                models.append(model)
        return tuple(models or ["gemini-2.5-flash"])

    def _retry_delay(self, attempt: int) -> float:
        base = self.settings.gemini_retry_base_delay_seconds
        if base <= 0:
            return 0.0
        delay = min(base * (2 ** (attempt - 1)), 8.0)
        return delay + random.uniform(0, min(base, 1.0))


class GroqTranscriptionProvider:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client: Any | None = None

    @property
    def client(self) -> Any:
        if not self.settings.groq_api_key:
            raise AIServiceError("GROQ_API_KEY is not configured on the server.")
        if self._client is None:
            try:
                from groq import Groq
            except ImportError as exc:
                raise AIServiceError(
                    "Groq transcription needs groq. Install dependencies with "
                    "'pip install -r requirements.txt'."
                ) from exc

            self._client = Groq(api_key=self.settings.groq_api_key)
        return self._client

    def transcribe_paths(
        self,
        paths: list[Path],
        prompt: str = "",
        language: str = "",
    ) -> TranscriptionResult:
        transcripts: list[str] = []
        languages: list[str] = []
        for index, path in enumerate(paths, start=1):
            part = self._transcribe_with_fallback(path, language=language)
            text = part.text
            if len(paths) > 1 and text:
                transcripts.append(f"Part {index}\n{text}")
            else:
                transcripts.append(text)
            if part.language and part.language not in languages:
                languages.append(part.language)

        text = "\n\n".join(part for part in transcripts if part.strip()).strip()
        if not text:
            raise AIServiceError("No speech was detected in the uploaded media.")
        return TranscriptionResult(
            text=text,
            chunk_count=len(paths),
            source_language=", ".join(languages) or language.strip(),
        )

    def _transcribe_with_fallback(self, path: Path, language: str = "") -> TranscribedPart:
        best_part: TranscribedPart | None = None
        for model in self._model_sequence():
            part = self._transcribe_one(path, model=model, language=language)
            if not part.suspicious:
                return part
            if best_part is None or len(part.text) > len(best_part.text):
                best_part = part

        if best_part is None:
            raise AIServiceError("No speech was detected in the uploaded media.")
        raise AIServiceError(
            "The audio was detected, but the transcript was not reliable enough to show. "
            "Please record again closer to the microphone, reduce background noise, or upload a clearer file."
        )

    def _model_sequence(self) -> tuple[str, ...]:
        models: list[str] = []
        for model in (
            self.settings.groq_transcription_model,
            *self.settings.groq_transcription_fallback_models,
        ):
            clean = model.strip()
            if clean and clean not in models:
                models.append(clean)
        if "whisper-large-v3" not in models:
            models.append("whisper-large-v3")
        return tuple(models)

    def _transcribe_one(self, path: Path, model: str, language: str = "") -> TranscribedPart:
        kwargs: dict[str, Any] = {
            "model": model,
            "response_format": "verbose_json",
            "temperature": 0.0,
        }
        if language.strip():
            kwargs["language"] = language.strip()

        try:
            with path.open("rb") as handle:
                result = self.client.audio.transcriptions.create(
                    file=(path.name, handle),
                    **kwargs,
                )
        except Exception as exc:
            raise AIServiceError(f"Groq transcription failed: {exc}") from exc

        if hasattr(result, "model_dump"):
            dumped = result.model_dump()
        elif isinstance(result, dict):
            dumped = result
        else:
            dumped = {}

        text = getattr(result, "text", "") if not dumped else dumped.get("text", "")
        detected_language = (
            getattr(result, "language", "") if not dumped else dumped.get("language", "")
        )
        clean_text = text.strip() if isinstance(text, str) else ""
        suspicious, reason = _suspicious_transcript(clean_text, dumped)
        return TranscribedPart(
            text=clean_text,
            language=detected_language.strip() if isinstance(detected_language, str) else "",
            suspicious=suspicious,
            reason=reason,
        )


def _is_retryable_gemini_error(exc: Exception) -> bool:
    parts = [str(exc)]
    for attr in ("code", "status", "status_code"):
        value = getattr(exc, attr, None)
        if value is not None:
            parts.append(str(value))
    text = " ".join(parts).lower()
    return any(marker in text for marker in RETRYABLE_GEMINI_MARKERS)


def _suspicious_transcript(text: str, response_data: dict[str, Any]) -> tuple[bool, str]:
    clean = " ".join(text.split())
    if not clean:
        return True, "empty"

    tokens = re.findall(r"[\w']+", clean.lower(), flags=re.UNICODE)
    if len(tokens) >= 6:
        counts = Counter(tokens)
        _, repeated_count = counts.most_common(1)[0]
        unique_ratio = len(counts) / len(tokens)
        if repeated_count >= 5 and repeated_count / len(tokens) >= 0.45:
            return True, "repeated words"
        if len(tokens) >= 10 and unique_ratio <= 0.28:
            return True, "low vocabulary"

    repeated_phrase = re.search(
        r"\b(.{2,24}?)(?:\s+\1\b){3,}",
        clean,
        flags=re.IGNORECASE,
    )
    if repeated_phrase:
        return True, "repeated phrase"

    segments = response_data.get("segments") if isinstance(response_data, dict) else None
    if isinstance(segments, list) and segments:
        low_confidence = 0
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            avg_logprob = _float_or_none(segment.get("avg_logprob"))
            compression_ratio = _float_or_none(segment.get("compression_ratio"))
            no_speech_prob = _float_or_none(segment.get("no_speech_prob"))
            if no_speech_prob is not None and no_speech_prob >= 0.72:
                low_confidence += 1
            elif avg_logprob is not None and avg_logprob <= -1.15:
                low_confidence += 1
            elif compression_ratio is not None and compression_ratio >= 2.4:
                low_confidence += 1
        if low_confidence and low_confidence >= max(1, len(segments) // 2):
            return True, "low confidence"

    return False, ""


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_direct_transcript_request(prompt: str) -> bool:
    text = " ".join(prompt.lower().split())
    direct_terms = (
        "direct transcript",
        "full transcript",
        "give me transcript",
        "give me the transcript",
        "i want transcript",
        "i want the transcript",
        "speech to text",
        "speech-to-text",
        "transcribe",
        "transcript",
        "transcription",
        "write it out",
        "write out",
    )
    transform_terms = (
        "bullet",
        "clean",
        "convert",
        "explain",
        "fix",
        "format",
        "grammar",
        "key point",
        "rewrite",
        "summar",
        "translate",
    )
    return (
        any(term in text for term in direct_terms)
        and not any(term in text for term in transform_terms)
    )


def _render_conversation(messages: list[dict[str, Any]], max_context_chars: int) -> str:
    selected: list[str] = []

    for message in reversed(messages[-30:]):
        role = "Assistant" if message.get("role") == "assistant" else "User"
        content = str(message.get("content") or "").strip()
        metadata = message.get("metadata") or {}
        transcript = str(metadata.get("transcript") or "").strip()
        filename = str(metadata.get("filename") or "uploaded media").strip()
        if transcript:
            transcript_context = (
                f"[Authoritative transcript from {filename}. Use this for follow-up "
                f"questions about the uploaded media. Do not invent missing details.]\n"
                f"{transcript}"
            )
            if message.get("kind") == "media_response":
                content = transcript_context
            else:
                content = f"{content}\n\n{transcript_context}".strip()
        if not content:
            continue

        rendered = f"{role}:\n{content}"
        if len(rendered) > max_context_chars:
            rendered = rendered[-max_context_chars:]
        if len(rendered) + sum(len(item) for item in selected) > max_context_chars:
            remaining = max_context_chars - sum(len(item) for item in selected)
            if remaining > 500:
                selected.append(rendered[-remaining:])
            break
        selected.append(rendered)

    return "\n\n".join(reversed(selected))


def _response_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip():
        return text.strip()

    if hasattr(response, "model_dump"):
        data = response.model_dump()
    elif isinstance(response, dict):
        data = response
    else:
        return ""

    text_parts: list[str] = []
    for candidate in data.get("candidates", []) or []:
        content = candidate.get("content") or {}
        for part in content.get("parts", []) or []:
            part_text = part.get("text")
            if isinstance(part_text, str):
                text_parts.append(part_text)
    return "\n".join(text_parts).strip()
