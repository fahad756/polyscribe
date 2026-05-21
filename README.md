# PolyScribe

Python-first web app for chat-style transcription and translation workflows.

## What It Does

- Chat interface with draft-first sessions that are saved after the first prompt.
- Drag-drop or click upload for audio/video files.
- Browser microphone recording that stages captured audio as an attachment.
- Audio/video files stage as composer attachments before sending.
- Admin/demo access gate before the chat UI is available.
- Server-side demo limit of 5 prompts per public IP/network.
- Per-session chat ownership so one visitor cannot see another visitor's chats.
- Transcribes uploads with Groq's online speech-to-text API.
- Uses Gemini only for text chat and translation after the transcript exists.
- Retries temporary Gemini capacity errors and can fall back to a lighter model.
- Converts/chunks larger videos with ffmpeg before transcription.
- Optional shared password gate for private deployments.

This project intentionally does not send uploaded audio to Gemini for transcription. The audio path uses a dedicated speech-to-text service so the transcript is created first, then Gemini can translate, summarize, or clean it in chat.

Upload flow:

1. Attach or drop an audio/video file.
2. Add an optional prompt, such as "give me the transcript" or "translate this to English".
3. Send once. The app transcribes first, then responds according to the prompt.

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
ADMIN_PASSWORD=<your-admin-password>
DEMO_PROMPT_LIMIT=5
GEMINI_API_KEY=<your-gemini-api-key>
GEMINI_FALLBACK_MODELS=gemini-2.5-flash-lite
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
ADMIN_PASSWORD=<private-host-env-var>
DEMO_PROMPT_LIMIT=5
CHAT_PROVIDER=gemini
GEMINI_API_KEY=<private-host-env-var>
GEMINI_FALLBACK_MODELS=gemini-2.5-flash-lite
GEMINI_RETRY_ATTEMPTS=3
GEMINI_RETRY_BASE_DELAY_SECONDS=1
TRANSCRIPTION_PROVIDER=groq
GROQ_API_KEY=<private-host-env-var>
DATABASE_PATH=/data/polyscribe.db
UPLOAD_DIR=/data/uploads
KEEP_UPLOADS=false
STORE_CHAT_MEDIA=true
```

For a public demo, keep `DEMO_PROMPT_LIMIT` low and add platform-level rate limits. Free API limits can still be exhausted by public traffic.

## Render Free Deployment

The repo includes `render.yaml` for a free Render web service that builds from the existing `Dockerfile`. This keeps the Python/FastAPI app and ffmpeg support.

Deploy from the Render dashboard:

1. Click **New +**.
2. Choose **Blueprint**.
3. Connect `https://github.com/fahad756/polyscribe`.
4. Select the `main` branch and apply the detected `render.yaml`.
5. When Render asks for unsynced secret values, add:

```env
ADMIN_PASSWORD=<your-admin-password>
GEMINI_API_KEY=<your-gemini-api-key>
GROQ_API_KEY=<your-groq-api-key>
```

Render generates `SECRET_KEY` automatically from the Blueprint. After deploy, open the `.onrender.com` URL shown by Render.

Render free notes:

- Free services spin down after idle time and wake on the next request.
- The filesystem is ephemeral on free services. SQLite chat history and uploaded files can disappear after redeploys, restarts, or idle spin-downs.
- `STORE_CHAT_MEDIA=true` keeps uploaded audio playable/downloadable in the chat while the free instance filesystem remains available.
- `KEEP_UPLOADS=false` still removes temporary conversion chunks and non-chat upload leftovers.

## Cloudflare Containers Deployment

This app is a Python FastAPI container with ffmpeg, SQLite, uploads, and API clients. Deploy it to Cloudflare as a **Container behind a Worker**, not as a plain Cloudflare Pages site.

Cloudflare requirements:

- Docker Desktop running locally.
- Wrangler CLI login with the Cloudflare account.
- Workers Paid plan for Cloudflare Containers.

Install Worker tooling:

```powershell
npm install
```

Login:

```powershell
npm run cf:login
npm run cf:whoami
```

Set Cloudflare Worker secrets. Do not put these values in git:

```powershell
npx wrangler secret put GEMINI_API_KEY
npx wrangler secret put GROQ_API_KEY
npx wrangler secret put ADMIN_PASSWORD
npx wrangler secret put SECRET_KEY
```

Generate a strong `SECRET_KEY` if needed:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Deploy:

```powershell
npm run deploy
npm run cf:containers
```

After the first deploy, wait a few minutes for the container to provision, then open the `workers.dev` URL printed by Wrangler.

If Wrangler returns `Unauthorized: You do not have access to Cloudflare Containers`, enable the Workers Paid plan for the Cloudflare account, then run `npm run deploy` again.

Cloudflare notes:

- `MAX_UPLOAD_MB` is set to `100` in `wrangler.jsonc` because Cloudflare Free/Pro request body limits are 100 MB.
- The Worker includes a Durable Object demo limiter, so demo prompt limits are enforced before requests reach the container.
- Container filesystem disk is ephemeral when the container sleeps. The app's local SQLite chat history is suitable for a portfolio demo, but long-term durable chat history should be moved to D1, Durable Objects storage, or an external database.

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
