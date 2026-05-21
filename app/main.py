from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from app import db
from app.auth import (
    ACCESS_COOKIE_NAME,
    AccessSession,
    admin_password_matches,
    make_access_cookie,
    read_access_cookie,
)
from app.config import ensure_runtime_paths, get_settings
from app.services.ai import AIService, AIServiceError
from app.services.media import MediaError, cleanup_media, prepare_for_transcription, save_upload


BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
logger = logging.getLogger("polyscribe")


class ChatMessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=30000)


class ChatCreateIn(BaseModel):
    current_chat_id: str | None = Field(default=None, max_length=64)


class AccessStartIn(BaseModel):
    mode: Literal["admin", "demo"]
    password: str = Field(default="", max_length=200)
    name: str = Field(default="", max_length=80)
    remember: bool = False


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    ensure_runtime_paths(settings)
    db.init_db(settings)
    yield


app = FastAPI(title="PolyScribe", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.middleware("http")
async def require_app_access(request: Request, call_next):
    settings = get_settings()
    path = request.url.path
    public_path = (
        path.startswith("/static/")
        or path in {"/", "/healthz", "/login", "/favicon.ico"}
        or path.startswith("/api/access/")
    )
    if public_path:
        return await call_next(request)

    access = read_access_cookie(settings, request.cookies.get(ACCESS_COOKIE_NAME))
    if access is not None:
        request.state.access = access
        return await call_next(request)

    if path.startswith("/api/"):
        return JSONResponse({"detail": "Choose admin or demo access first."}, status_code=401)
    return RedirectResponse("/", status_code=303)


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


def _client_ip(request: Request) -> str:
    cloudflare_ip = request.headers.get("CF-Connecting-IP", "").strip()
    if cloudflare_ip:
        return cloudflare_ip
    forwarded_for = request.headers.get("X-Forwarded-For", "").split(",", 1)[0].strip()
    if forwarded_for:
        return forwarded_for
    return request.client.host if request.client else "unknown"


def _use_secure_cookie(request: Request) -> bool:
    settings = get_settings()
    forwarded_proto = request.headers.get("X-Forwarded-Proto", "").split(",", 1)[0].strip()
    request_is_https = request.url.scheme == "https" or forwarded_proto == "https"
    return settings.secure_cookies and request_is_https


def _demo_usage_key(request: Request) -> str:
    return f"ip:{_client_ip(request)}"


def _access_from_request(request: Request) -> AccessSession:
    access = getattr(request.state, "access", None)
    if access is not None:
        return access
    settings = get_settings()
    access = read_access_cookie(settings, request.cookies.get(ACCESS_COOKIE_NAME))
    if access is None:
        raise HTTPException(status_code=401, detail="Choose admin or demo access first.")
    request.state.access = access
    return access


def _access_payload(request: Request, access: AccessSession | None = None) -> dict[str, object]:
    settings = get_settings()
    access = access or read_access_cookie(settings, request.cookies.get(ACCESS_COOKIE_NAME))
    if access is None:
        return {
            "authenticated": False,
            "role": "",
            "demoLimit": settings.demo_prompt_limit,
            "demoUsed": db.demo_usage(_demo_usage_key(request)),
            "demoRemaining": max(
                settings.demo_prompt_limit - db.demo_usage(_demo_usage_key(request)),
                0,
            ),
        }

    demo_used = db.demo_usage(_demo_usage_key(request)) if access.is_demo else 0
    return {
        "authenticated": True,
        "role": access.role,
        "demoLimit": settings.demo_prompt_limit,
        "demoUsed": demo_used,
        "demoRemaining": max(settings.demo_prompt_limit - demo_used, 0)
        if access.is_demo
        else None,
    }


def _consume_demo_prompt(request: Request, access: AccessSession) -> None:
    if not access.is_demo:
        return
    settings = get_settings()
    usage = db.consume_demo_prompt(_demo_usage_key(request), settings.demo_prompt_limit)
    if not usage["allowed"]:
        raise HTTPException(
            status_code=429,
            detail="Demo limit reached. Contact the admin for further access.",
        )


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return RedirectResponse("/", status_code=303)


@app.post("/login")
async def login_submit(request: Request, password: str = Form("")):
    return RedirectResponse("/", status_code=303)


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
        "authEnabled": True,
        "demoPromptLimit": settings.demo_prompt_limit,
    }


@app.get("/api/access/status")
async def api_access_status(request: Request):
    return {"access": _access_payload(request)}


@app.post("/api/access/start")
async def api_access_start(request: Request, payload: AccessStartIn):
    settings = get_settings()
    if payload.mode == "admin" and not admin_password_matches(settings, payload.password):
        raise HTTPException(status_code=401, detail="Invalid admin password.")
    if payload.mode == "demo" and not payload.name.strip():
        raise HTTPException(status_code=400, detail="Enter your name to start the demo.")

    owner_id = uuid.uuid4().hex
    cookie_value = make_access_cookie(settings, payload.mode, owner_id)
    access = AccessSession(role=payload.mode, owner_id=owner_id, issued_at=0)
    response = JSONResponse({"access": _access_payload(request, access)})
    response.set_cookie(
        ACCESS_COOKIE_NAME,
        cookie_value,
        httponly=True,
        secure=_use_secure_cookie(request),
        samesite="lax",
        max_age=settings.access_remember_max_age_seconds if payload.remember else None,
    )
    return response


@app.post("/api/access/logout")
async def api_access_logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie(ACCESS_COOKIE_NAME)
    return response


@app.get("/api/chats")
async def api_list_chats(request: Request):
    access = _access_from_request(request)
    return {"chats": db.list_chats(access.owner_id), "access": _access_payload(request, access)}


@app.post("/api/chats")
async def api_create_chat(request: Request, payload: ChatCreateIn | None = None):
    access = _access_from_request(request)
    if payload and payload.current_chat_id:
        chat = db.get_chat(payload.current_chat_id, access.owner_id)
        if chat is not None and not db.list_messages(payload.current_chat_id, access.owner_id):
            return {"chat": chat, "access": _access_payload(request, access)}
    return {"chat": db.create_chat(access.owner_id), "access": _access_payload(request, access)}


@app.get("/api/chats/{chat_id}")
async def api_get_chat(request: Request, chat_id: str):
    access = _access_from_request(request)
    chat = db.get_chat(chat_id, access.owner_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found.")
    return {
        "chat": chat,
        "messages": db.list_messages(chat_id, access.owner_id),
        "access": _access_payload(request, access),
    }


@app.delete("/api/chats/{chat_id}")
async def api_delete_chat(request: Request, chat_id: str):
    access = _access_from_request(request)
    if not db.delete_chat(chat_id, access.owner_id):
        raise HTTPException(status_code=404, detail="Chat not found.")
    return {"deleted": True, "access": _access_payload(request, access)}


@app.post("/api/chats/{chat_id}/messages")
async def api_send_message(request: Request, chat_id: str, payload: ChatMessageIn):
    access = _access_from_request(request)
    chat = db.get_chat(chat_id, access.owner_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found.")

    _consume_demo_prompt(request, access)
    content = payload.content.strip()
    db.add_message(chat_id, access.owner_id, "user", content, kind="text")
    messages = db.list_messages(chat_id, access.owner_id)

    settings = get_settings()
    service = AIService(settings)
    assistant_text = await asyncio.to_thread(service.chat, messages)
    db.add_message(chat_id, access.owner_id, "assistant", assistant_text, kind="text")

    return {
        "chat": db.get_chat(chat_id, access.owner_id),
        "messages": db.list_messages(chat_id, access.owner_id),
        "access": _access_payload(request, access),
    }


@app.post("/api/chats/{chat_id}/uploads")
async def api_upload_media(
    request: Request,
    chat_id: str,
    file: UploadFile = File(...),
    prompt: str = Form(""),
    language: str = Form(""),
):
    access = _access_from_request(request)
    chat = db.get_chat(chat_id, access.owner_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found.")

    _consume_demo_prompt(request, access)
    settings = get_settings()
    saved = await save_upload(file, settings)
    prepared = None

    user_content = f"Uploaded {saved.original_filename}"
    if prompt.strip():
        user_content = f"{user_content}\n\n{prompt.strip()}"

    db.add_message(
        chat_id,
        access.owner_id,
        "user",
        user_content,
        kind="upload",
        metadata={
            "filename": saved.original_filename,
            "sizeBytes": saved.size_bytes,
            "extension": saved.extension,
            "prompt": prompt.strip(),
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

    assistant_content = await asyncio.to_thread(
        service.answer_from_transcript,
        prompt,
        result.text,
        saved.original_filename,
    )
    db.add_message(
        chat_id,
        access.owner_id,
        "assistant",
        assistant_content,
        kind="media_response",
        metadata={
            "filename": saved.original_filename,
            "chunks": result.chunk_count,
            "sourceLanguage": result.source_language or language.strip(),
            "transcript": result.text,
            "prompt": prompt.strip(),
        },
    )
    return {
        "chat": db.get_chat(chat_id, access.owner_id),
        "messages": db.list_messages(chat_id, access.owner_id),
        "access": _access_payload(request, access),
    }
