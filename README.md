# PolyScribe

Python-first web app for GPT-style transcription and translation workflows.

## What It Does

- Chat interface with persisted chat sessions.
- Drag-drop or click upload for audio/video files.
- Transcribes supported media through OpenAI speech-to-text models.
- Converts/chunks larger videos with ffmpeg before transcription.
- Lets users ask translation prompts in the same chat after upload.
- Optional shared password gate for private deployments.

The app uses OpenAI's current speech-to-text endpoint for media transcription and the Responses API for chat/translation. OpenAI documents the transcription endpoint as supporting `mp3`, `mp4`, `mpeg`, `mpga`, `m4a`, `wav`, and `webm` uploads up to 25 MB directly; this app uses ffmpeg to handle larger files or formats that need conversion.

## Local Run

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` and set:

```env
OPENAI_API_KEY=sk-your-key
APP_ENV=development
DATABASE_PATH=runtime/polyscribe.db
UPLOAD_DIR=runtime/uploads
```

Run:

```powershell
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`.

## Docker

```bash
cp .env.example .env
docker compose up --build
```

Open `http://localhost:8000`.

## Production Settings

Set these at minimum:

```env
APP_ENV=production
SECRET_KEY=<long-random-secret>
APP_PASSWORD=<optional-shared-password>
OPENAI_API_KEY=<your-openai-key>
DATABASE_PATH=/data/polyscribe.db
UPLOAD_DIR=/data/uploads
KEEP_UPLOADS=false
```

For a public app, set `APP_PASSWORD` or put the service behind real authentication and rate limiting. Public unauthenticated uploads can burn API budget quickly.

## Media Notes

- Direct OpenAI audio upload limit is controlled by `OPENAI_AUDIO_MAX_MB`, default `24`.
- App upload limit is controlled by `MAX_UPLOAD_MB`, default `200`.
- ffmpeg is required for large MP4/video extraction and non-direct formats like `mov`, `mkv`, `flac`, or `ogg`.
- Docker installs ffmpeg automatically.
- Local non-Docker runs need ffmpeg on `PATH` for large/video conversion.

## Verification

```bash
pytest
```

## API Docs Used

- OpenAI speech-to-text guide: https://platform.openai.com/docs/guides/speech-to-text
- OpenAI audio transcription reference: https://platform.openai.com/docs/api-reference/audio/transcribe
- OpenAI Responses API reference: https://platform.openai.com/docs/api-reference/responses

