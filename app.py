"""Filmmate 后端入口:FastAPI + SSE 流式输出。

聊天事件（React 使用 UIMessageStream，旧界面使用以下 SSE 事件）:
  start      {tool, label, mode}          会话开始,说明走哪个工具/模式
  steps      {steps}                      模型自主调用的检索工具过程(Agent 可视化)
  citations  {kind, items}                知识库/案例库引用
  delta      {text}                       流式文本增量
  tool_data  {tool, payload}              结构化工具结果(审阅报告/分镜/rundown/日程/案例)
  done       {}                           结束
  error      {message}                    错误
"""
import asyncio
import json
import logging
import re
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

import case_store
import chat_storage_api
import config
import llm
import library
import personal_api
import prompts
import rag
import sample_search
import script_api
import tools
import voice_input_api

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("app")

@asynccontextmanager
async def lifespan(_app):
    await asyncio.to_thread(sample_search.prepare_index)
    yield


app = FastAPI(title="Filmmate 影视创作助理", lifespan=lifespan)
STATIC_DIR = config.BASE_DIR / "static"
WEB_DIST = config.BASE_DIR / "filmmate-web" / "dist"

# 前端跑在 Vite(5173) 或 Tauri WebView(tauri://localhost),都算跨源。
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "tauri://localhost",
        "http://tauri.localhost",
        "https://tauri.localhost",
    ],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(voice_input_api.router)
app.include_router(chat_storage_api.router)
app.include_router(script_api.router)
app.include_router(personal_api.router)


def legacy_event(event, data):
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def ui_chunk(kind, **fields):
    return f"data: {json.dumps(dict(type=kind, **fields), ensure_ascii=False)}\n\n"


async def ui_message_stream(events):
    yield ui_chunk("start", messageId=uuid4().hex)
    text_id = "answer"
    text_started = False
    steps = []
    citations = {}
    failed = False

    async for event, data in events:
        if event == "steps":
            steps.extend(data["steps"])
        elif event == "citations":
            citations.setdefault(data["kind"], []).extend(data["items"])
        elif event == "tool_data":
            tool_id = uuid4().hex
            yield ui_chunk("tool-input-available", toolCallId=tool_id, toolName=data["tool"], input={})
            yield ui_chunk("tool-output-available", toolCallId=tool_id, output=data["payload"])
            sample_hits = [ref for ref in data["payload"].get("references", []) if "video_id" in ref]
            if sample_hits:
                sample_id = uuid4().hex
                yield ui_chunk("tool-input-available", toolCallId=sample_id, toolName="search_samples", input={})
                yield ui_chunk("tool-output-available", toolCallId=sample_id, output={"hits": sample_hits})
        elif event == "delta":
            if not text_started:
                for step in steps:
                    tool_id = uuid4().hex
                    kind = step["tool"].removeprefix("search_")
                    yield ui_chunk("tool-input-available", toolCallId=tool_id, toolName=step["tool"],
                                   input={"query": step["query"]})
                    output = {"hits": step["hits"]} if "hits" in step else {"references": citations.get(kind, [])}
                    yield ui_chunk("tool-output-available", toolCallId=tool_id, output=output)
                yield ui_chunk("text-start", id=text_id)
                text_started = True
            yield ui_chunk("text-delta", id=text_id, delta=data["text"])
        elif event == "error":
            failed = True
            yield ui_chunk("error", errorText=data["message"])

    if text_started:
        yield ui_chunk("text-end", id=text_id)
    yield ui_chunk("finish", finishReason="error" if failed else "stop")
    yield "data: [DONE]\n\n"


def react_chat_body(body):
    messages = body["messages"]
    if not isinstance(messages, list):
        raise HTTPException(status_code=422, detail="messages must be a list")
    turns = [
        {"role": message["role"], "content": "\n".join(
            part["text"] for part in message["parts"]
            if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str)
        ), "metadata": message.get("metadata") if isinstance(message.get("metadata"), dict) else {}}
        for message in messages
        if isinstance(message, dict) and message.get("role") in ("user", "assistant")
        and isinstance(message.get("parts"), list)
    ]
    for index in range(len(turns) - 1, -1, -1):
        if turns[index]["role"] == "user":
            meta = turns[index].get("metadata") or {}
            body = {"message": turns[index]["content"], "history": turns[:index]}
            for key in ("tool", "kind", "storyboard", "script_text"):
                if meta.get(key) is not None:
                    body[key] = meta[key]
            return body
    return {}


def chunk_text(text: str, size: int = 6):
    """把长文本切成小块,模拟流式打字效果。"""
    for i in range(0, len(text), size):
        yield text[i:i + size]


@app.get("/api/health")
async def health():
    return {
        "ok": True,
        "online": llm.available(),
        "knowledge_entries": rag.count(),
        "case_count": case_store.count(),
        "library": library.stats(),
    }


# --------------------------------------------------------------------------
# 领域问答:在线 = 模型自主调用检索工具(Agent);离线 = 规则路由 + 直接检索
# --------------------------------------------------------------------------
async def handle_qa(message: str, history: list, api_key: str):
    online = llm.available(api_key)

    if online:
        msgs = [{"role": "system", "content": prompts.SYSTEM_QA_AGENT}]
        msgs += [{"role": m.get("role", "user"), "content": str(m.get("content", ""))} for m in history[-6:]]
        msgs.append({"role": "user", "content": message})
        text, steps = await llm.chat_with_tools(msgs, api_key=api_key)
        yield "steps", {"steps": steps}
        # 依据模型调用过的工具,补发引用(前端展示资料/案例来源)
        for st in steps:
            if st["tool"] == "search_knowledge" and st["query"]:
                hits = rag.retrieve(st["query"], k=3)
                yield "citations", {"kind": "knowledge", "items": [
                    {"title": h["title"], "category": h["category"]} for h in hits]}
            elif st["tool"] == "search_cases" and st["query"]:
                cases = case_store.search_cases(st["query"], k=3)
                yield "citations", {"kind": "cases", "items": [
                    {"id": c["id"], "title": c["title"], "type": c["type"], "genre": c["genre"],
                     "logline": c["logline"], "score": c["score"]} for c in cases]}
            elif st["tool"] == "search_scenes" and st["query"]:
                scenes = library.search_scenes(st["query"], k=3)
                yield "citations", {"kind": "scenes", "items": [
                    {"title": s["name_zh"], "category": s["dramatic_function"],
                     "score": s["score"]} for s in scenes]}
            elif st["tool"] == "search_shots" and st["query"]:
                shots = library.search_shots(st["query"], k=3)
                yield "citations", {"kind": "shots", "items": [
                    {"title": s["name_zh"], "category": f"{s['size']}/{s['angle']}/{s['movement']}",
                     "score": s["score"]} for s in shots]}
            elif st["tool"] == "search_stripboards" and st["query"]:
                templates = library.search_templates(st["query"], k=2)
                yield "citations", {"kind": "stripboards", "items": [
                    {"title": t["name"], "category": f"{t['type']}·{t['shoot_days']}天",
                     "score": t["score"]} for t in templates]}
        for chunk in chunk_text(text):
            yield "delta", {"text": chunk}
            await asyncio.sleep(0.02)
        return

    # ---------- 离线模式 ----------
    low = message.lower().strip()
    if re.fullmatch(r"(hi|hello|hey|你好|哈喽|嗨|喂|在吗|good\s+(morning|afternoon|evening))[!！。 ]*", low):
        text = ("你好!我是 Filmmate,你的影视创作助理。我可以:检查剧本漏洞、给分镜建议、"
                "排拍摄 Rundown、规划拍摄日程、找参考案例,或回答镜头语言/灯光/收音/剪辑等专业问题。想从哪里开始?")
        yield "steps", {"steps": []}
        for chunk in chunk_text(text):
            yield "delta", {"text": chunk}
            await asyncio.sleep(0.015)
        return
    if re.search(r"谢谢|多谢|thank", low):
        text = "不客气!随时把你的剧本或想法发给我,继续打磨你的作品。"
        yield "steps", {"steps": []}
        for chunk in chunk_text(text):
            yield "delta", {"text": chunk}
            await asyncio.sleep(0.015)
        return

    q = message[:40]
    yield "steps", {"steps": [{"tool": "search_knowledge", "query": q}]}
    hits = rag.retrieve(message, k=3) if rag.is_relevant(message) else []
    if hits:
        yield "citations", {"kind": "knowledge", "items": [
            {"title": h["title"], "category": h["category"]} for h in hits]}
        lines = [f"关于「{q}」,知识库检索到这些内容:"]
        for h in hits:
            lines.append(f"\n**{h['title']}**({h['category']})\n{h['content']}")
        lines.append("\n(离线演示模式:回答直接来自本地知识库;接入 API 后由大模型基于检索结果组织语言、综合多个条目。)")
        text = "\n".join(lines)
    else:
        text = ("这个问题在我的影视知识库里没有直接答案。我可以帮你:检查剧本漏洞、设计分镜、"
                "排拍摄 Rundown、规划拍摄日程、找参考案例。试试点击下方快捷按钮,或直接把剧本贴给我。")
    for chunk in chunk_text(text):
        yield "delta", {"text": chunk}
        await asyncio.sleep(0.015)


# --------------------------------------------------------------------------
# 创作工具(剧本检查/分镜/rundown/日程/灵感/案例)
# --------------------------------------------------------------------------
async def handle_tool(tool: str, message: str, api_key: str, script_text: str = "", script_name: str = "",
                      history: list = None, kind: str = None, storyboard: dict = None):
    # 只有剧本类任务才用上传文件覆盖输入；灵感/案例仍按用户当前输入检索
    script_tools = ("review", "storyboard", "rundown", "schedule")
    content = script_text if (script_text and tool in script_tools) else message
    needs_script = tool in ("rundown",)
    if needs_script and len(content) < 40 and not re.search(r"第\s*\d+\s*[场幕景]", content):
        hint = (
            "请先上传剧本文件（PDF / DOCX / TXT），或在输入框里粘贴剧本全文，再点这个功能。\n\n"
            "支持的格式：PDF、DOCX、TXT、Markdown、Fountain；单文件 ≤ 15 MB。"
        )
        for chunk in chunk_text(hint):
            yield "delta", {"text": chunk}
            await asyncio.sleep(0.01)
        return

    if tool == "review":
        payload = await tools.script_tool(message, api_key, script_text, history, kind=kind)
    elif tool == "storyboard":
        payload = await tools.storyboard_tool(message, api_key, script_text, history)
    elif tool == "schedule":
        payload = await tools.schedule_tool(message, api_key, storyboard, history)
    else:
        payload = await tools.run_tool(tool, content, api_key, history=history, kind=kind)
    if script_name:
        payload["script_name"] = script_name
    yield "tool_data", {"tool": tool, "payload": payload}
    if payload.get("steps"):
        yield "steps", {"steps": payload["steps"]}
    intro = payload.get("text")
    if intro:
        for chunk in chunk_text(intro):
            yield "delta", {"text": chunk}
            await asyncio.sleep(0.015)


@app.post("/api/chat")
async def chat(req: Request):
    body = await req.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Chat body must be an object")
    react = "messages" in body
    top_meta = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
    if react:
        body = react_chat_body(body)
        if top_meta:  # 兼容 transport 把 metadata 放在请求体顶层
            for _key in ("tool", "kind", "storyboard", "script_text"):
                if top_meta.get(_key) is not None and not body.get(_key):
                    body[_key] = top_meta[_key]
    message = (body.get("message") or "").strip()
    script_text = (body.get("script_text") or "").strip()
    script_name = (body.get("script_name") or "").strip()
    kind_hint = (body.get("kind") or "").strip() or None
    storyboard_payload = body.get("storyboard") if isinstance(body.get("storyboard"), dict) else None
    # React 前端上传剧本后，会把它附在消息末尾（【上传剧本】+ 原文）
    if "【上传剧本】" in message:
        head, _, uploaded = message.partition("【上传剧本】")
        message = head.strip()
        if not script_text:
            script_text = uploaded.strip()
    forced = (body.get("tool") or "").strip() or None
    if not forced:
        guessed_tool, guessed_kind, _idea = tools.guess_intent(message)
        forced = guessed_tool
        kind_hint = kind_hint or guessed_kind
    elif kind_hint is None:
        kind_hint, _idea = tools.parse_inspiration_kind(message)[0], ""
        kind_hint = kind_hint or tools.guess_intent(message)[1]
    tool = forced or tools.detect_tool(message)
    api_key = (body.get("api_key") or "").strip()
    history = body.get("history") or []
    online = llm.available(api_key)

    async def gen():
        try:
            if not message and not script_text:
                yield "done", {}
                return
            yield "start", {
                "tool": tool or "qa",
                "label": tools.tool_labels().get(tool or "qa", "知识问答"),
                "mode": "online" if online else "offline",
            }
            if tool is None:
                async for ev in handle_qa(message, history, api_key):
                    yield ev
            else:
                async for ev in handle_tool(tool, message, api_key, script_text, script_name, history,
                                             kind=kind_hint, storyboard=storyboard_payload):
                    yield ev
            yield "done", {}
        except Exception as e:  # noqa: BLE001
            logger.exception("请求处理失败")
            error_message = "The chat request failed. Check the server log and try again." if react else str(e)
            yield "error", {"message": error_message}

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    if react:
        headers["x-vercel-ai-ui-message-stream"] = "v1"
        stream = ui_message_stream(gen())
    else:
        stream = (legacy_event(event, data) async for event, data in gen())
    return StreamingResponse(stream, media_type="text/event-stream", headers=headers)


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if (WEB_DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="react-assets")


@app.get("/")
async def index():
    index_file = WEB_DIST / "index.html"
    if not index_file.is_file() or not (WEB_DIST / "assets").is_dir():
        raise HTTPException(
            status_code=503,
            detail="Build the React UI in filmmate-web with npm ci and npm run build, then restart Filmmate.",
        )
    html = await asyncio.to_thread(index_file.read_text, encoding="utf-8")
    html = html.replace("</head>", '<meta name="filmmate-backend" content="same-origin"></head>', 1)
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


@app.get("/legacy")
async def legacy_index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/catalog")
async def catalog_page():
    """影视灵感目录画廊（261 部 / 每部 10 张静帧）。"""
    page = STATIC_DIR / "catalog.html"
    if not page.exists():
        return FileResponse(STATIC_DIR / "index.html")
    # 画廊里的静帧用 frames/catalog/... 相对路径；加 <base> 让 /catalog 下也能正确指向 /static/
    html = await asyncio.to_thread(page.read_text, encoding="utf-8")
    html = html.replace("<head>", '<head><base href="/static/">', 1)
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="info")
