import { Container, getContainer } from "@cloudflare/containers";
import { env as cloudflareEnv } from "cloudflare:workers";

type WorkerEnv = {
  POLYSCRIBE_CONTAINER: DurableObjectNamespace<PolyScribeContainer>;
  DEMO_LIMITER: DurableObjectNamespace;
  APP_NAME?: string;
  APP_ENV?: string;
  CHAT_PROVIDER?: string;
  TRANSCRIPTION_PROVIDER?: string;
  GEMINI_API_KEY?: string;
  GEMINI_MODEL?: string;
  GEMINI_FALLBACK_MODELS?: string;
  GEMINI_RETRY_ATTEMPTS?: string;
  GEMINI_RETRY_BASE_DELAY_SECONDS?: string;
  GROQ_API_KEY?: string;
  GROQ_TRANSCRIPTION_MODEL?: string;
  DATABASE_PATH?: string;
  UPLOAD_DIR?: string;
  MAX_UPLOAD_MB?: string;
  DIRECT_AUDIO_MAX_MB?: string;
  KEEP_UPLOADS?: string;
  STORE_CHAT_MEDIA?: string;
  FFMPEG_SEGMENT_SECONDS?: string;
  REQUEST_TIMEOUT_SECONDS?: string;
  MAX_CHAT_CONTEXT_CHARS?: string;
  ADMIN_PASSWORD?: string;
  DEMO_PROMPT_LIMIT?: string;
  ACCESS_REMEMBER_MAX_AGE_SECONDS?: string;
  SECRET_KEY?: string;
  WEB_CONCURRENCY?: string;
  PORT?: string;
};

const cfEnv = cloudflareEnv as unknown as WorkerEnv;
const CONTAINER_NAME = "polyscribe-production";
const PROMPT_PATH_PATTERN = /^\/api\/chats\/[^/]+\/(messages|uploads)$/;

export class PolyScribeContainer extends Container {
  defaultPort = 8000;
  sleepAfter = "2h";

  envVars = {
    APP_NAME: cfEnv.APP_NAME ?? "PolyScribe",
    APP_ENV: cfEnv.APP_ENV ?? "production",
    CHAT_PROVIDER: cfEnv.CHAT_PROVIDER ?? "gemini",
    TRANSCRIPTION_PROVIDER: cfEnv.TRANSCRIPTION_PROVIDER ?? "groq",
    GEMINI_API_KEY: cfEnv.GEMINI_API_KEY ?? "",
    GEMINI_MODEL: cfEnv.GEMINI_MODEL ?? "gemini-2.5-flash",
    GEMINI_FALLBACK_MODELS: cfEnv.GEMINI_FALLBACK_MODELS ?? "gemini-2.5-flash-lite",
    GEMINI_RETRY_ATTEMPTS: cfEnv.GEMINI_RETRY_ATTEMPTS ?? "3",
    GEMINI_RETRY_BASE_DELAY_SECONDS: cfEnv.GEMINI_RETRY_BASE_DELAY_SECONDS ?? "1",
    GROQ_API_KEY: cfEnv.GROQ_API_KEY ?? "",
    GROQ_TRANSCRIPTION_MODEL: cfEnv.GROQ_TRANSCRIPTION_MODEL ?? "whisper-large-v3-turbo",
    DATABASE_PATH: cfEnv.DATABASE_PATH ?? "/data/polyscribe.db",
    UPLOAD_DIR: cfEnv.UPLOAD_DIR ?? "/data/uploads",
    MAX_UPLOAD_MB: cfEnv.MAX_UPLOAD_MB ?? "100",
    DIRECT_AUDIO_MAX_MB: cfEnv.DIRECT_AUDIO_MAX_MB ?? "24",
    KEEP_UPLOADS: cfEnv.KEEP_UPLOADS ?? "false",
    STORE_CHAT_MEDIA: cfEnv.STORE_CHAT_MEDIA ?? "true",
    FFMPEG_SEGMENT_SECONDS: cfEnv.FFMPEG_SEGMENT_SECONDS ?? "1200",
    REQUEST_TIMEOUT_SECONDS: cfEnv.REQUEST_TIMEOUT_SECONDS ?? "180",
    MAX_CHAT_CONTEXT_CHARS: cfEnv.MAX_CHAT_CONTEXT_CHARS ?? "60000",
    ADMIN_PASSWORD: cfEnv.ADMIN_PASSWORD ?? "",
    DEMO_PROMPT_LIMIT: cfEnv.DEMO_PROMPT_LIMIT ?? "5",
    ACCESS_REMEMBER_MAX_AGE_SECONDS: cfEnv.ACCESS_REMEMBER_MAX_AGE_SECONDS ?? "2592000",
    SECRET_KEY: cfEnv.SECRET_KEY ?? "change-me-for-production",
    WEB_CONCURRENCY: cfEnv.WEB_CONCURRENCY ?? "1",
    PORT: cfEnv.PORT ?? "8000",
  };
}

export class DemoLimiter {
  constructor(
    private readonly state: DurableObjectState,
    private readonly env: WorkerEnv,
  ) {}

  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);
    const limit = Math.max(Number(url.searchParams.get("limit") || this.env.DEMO_PROMPT_LIMIT || 5), 0);
    const used = (await this.state.storage.get<number>("prompt_count")) ?? 0;

    if (used >= limit) {
      return Response.json(
        {
          detail: "Demo limit reached. Contact the admin for further access.",
          used,
          remaining: 0,
          limit,
        },
        { status: 429 },
      );
    }

    const nextUsed = used + 1;
    await this.state.storage.put("prompt_count", nextUsed);
    return Response.json({
      allowed: true,
      used: nextUsed,
      remaining: Math.max(limit - nextUsed, 0),
      limit,
    });
  }
}

export default {
  async fetch(request: Request, env: WorkerEnv): Promise<Response> {
    if (shouldApplyDemoLimit(request)) {
      const ip = clientIp(request);
      const limiterId = env.DEMO_LIMITER.idFromName(ip);
      const limiter = env.DEMO_LIMITER.get(limiterId);
      const limitResponse = await limiter.fetch(
        `https://limiter/check?limit=${encodeURIComponent(env.DEMO_PROMPT_LIMIT || "5")}`,
        { method: "POST" },
      );

      if (!limitResponse.ok) {
        return limitResponse;
      }
    }

    const container = getContainer(env.POLYSCRIBE_CONTAINER, CONTAINER_NAME);
    return container.fetch(request);
  },
};

function shouldApplyDemoLimit(request: Request): boolean {
  if (request.method !== "POST") return false;
  const url = new URL(request.url);
  if (!PROMPT_PATH_PATTERN.test(url.pathname)) return false;
  return accessRoleFromCookie(request.headers.get("Cookie") || "") === "demo";
}

function clientIp(request: Request): string {
  return (
    request.headers.get("CF-Connecting-IP") ||
    request.headers.get("X-Forwarded-For")?.split(",", 1)[0]?.trim() ||
    "unknown"
  );
}

function accessRoleFromCookie(cookieHeader: string): string {
  const cookie = cookieHeader
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith("ps_access="));
  if (!cookie) return "";

  const rawValue = cookie.slice("ps_access=".length).replace(/^"|"$/g, "");
  try {
    const decoded = decodeBase64Url(rawValue);
    const [prefix, role] = decoded.split(":", 3);
    return prefix === "access" ? role : "";
  } catch {
    return "";
  }
}

function decodeBase64Url(value: string): string {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "=");
  return atob(padded);
}
