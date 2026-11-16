"""Phase 2 语音输入(voice input):语音转文字(whisper-1)。

前端 `MicButton -> useRecorder` 把 MediaRecorder 录到的音频以 multipart 上传,
这里转发给 Vercel AI Gateway 或直连 OpenAI。密钥只存在于服务端 `.env`,
永远不会出现在浏览器 / Tauri WebView 里。

    POST /api/transcribe   multipart: file=<audio>, language=<可选>
      -> 200 {"text": "..."}
      -> 400 空音频 / 401 密钥无效 / 413 超过 25 MB / 429 限流
      -> 502 上游错误 / 504 超时
"""
import base64

import httpx
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

import config

router = APIRouter(prefix="/api", tags=["voice"])

# whisper-1 硬上限 25 MB;MediaRecorder 32 kbps 约 90 分钟才会到。
MAX_AUDIO_BYTES = 25 * 1024 * 1024
REQUEST_TIMEOUT = 60.0

# AI Gateway 的转写不在 /v1 下的 OpenAI 兼容接口里(那里只有 chat/embeddings,
# /v1/audio/transcriptions 会 404),而是独立的 v4 端点,且只收 JSON + base64。
# 见 https://vercel.com/docs/ai-gateway/modalities/speech-to-text
GATEWAY_TRANSCRIBE_PATH = "/v4/ai/transcription-model"
GATEWAY_PROTOCOL_VERSION = "0.0.1"
GATEWAY_TRANSCRIBE_SPEC_VERSION = "4"


def _provider():
    """返回 (kind, base_url, api_key, model);Gateway 优先,与 Electron 版一致。"""
    if config.AI_GATEWAY_API_KEY:
        return (
            "gateway",
            config.AI_GATEWAY_BASE_URL.rstrip("/"),
            config.AI_GATEWAY_API_KEY,
            config.TRANSCRIBE_MODEL or "openai/whisper-1",
        )
    if config.OPENAI_API_KEY:
        return (
            "openai",
            config.OPENAI_BASE_URL.rstrip("/"),
            config.OPENAI_API_KEY,
            config.TRANSCRIBE_MODEL or "whisper-1",
        )
    return None


def _gateway_root(base_url: str) -> str:
    """v4 端点在根域名下,把默认的 /v1 去掉。"""
    return base_url[: -len("/v1")] if base_url.endswith("/v1") else base_url


@router.get("/transcribe/status")
def transcribe_status():
    """给前端判断：服务端是否配置了转写能力（浏览器识别兜底用）。"""
    provider = _provider()
    if provider is None:
        return {"configured": False, "provider": None, "model": None,
                "hint": "未配置转写密钥，前端可回退浏览器语音识别。"}
    kind, _base, _key, model = provider
    return {"configured": True, "provider": kind, "model": model, "hint": ""}


@router.post("/transcribe")
async def transcribe(file: UploadFile = File(...), language: str | None = Form(None)):
    provider = _provider()
    if provider is None:
        raise HTTPException(
            status_code=503,
            detail="未配置 AI_GATEWAY_API_KEY 或 OPENAI_API_KEY(见 .env.example)",
        )
    kind, base_url, api_key, model = provider

    audio = await file.read()
    if not audio:
        raise HTTPException(status_code=400, detail="没有收到音频数据")
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="录音超过 25 MB 上限,请缩短录音")

    # MediaRecorder 给的是 "audio/webm;codecs=opus",Gateway 只认裸 MIME,带参数会 400。
    media_type = (file.content_type or "audio/webm").split(";")[0].strip()
    form = {"model": model}
    lang = (language or config.TRANSCRIBE_LANGUAGE or "").strip()
    if lang:
        form["language"] = lang
    if config.TRANSCRIBE_PROMPT:
        form["prompt"] = config.TRANSCRIBE_PROMPT

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            if kind == "gateway":
                # Gateway 只接受 JSON + base64,不支持 multipart。
                response = await client.post(
                    f"{_gateway_root(base_url)}{GATEWAY_TRANSCRIBE_PATH}",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "ai-gateway-protocol-version": GATEWAY_PROTOCOL_VERSION,
                        "ai-transcription-model-specification-version": GATEWAY_TRANSCRIBE_SPEC_VERSION,
                        "ai-model-id": model,
                    },
                    json={
                        "audio": base64.b64encode(audio).decode("ascii"),
                        "mediaType": media_type,
                    },
                )
            else:
                response = await client.post(
                    f"{base_url}/audio/transcriptions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    files={
                        "file": (
                            file.filename or "audio.webm",
                            audio,
                            media_type,
                        )
                    },
                    data=form,
                )
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="转写超时,请重试") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"无法连接转写服务:{exc}") from exc

    if response.status_code == 402:
        raise HTTPException(
            status_code=402,
            detail="转写额度已用尽（AI Gateway: budget exceeded）。已自动启用浏览器语音识别兜底：请再点一次麦克风，用 Chrome/Edge 录音即可；或给 .env 配置 OPENAI_API_KEY 恢复服务端转写。",
        )
    if response.status_code in (401, 403):
        raise HTTPException(status_code=401, detail="转写服务密钥无效,请检查 .env 的 AI_GATEWAY_API_KEY")
    if response.status_code == 413:
        raise HTTPException(status_code=413, detail="录音超过 25 MB 上限,请缩短录音")
    if response.status_code == 429:
        raise HTTPException(status_code=429, detail="转写请求过于频繁,请稍后重试")
    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=f"转写失败({response.status_code}):{response.text[:200]}",
        )

    try:
        text = (response.json().get("text") or "").strip()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="转写服务返回了非 JSON 响应") from exc
    if not text:
        raise HTTPException(status_code=422, detail="没有识别出文字,请再试一次")
    return {"text": text}
