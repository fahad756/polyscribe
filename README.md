# PolyScribe

Python-first web app for GPT-style transcription and translation workflows.

## What It Does

- Chat interface with persisted chat sessions.
- Drag-drop or click upload for audio/video files.
- Free local transcription with `faster-whisper` by default.
- Automatic source-language detection when transcribing.
- Free local prompt/chat translation through Ollama by default.
- Online Gemini provider for hosted portfolio demos.
- Converts/chunks larger videos with ffmpeg before transcription.
- Optional shared password gate for private deployments.
- Optional OpenAI fallback if you set `AI_PROVIDER=openai`.

## Online Portfolio Setup

Use Gemini when you deploy the app somewhere and want it to work live without running Ollama or Whisper on the server.

```env
AI_PROVIDER=gemini
GEMINI_API_KEY=<your-gemini-api-key>
GEMINI_MODEL=gemini-2.5-flash
```

Do not commit `.env`. It is already ignored by git. Set `GEMINI_API_KEY` in your hosting provider's private environment variables for deployment.

## Free Local Setup

The local provider does not need an OpenAI or Gemini key.

Install Python dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Install Ollama, then pull a free local model:

```powershell
ollama pull llama3.2:3b
```

Run the app:

```powershell
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`.

The first transcription downloads the configured Whisper model. After that, it stays local.

## Local Provider Settings

```env
AI_PROVIDER=local
LOCAL_WHISPER_MODEL=base
LOCAL_WHISPER_DEVICE=cpu
LOCAL_WHISPER_COMPUTE_TYPE=int8
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=llama3.2:3b
```

Source language is optional. Leave the UI language hint empty and Whisper will detect it automatically.

For better transcription quality, change `LOCAL_WHISPER_MODEL` to `small`, `medium`, or `large-v3`. Larger models are slower and need more RAM.

## Optional OpenAI Provider

OpenAI is no longer required. To use it anyway:

```powershell
pip install openai
```

Then set:

```env
AI_PROVIDER=openai
OPENAI_API_KEY=sk-your-key
OPENAI_TEXT_MODEL=gpt-5-mini
OPENAI_TRANSCRIPTION_MODEL=gpt-4o-mini-transcribe
```

## Docker

```bash
cp .env.example .env
docker compose up --build
```

If Ollama is running on the host machine and the app is in Docker, set:

```env
OLLAMA_BASE_URL=http://host.docker.internal:11434
```

Open `http://localhost:8000`.

## Production Settings

Set these at minimum:

```env
APP_ENV=production
SECRET_KEY=<long-random-secret>
APP_PASSWORD=<optional-shared-password>
AI_PROVIDER=gemini
GEMINI_API_KEY=<private-host-env-var>
DATABASE_PATH=/data/polyscribe.db
UPLOAD_DIR=/data/uploads
KEEP_UPLOADS=false
```

For a public app, set `APP_PASSWORD` or put the service behind real authentication and rate limiting. Public unauthenticated uploads can still burn CPU/GPU and disk resources.

## Media Notes

- App upload limit is controlled by `MAX_UPLOAD_MB`, default `200`.
- Direct media pass-through/chunk threshold is controlled by `DIRECT_AUDIO_MAX_MB`, default `24`.
- ffmpeg is required for large MP4/video extraction and non-direct formats like `mov`, `mkv`, `flac`, or `ogg`.
- Docker installs ffmpeg automatically.
- Local non-Docker runs need ffmpeg on `PATH` for large/video conversion.

## Verification

```bash
python -m pytest -q
```
