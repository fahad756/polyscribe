# PolyScribe

Python-first web app for chat-style transcription and translation workflows.

## What It Does

- Chat interface with persisted chat sessions.
- Drag-drop or click upload for audio/video files.
- Transcribes uploads with Groq's online speech-to-text API.
- Uses Gemini only for text chat and translation after the transcript exists.
- Converts/chunks larger videos with ffmpeg before transcription.
- Optional shared password gate for private deployments.

This project intentionally does not send uploaded audio to Gemini for transcription. The audio path uses a dedicated speech-to-text service so the transcript is created first, then Gemini can translate, summarize, or clean it in chat.

## Providers

```env
CHAT_PROVIDER=gemini
TRANSCRIPTION_PROVIDER=groq
```

- Gemini: text chat and translation.
- Groq: audio/video transcription.

No local model or local speech-to-text runtime is required.

## Local Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env`:

```env
GEMINI_API_KEY=<your-gemini-api-key>
GROQ_API_KEY=<your-groq-api-key>
```

Run:

```powershell
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`.

## Deployment

Do not commit `.env`. It is ignored by git. In your hosting provider, add these as private environment variables:

```env
APP_ENV=production
SECRET_KEY=<long-random-secret>
APP_PASSWORD=<optional-shared-password>
CHAT_PROVIDER=gemini
GEMINI_API_KEY=<private-host-env-var>
TRANSCRIPTION_PROVIDER=groq
GROQ_API_KEY=<private-host-env-var>
DATABASE_PATH=/data/polyscribe.db
UPLOAD_DIR=/data/uploads
KEEP_UPLOADS=false
```

For a public portfolio demo, set `APP_PASSWORD` or add platform-level rate limits. Free API limits can still be exhausted by public traffic.

## Docker

```bash
cp .env.example .env
docker compose up --build
```

Open `http://localhost:8000`.

## Media Notes

- App upload limit is controlled by `MAX_UPLOAD_MB`, default `200`.
- Direct/chunk threshold is controlled by `DIRECT_AUDIO_MAX_MB`, default `24`.
- ffmpeg is required for large MP4/video extraction and non-direct formats like `mov`, `mkv`, `flac`, or `ogg`.
- Docker installs ffmpeg automatically.
- Local non-Docker runs need ffmpeg on `PATH` for large/video conversion.

## Verification

```bash
python -m pytest -q
```
