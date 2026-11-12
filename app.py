"""Filmmate 后端入口:FastAPI + SSE 流式输出。

事件流(SSE):
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

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

import case_store
import config
import llm
import prompts
import rag
import tools

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("app")

app = FastAPI(title="Filmmate 影视创作助理")
STATIC_DIR = config.BASE_DIR / "static"


def sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


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
        yield sse("steps", {"steps": steps})
        # 依据模型调用过的工具,补发引用(前端展示资料/案例来源)
        for st in steps:
            if st["tool"] == "search_knowledge" and st["query"]:
                hits = rag.retrieve(st["query"], k=3)
                yield sse("citations", {"kind": "knowledge", "items": [
                    {"title": h["title"], "category": h["category"]} for h in hits]})
            elif st["tool"] == "search_cases" and st["query"]:
                cases = case_store.search_cases(st["query"], k=3)
                yield sse("citations", {"kind": "cases", "items": [
                    {"id": c["id"], "title": c["title"], "type": c["type"], "genre": c["genre"],
                     "logline": c["logline"], "score": c["score"]} for c in cases]})
        for chunk in chunk_text(text):
            yield sse("delta", {"text": chunk})
            await asyncio.sleep(0.02)
        return

    # ---------- 离线模式 ----------
    low = message.lower().strip()
    if re.fullmatch(r"(hi|hello|hey|你好|哈喽|嗨|喂|在吗|good\s+(morning|afternoon|evening))[!！。 ]*", low):
        text = ("你好!我是 Filmmate,你的影视创作助理。我可以:检查剧本漏洞、给分镜建议、"
                "排拍摄 Rundown、规划拍摄日程、找参考案例,或回答镜头语言/灯光/收音/剪辑等专业问题。想从哪里开始?")
        yield sse("steps", {"steps": []})
        for chunk in chunk_text(text):
            yield sse("delta", {"text": chunk})
            await asyncio.sleep(0.015)
        return
    if re.search(r"谢谢|多谢|thank", low):
        text = "不客气!随时把你的剧本或想法发给我,继续打磨你的作品。"
        yield sse("steps", {"steps": []})
        for chunk in chunk_text(text):
            yield sse("delta", {"text": chunk})
            await asyncio.sleep(0.015)
        return

    q = message[:40]
    yield sse("steps", {"steps": [{"tool": "search_knowledge", "query": q}]})
    hits = rag.retrieve(message, k=3) if rag.is_relevant(message) else []
    if hits:
        yield sse("citations", {"kind": "knowledge", "items": [
            {"title": h["title"], "category": h["category"]} for h in hits]})
        lines = [f"关于「{q}」,知识库检索到这些内容:"]
        for h in hits:
            lines.append(f"\n**{h['title']}**({h['category']})\n{h['content']}")
        lines.append("\n(离线演示模式:回答直接来自本地知识库;接入 API 后由大模型基于检索结果组织语言、综合多个条目。)")
        text = "\n".join(lines)
    else:
        text = ("这个问题在我的影视知识库里没有直接答案。我可以帮你:检查剧本漏洞、设计分镜、"
                "排拍摄 Rundown、规划拍摄日程、找参考案例。试试点击下方快捷按钮,或直接把剧本贴给我。")
    for chunk in chunk_text(text):
        yield sse("delta", {"text": chunk})
        await asyncio.sleep(0.015)


# --------------------------------------------------------------------------
# 创作工具(剧本检查/分镜/rundown/日程/灵感/案例)
# --------------------------------------------------------------------------
async def handle_tool(tool: str, message: str, api_key: str):
    if tool == "review" and len(message) < 60 and not re.search(r"[:：]", message):
        text = ("请把要检查的剧本或大纲贴给我(最好包含场次和对白),例如:\n\n"
                "第1场 天台 夜\n小明:今晚的月亮真圆。\n小红:嗯,和去年一样。\n\n"
                "我会从情节漏洞、时间线、人物动机、对白、结构等方面给出审阅报告。")
        for chunk in chunk_text(text):
            yield sse("delta", {"text": chunk})
            await asyncio.sleep(0.015)
        return

    payload = await tools.run_tool(tool, message, api_key)
    yield sse("tool_data", {"tool": tool, "payload": payload})
    if payload.get("steps"):
        yield sse("steps", {"steps": payload["steps"]})
    intro = payload.get("text")
    if intro:
        for chunk in chunk_text(intro):
            yield sse("delta", {"text": chunk})
            await asyncio.sleep(0.015)


@app.post("/api/chat")
async def chat(req: Request):
    body = await req.json()
    message = (body.get("message") or "").strip()
    forced = (body.get("tool") or "").strip() or None
    tool = forced or tools.detect_tool(message)
    api_key = (body.get("api_key") or "").strip()
    history = body.get("history") or []
    online = llm.available(api_key)

    async def gen():
        try:
            if not message:
                yield sse("done", {})
                return
            yield sse("start", {
                "tool": tool or "qa",
                "label": tools.tool_labels().get(tool or "qa", "知识问答"),
                "mode": "online" if online else "offline",
            })
            if tool is None:
                async for ev in handle_qa(message, history, api_key):
                    yield ev
            else:
                async for ev in handle_tool(tool, message, api_key):
                    yield ev
            yield sse("done", {})
        except Exception as e:  # noqa: BLE001
            logger.exception("请求处理失败")
            yield sse("error", {"message": str(e)})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="info")
