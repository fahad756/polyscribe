from __future__ import annotations

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
- Do not pretend to process files that have not been uploaded through the app.
"""


class AIServiceError(RuntimeError):
    """Raised when an external AI service cannot complete a request."""


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    chunk_count: int
    source_language: str = ""


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
        try:
            response = self.client.models.generate_content(
                model=self.settings.gemini_model,
                contents=prompt,
            )
        except Exception as exc:
            raise AIServiceError(f"Gemini request failed: {exc}") from exc

        text = _response_text(response)
        if not text:
            raise AIServiceError("Gemini returned an empty response.")
        return text

    def answer_from_transcript(self, prompt: str, transcript: str, filename: str) -> str:
        clean_prompt = prompt.strip()
        if not clean_prompt:
            return f"Transcript: {filename}\n\n{transcript.strip()}"

        instruction = (
            f"{SYSTEM_PROMPT}\n\n"
            "The user uploaded an audio/video file. A dedicated speech-to-text service "
            "has already produced the transcript below. Follow the user's instruction "
            "using this transcript as source material. If the user asks for the direct "
            "transcript, return the transcript text without adding commentary.\n\n"
            f"File: {filename}\n\n"
            f"User instruction:\n{clean_prompt}\n\n"
            f"Transcript:\n{transcript}"
        )
        try:
            response = self.client.models.generate_content(
                model=self.settings.gemini_model,
                contents=instruction,
            )
        except Exception as exc:
            raise AIServiceError(f"Gemini transcript response failed: {exc}") from exc

        text = _response_text(response)
        if not text:
            raise AIServiceError("Gemini returned an empty response.")
        return text


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
        for index, path in enumerate(paths, start=1):
            text = self._transcribe_one(path, prompt=prompt, language=language)
            if len(paths) > 1 and text:
                transcripts.append(f"Part {index}\n{text}")
            else:
                transcripts.append(text)

        text = "\n\n".join(part for part in transcripts if part.strip()).strip()
        if not text:
            raise AIServiceError("No speech was detected in the uploaded media.")
        return TranscriptionResult(
            text=text,
            chunk_count=len(paths),
            source_language=language.strip(),
        )

    def _transcribe_one(self, path: Path, prompt: str = "", language: str = "") -> str:
        kwargs: dict[str, Any] = {
            "model": self.settings.groq_transcription_model,
            "response_format": "json",
            "temperature": 0.0,
        }
        if prompt.strip():
            kwargs["prompt"] = prompt.strip()[:1000]
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

        text = getattr(result, "text", "")
        if isinstance(text, str):
            return text.strip()
        if hasattr(result, "model_dump"):
            dumped = result.model_dump()
            text = dumped.get("text", "")
            return text.strip() if isinstance(text, str) else ""
        return ""


def _render_conversation(messages: list[dict[str, Any]], max_context_chars: int) -> str:
    selected: list[str] = []

    for message in reversed(messages[-30:]):
        role = "Assistant" if message.get("role") == "assistant" else "User"
        content = str(message.get("content") or "").strip()
        metadata = message.get("metadata") or {}
        transcript = str(metadata.get("transcript") or "").strip()
        filename = str(metadata.get("filename") or "uploaded media").strip()
        if transcript:
            content = (
                f"{content}\n\n"
                f"[Transcript context from {filename}; use for follow-up questions]\n"
                f"{transcript}"
            ).strip()
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
