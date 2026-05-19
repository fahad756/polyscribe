from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openai import OpenAI

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
    """Raised when the model provider cannot complete a request."""


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    chunk_count: int


class AIService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client: OpenAI | None = None

    @property
    def client(self) -> OpenAI:
        if not self.settings.openai_api_key:
            raise AIServiceError("OPENAI_API_KEY is not configured on the server.")
        if self._client is None:
            self._client = OpenAI(
                api_key=self.settings.openai_api_key,
                timeout=self.settings.request_timeout_seconds,
            )
        return self._client

    def chat(self, messages: list[dict[str, Any]]) -> str:
        conversation = self._render_conversation(messages)
        try:
            response = self.client.responses.create(
                model=self.settings.openai_text_model,
                instructions=SYSTEM_PROMPT,
                input=conversation,
            )
        except Exception as exc:  # The SDK raises provider-specific subclasses.
            raise AIServiceError(f"Model request failed: {exc}") from exc

        text = _response_output_text(response)
        if not text:
            raise AIServiceError("The model returned an empty response.")
        return text

    def transcribe_paths(
        self,
        paths: list[Path],
        prompt: str = "",
        language: str = "",
    ) -> TranscriptionResult:
        transcripts: list[str] = []
        for index, path in enumerate(paths, start=1):
            transcripts.append(
                self._transcribe_one(
                    path=path,
                    prompt=prompt,
                    language=language,
                    chunk_label=f"Part {index}" if len(paths) > 1 else "",
                )
            )

        text = "\n\n".join(part for part in transcripts if part.strip()).strip()
        if not text:
            raise AIServiceError("No speech was detected in the uploaded media.")
        return TranscriptionResult(text=text, chunk_count=len(paths))

    def _transcribe_one(
        self,
        path: Path,
        prompt: str = "",
        language: str = "",
        chunk_label: str = "",
    ) -> str:
        base_kwargs: dict[str, Any] = {
            "model": self.settings.openai_transcription_model,
        }
        optional_kwargs: dict[str, Any] = {}
        if prompt.strip():
            optional_kwargs["prompt"] = prompt.strip()[:2000]
        if language.strip():
            optional_kwargs["language"] = language.strip()

        try:
            with path.open("rb") as handle:
                result = self.client.audio.transcriptions.create(
                    file=handle,
                    **base_kwargs,
                    **optional_kwargs,
                )
        except Exception as first_exc:
            if not optional_kwargs:
                raise AIServiceError(f"Transcription failed: {first_exc}") from first_exc
            try:
                with path.open("rb") as handle:
                    result = self.client.audio.transcriptions.create(
                        file=handle,
                        **base_kwargs,
                    )
            except Exception as second_exc:
                raise AIServiceError(f"Transcription failed: {second_exc}") from second_exc

        text = _transcription_text(result).strip()
        if chunk_label and text:
            return f"{chunk_label}\n{text}"
        return text

    def _render_conversation(self, messages: list[dict[str, Any]]) -> str:
        budget = self.settings.max_chat_context_chars
        selected: list[str] = []

        for message in reversed(messages[-30:]):
            role = "Assistant" if message.get("role") == "assistant" else "User"
            content = str(message.get("content") or "").strip()
            if not content:
                continue

            rendered = f"{role}:\n{content}"
            if len(rendered) > budget:
                rendered = rendered[-budget:]
            if len(rendered) + sum(len(item) for item in selected) > budget:
                remaining = budget - sum(len(item) for item in selected)
                if remaining > 500:
                    selected.append(rendered[-remaining:])
                break
            selected.append(rendered)

        return "\n\n".join(reversed(selected))


def _response_output_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    if hasattr(response, "model_dump"):
        data = response.model_dump()
    elif isinstance(response, dict):
        data = response
    else:
        return ""

    text_parts: list[str] = []
    for item in data.get("output", []) or []:
        for content in item.get("content", []) or []:
            text = content.get("text")
            if isinstance(text, str):
                text_parts.append(text)
    return "\n".join(text_parts).strip()


def _transcription_text(result: Any) -> str:
    text = getattr(result, "text", None)
    if isinstance(text, str):
        return text
    if hasattr(result, "model_dump"):
        text = result.model_dump().get("text")
        return text if isinstance(text, str) else ""
    if isinstance(result, dict):
        text = result.get("text")
        return text if isinstance(text, str) else ""
    return ""

