from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from app import db
from app.auth import auth_enabled, make_session_cookie, password_matches, verify_session_cookie
from app.config import ensure_runtime_paths, get_settings
from app.services.ai import AIService, AIServiceError
from app.services.media import MediaError, cleanup_media, prepare_for_transcription, save_upload


BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
logger = logging.getLogger("polyscribe")


class ChatMessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=30000)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    ensure_runtime_paths(settings)
    db.init_db(settings)
    yield


app = FastAPI(title="PolyScribe", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.middleware("http")
async def optional_app_password(request: Request, call_next):
    settings = get_settings()
    path = request.url.path
    public_path = (
        path.startswith("/static/")
        or path in {"/healthz", "/login", "/favicon.ico"}
    )
    if not auth_enabled(settings) or public_path:
        return await call_next(request)

    cookie_value = request.cookies.get("ps_session")
    if verify_session_cookie(settings, cookie_value):
        return await call_next(request)

    if path.startswith("/api/"):
        return JSONResponse({"detail": "Authentication required."}, status_code=401)
    return RedirectResponse("/login", status_code=303)


@app.exception_handler(MediaError)
async def media_error_handler(_: Request, exc: MediaError):
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.exception_handler(AIServiceError)
async def ai_error_handler(_: Request, exc: AIServiceError):
    logger.warning("AI request failed: %s", exc)
    return JSONResponse({"detail": str(exc)}, status_code=503)


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    settings = get_settings()
    if not auth_enabled(settings):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"app_name": settings.app_name, "error": ""},
    )


@app.post("/login")
async def login_submit(request: Request, password: str = Form("")):
    settings = get_settings()
    if not auth_enabled(settings):
        return RedirectResponse("/", status_code=303)
    if not password_matches(settings, password):
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "app_name": settings.app_name,
                "error": "Invalid password.",
            },
            status_code=401,
        )

    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        "ps_session",
        make_session_cookie(settings),
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        max_age=settings.session_max_age_seconds,
    )
    return response


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    settings = get_settings()
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "app_name": settings.app_name,
            "max_upload_mb": settings.max_upload_mb,
            "allowed_extensions": ", ".join(sorted(settings.allowed_extensions)),
        },
    )


@app.get("/api/config")
async def client_config():
    settings = get_settings()
    return {
        "appName": settings.app_name,
        "chatProvider": settings.chat_provider,
        "transcriptionProvider": settings.transcription_provider,
        "maxUploadMb": settings.max_upload_mb,
        "allowedExtensions": sorted(settings.allowed_extensions),
        "authEnabled": auth_enabled(settings),
    }


@app.get("/api/chats")
async def api_list_chats():
    return {"chats": db.list_chats()}


@app.post("/api/chats")
async def api_create_chat():
    return {"chat": db.create_chat()}


@app.get("/api/chats/{chat_id}")
async def api_get_chat(chat_id: str):
    chat = db.get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found.")
    return {"chat": chat, "messages": db.list_messages(chat_id)}


@app.delete("/api/chats/{chat_id}")
async def api_delete_chat(chat_id: str):
    if not db.delete_chat(chat_id):
        raise HTTPException(status_code=404, detail="Chat not found.")
    return {"deleted": True}


@app.post("/api/chats/{chat_id}/messages")
async def api_send_message(chat_id: str, payload: ChatMessageIn):
    chat = db.get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found.")

    content = payload.content.strip()
    db.add_message(chat_id, "user", content, kind="text")
    messages = db.list_messages(chat_id)

    settings = get_settings()
    service = AIService(settings)
    assistant_text = await asyncio.to_thread(service.chat, messages)
    db.add_message(chat_id, "assistant", assistant_text, kind="text")

    return {"chat": db.get_chat(chat_id), "messages": db.list_messages(chat_id)}


@app.post("/api/chats/{chat_id}/uploads")
async def api_upload_media(
    chat_id: str,
    file: UploadFile = File(...),
    prompt: str = Form(""),
    language: str = Form(""),
):
    chat = db.get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found.")

    settings = get_settings()
    saved = await save_upload(file, settings)
    prepared = None

    db.add_message(
        chat_id,
        "user",
        f"Uploaded {saved.original_filename}",
        kind="upload",
        metadata={
            "filename": saved.original_filename,
            "sizeBytes": saved.size_bytes,
            "extension": saved.extension,
        },
    )

    try:
        prepared = await asyncio.to_thread(prepare_for_transcription, saved.path, settings)
        service = AIService(settings)
        result = await asyncio.to_thread(
            service.transcribe_paths,
            prepared.paths,
            prompt,
            language,
        )
    finally:
        cleanup_media(saved, prepared, settings)

    assistant_content = f"Transcript: {saved.original_filename}\n\n{result.text}"
    db.add_message(
        chat_id,
        "assistant",
        assistant_content,
        kind="transcript",
        metadata={
            "filename": saved.original_filename,
            "chunks": result.chunk_count,
            "sourceLanguage": result.source_language or language.strip(),
        },
    )
    return {"chat": db.get_chat(chat_id), "messages": db.list_messages(chat_id)}
