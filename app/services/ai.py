from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import httpx

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

LOCAL_SYSTEM_PROMPT = SYSTEM_PROMPT + """

You are running on a local free model. Keep responses concise and task-focused.
When the user asks for a translation, infer the source language automatically.
"""


class AIServiceError(RuntimeError):
    """Raised when the configured AI provider cannot complete a request."""


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    chunk_count: int
    source_language: str = ""


class AIProvider(Protocol):
    def chat(self, messages: list[dict[str, Any]]) -> str:
        ...

    def transcribe_paths(
        self,
        paths: list[Path],
        prompt: str = "",
        language: str = "",
    ) -> TranscriptionResult:
        ...


class AIService:
    def __init__(self, settings: Settings):
        provider = settings.ai_provider
        if provider in {"local", "free", "ollama"}:
            self._provider: AIProvider = LocalAIProvider(settings)
        elif provider == "gemini":
            self._provider = GeminiProvider(settings)
        elif provider in {"openai", "gpt"}:
            self._provider = OpenAIProvider(settings)
        else:
            raise AIServiceError(
                f"Unsupported AI_PROVIDER '{settings.ai_provider}'. Use 'local', 'gemini', or 'openai'."
            )

    def chat(self, messages: list[dict[str, Any]]) -> str:
        return self._provider.chat(messages)

    def transcribe_paths(
        self,
        paths: list[Path],
        prompt: str = "",
        language: str = "",
    ) -> TranscriptionResult:
        return self._provider.transcribe_paths(paths, prompt, language)


class LocalAIProvider:
    def __init__(self, settings: Settings):
        self.settings = settings

    def chat(self, messages: list[dict[str, Any]]) -> str:
        payload = {
            "model": self.settings.ollama_model,
            "stream": False,
            "messages": _messages_for_ollama(messages, self.settings.max_chat_context_chars),
            "options": {"temperature": 0.2},
        }

        try:
            response = httpx.post(
                f"{self.settings.ollama_base_url}/api/chat",
                json=payload,
                timeout=self.settings.request_timeout_seconds,
            )
            response.raise_for_status()
        except httpx.ConnectError as exc:
            raise AIServiceError(
                "Local chat needs Ollama running. Install Ollama, run "
                f"'ollama pull {self.settings.ollama_model}', then start the app again."
            ) from exc
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text.strip()
            raise AIServiceError(f"Ollama chat failed: {detail}") from exc
        except httpx.HTTPError as exc:
            raise AIServiceError(f"Ollama chat failed: {exc}") from exc

        data = response.json()
        text = (data.get("message") or {}).get("content") or data.get("response") or ""
        text = text.strip()
        if not text:
            raise AIServiceError("Ollama returned an empty response.")
        return text

    def transcribe_paths(
        self,
        paths: list[Path],
        prompt: str = "",
        language: str = "",
    ) -> TranscriptionResult:
        transcripts: list[str] = []
        detected_languages: list[str] = []

        for index, path in enumerate(paths, start=1):
            text, detected_language = self._transcribe_one(
                path=path,
                prompt=prompt,
                language=language,
            )
            if detected_language:
                detected_languages.append(detected_language)
            if len(paths) > 1 and text:
                transcripts.append(f"Part {index}\n{text}")
            else:
                transcripts.append(text)

        text = "\n\n".join(part for part in transcripts if part.strip()).strip()
        if not text:
            raise AIServiceError("No speech was detected in the uploaded media.")

        unique_languages = sorted(set(detected_languages))
        return TranscriptionResult(
            text=text,
            chunk_count=len(paths),
            source_language=", ".join(unique_languages),
        )

    def _transcribe_one(
        self,
        path: Path,
        prompt: str = "",
        language: str = "",
    ) -> tuple[str, str]:
        model = _local_whisper_model(
            self.settings.local_whisper_model,
            self.settings.local_whisper_device,
            self.settings.local_whisper_compute_type,
        )
        try:
            segments, info = model.transcribe(
                str(path),
                language=language.strip() or None,
                initial_prompt=prompt.strip()[:2000] or None,
                vad_filter=True,
            )
            text = "".join(segment.text for segment in segments).strip()
        except Exception as exc:
            raise AIServiceError(f"Local transcription failed: {exc}") from exc

        detected_language = str(getattr(info, "language", "") or "").strip()
        return text, detected_language


class OpenAIProvider:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client: Any | None = None

    @property
    def client(self) -> Any:
        if not self.settings.openai_api_key:
            raise AIServiceError("OPENAI_API_KEY is not configured on the server.")
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise AIServiceError(
                    "OpenAI provider selected, but the openai package is not installed. "
                    "Install it with 'pip install openai'."
                ) from exc

            self._client = OpenAI(
                api_key=self.settings.openai_api_key,
                timeout=self.settings.request_timeout_seconds,
            )
        return self._client

    def chat(self, messages: list[dict[str, Any]]) -> str:
        conversation = _render_conversation(messages, self.settings.max_chat_context_chars)
        try:
            response = self.client.responses.create(
                model=self.settings.openai_text_model,
                instructions=SYSTEM_PROMPT,
                input=conversation,
            )
        except Exception as exc:
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
            text = self._transcribe_one(
                path=path,
                prompt=prompt,
                language=language,
            )
            if len(paths) > 1 and text:
                transcripts.append(f"Part {index}\n{text}")
            else:
                transcripts.append(text)

        text = "\n\n".join(part for part in transcripts if part.strip()).strip()
        if not text:
            raise AIServiceError("No speech was detected in the uploaded media.")
        return TranscriptionResult(text=text, chunk_count=len(paths), source_language=language.strip())

    def _transcribe_one(
        self,
        path: Path,
        prompt: str = "",
        language: str = "",
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

        return _transcription_text(result).strip()


class GeminiProvider:
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
                    "Gemini provider selected, but google-genai is not installed. "
                    "Install dependencies with 'pip install -r requirements.txt'."
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

        text = _generic_response_text(response)
        if not text:
            raise AIServiceError("Gemini returned an empty response.")
        return text

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
        return TranscriptionResult(text=text, chunk_count=len(paths), source_language=language.strip())

    def _transcribe_one(self, path: Path, prompt: str = "", language: str = "") -> str:
        language_instruction = (
            f"The user says the source language may be {language.strip()}. "
            if language.strip()
            else "Detect the source language automatically. "
        )
        user_prompt = (
            "Transcribe this audio or video accurately. "
            f"{language_instruction}"
            "Return only the transcript text. Preserve paragraph breaks when useful."
        )
        if prompt.strip():
            user_prompt += f"\nContext or user instruction: {prompt.strip()[:2000]}"

        uploaded_file = None
        try:
            uploaded_file = self.client.files.upload(file=str(path))
            response = self.client.models.generate_content(
                model=self.settings.gemini_model,
                contents=[user_prompt, uploaded_file],
            )
        except Exception as exc:
            raise AIServiceError(f"Gemini transcription failed: {exc}") from exc
        finally:
            if uploaded_file is not None:
                _delete_gemini_file(self.client, uploaded_file)

        return _generic_response_text(response).strip()


@lru_cache(maxsize=3)
def _local_whisper_model(model_name: str, device: str, compute_type: str) -> Any:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise AIServiceError(
            "Local transcription needs faster-whisper. Install dependencies with "
            "'pip install -r requirements.txt'."
        ) from exc

    try:
        return WhisperModel(model_name, device=device, compute_type=compute_type)
    except Exception as exc:
        raise AIServiceError(f"Could not load local Whisper model '{model_name}': {exc}") from exc


def _messages_for_ollama(
    messages: list[dict[str, Any]],
    max_context_chars: int,
) -> list[dict[str, str]]:
    conversation: list[dict[str, str]] = []
    for message in messages[-30:]:
        role = "assistant" if message.get("role") == "assistant" else "user"
        content = str(message.get("content") or "").strip()
        if content:
            conversation.append({"role": role, "content": content})

    total = len(LOCAL_SYSTEM_PROMPT)
    trimmed: list[dict[str, str]] = []
    for message in reversed(conversation):
        content = message["content"]
        if total + len(content) > max_context_chars:
            remaining = max_context_chars - total
            if remaining > 500:
                trimmed.append({"role": message["role"], "content": content[-remaining:]})
            break
        trimmed.append(message)
        total += len(content)

    return [{"role": "system", "content": LOCAL_SYSTEM_PROMPT}, *reversed(trimmed)]


def _render_conversation(messages: list[dict[str, Any]], max_context_chars: int) -> str:
    selected: list[str] = []

    for message in reversed(messages[-30:]):
        role = "Assistant" if message.get("role") == "assistant" else "User"
        content = str(message.get("content") or "").strip()
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


def _generic_response_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip():
        return text.strip()
    return _response_output_text(response)


def _delete_gemini_file(client: Any, uploaded_file: Any) -> None:
    file_name = getattr(uploaded_file, "name", "") or ""
    if not file_name:
        return
    try:
        client.files.delete(name=file_name)
    except Exception:
        pass


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
