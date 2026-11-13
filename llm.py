"""DeepSeek 大模型客户端(OpenAI 兼容接口,httpx 异步实现)。

- stream_chat: 流式输出,逐段 yield 增量文本
- complete: 一次性返回全文
- complete_json: 要求 JSON 输出并解析,解析失败自动重试
"""
import json
import logging
import re

import httpx

import config

logger = logging.getLogger("llm")


def available(api_key: str = None):
    return bool((api_key or "").strip() or config.DEEPSEEK_API_KEY)


def _payload(messages, temperature, json_mode, stream):
    payload = {
        "model": config.DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": temperature,
        "stream": stream,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    return payload


async def stream_chat(messages, api_key: str = None, temperature: float = 0.7, timeout: float = 120.0):
    """逐段返回模型生成的增量文本。"""
    key = api_key or config.DEEPSEEK_API_KEY
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    url = config.DEEPSEEK_BASE_URL.rstrip("/") + "/chat/completions"
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", url, json=_payload(messages, temperature, False, True), headers=headers) as resp:
            if resp.status_code != 200:
                body = (await resp.aread()).decode("utf-8", "ignore")
                raise RuntimeError(f"DeepSeek API {resp.status_code}: {body[:300]}")
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                delta = chunk.get("choices", [{}])[0].get("delta", {}).get("content")
                if delta:
                    yield delta


async def complete(messages, api_key: str = None, temperature: float = 0.7, timeout: float = 120.0):
    chunks = []
    async for c in stream_chat(messages, api_key=api_key, temperature=temperature, timeout=timeout):
        chunks.append(c)
    return "".join(chunks)


def _extract_json(text: str):
    """从模型输出中尽力提取 JSON 对象。"""
    text = (text or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    raise ValueError("无法从模型输出中解析出 JSON")


async def complete_json(messages, api_key: str = None, temperature: float = 0.4, retries: int = 2):
    """请求结构化 JSON 输出;解析失败自动重试,仍失败则抛出异常。"""
    last_err = None
    for attempt in range(retries):
        try:
            text = await complete(messages, api_key=api_key, temperature=temperature)
            return _extract_json(text)
        except Exception as e:  # noqa: BLE001
            last_err = e
            logger.warning("JSON 解析失败(第 %d 次): %s", attempt + 1, e)
    raise last_err


# --------------------------------------------------------------------------
# 工具调用(Agent / Function Calling)
# 模型自主决定何时调用检索工具,拿到结果后再生成最终回答
# --------------------------------------------------------------------------
TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": "在影视专业知识库中检索拍摄知识:景别/机位/运镜/灯光/收音/剪辑/拍摄流程/设备/香港取景地。适合回答「怎么拍」「什么是」类专业问题。",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "检索关键词,如:夜景布光 三点布光 180度规则"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_cases",
            "description": "在优秀作品案例库中检索与用户创意/需求相关的参考案例。每部案例含剧本梗概、分镜要点、拍摄Rundown、设备清单与经验教训。适合回答「有没有类似案例」「别人怎么拍」「给我参考」类问题,或为剧本/分镜/日程生成提供样本。",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "检索关键词,如:爱情短片 夜景 低成本 纪录片"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_scenes",
            "description": "在场面模式库中检索某类戏的专业拍法：戏剧功能、节拍结构、冲突/潜台词、走位调度、建议镜头、光线与声音、页数（1/8 页）与拍摄分钟估算。适合回答「这场戏怎么拍」「怎么调度」「要拍多久」。",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "检索关键词,如:天台告白 夜景 关系转折 审讯对峙"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_shots",
            "description": "在镜头模式库中检索具体镜头：景别/机位/运镜/焦段/帧率/光线/声音/叙事用途/常见误用。适合回答「这个情绪用什么镜头」「推镜头什么时候用」。",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "检索关键词,如:推镜头 孤独 大特写 荷兰角 手持跟拍"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_stripboards",
            "description": "在通告单模板库中检索专业 stripboard / call sheet：crew_call、setup、scene、company move、meal、wrap 的时间块，页数（1/8 页）与拍摄分钟合计。适合回答「一天能拍多少」「通告单怎么排」「要几天」。",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "检索关键词,如:单日广告 夜戏 转场 三天短片"}},
                "required": ["query"],
            },
        },
    },
]


def execute_tool(name: str, query: str, limit: int = 3):
    """执行检索工具,返回给模型的结果文本。"""
    import case_store
    import library
    import rag

    if name == "search_knowledge":
        hits = rag.retrieve(query, k=limit)
        if not hits:
            return "(知识库中没有检索到相关内容)"
        parts = [f"[{h['category']}] {h['title']}: {h['content']}" for h in hits]
        return "\n".join(parts)
    if name == "search_cases":
        hits = case_store.search_cases(query, k=limit)
        if not hits:
            return "(案例库中没有检索到相关内容)"
        return "\n\n".join(case_store.case_to_text(c)[:1200] for c in hits)
    if name == "search_scenes":
        hits = library.search_scenes(query, k=min(limit, 3))
        if not hits:
            return "(场面模式库中没有检索到相关内容)"
        return "\n\n".join(library.scene_to_text(s) for s in hits)
    if name == "search_shots":
        hits = library.search_shots(query, k=min(limit, 4))
        if not hits:
            return "(镜头模式库中没有检索到相关内容)"
        return "\n".join(library.shot_to_text(s) for s in hits)
    if name == "search_stripboards":
        hits = library.search_templates(query, k=min(limit, 2))
        if not hits:
            return "(通告单模板库中没有检索到相关内容)"
        return "\n\n".join(library.template_to_text(t) for t in hits)
    return f"(未知工具 {name})"


async def complete_raw(messages, api_key: str = None, temperature: float = 0.7, tools=None, timeout: float = 120.0):
    """单次非流式请求,返回完整响应 JSON(支持 tools 参数)。"""
    key = api_key or config.DEEPSEEK_API_KEY
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    url = config.DEEPSEEK_BASE_URL.rstrip("/") + "/chat/completions"
    payload = {
        "model": config.DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code != 200:
            body = resp.text[:300]
            raise RuntimeError(f"DeepSeek API {resp.status_code}: {body}")
        return resp.json()


async def chat_with_tools(messages, api_key: str = None, max_steps: int = 3):
    """Agent 循环:模型决定是否调用检索工具 → 我们执行工具 → 结果回填 → 模型生成最终回答。

    返回 (final_text, steps),steps 记录工具调用过程供前端展示:
    [{"tool": "search_cases", "query": "夜景 低成本"}, ...]
    """
    msgs = [dict(m) for m in messages]
    steps = []
    for _ in range(max_steps):
        data = await complete_raw(msgs, api_key=api_key, tools=TOOLS_SCHEMA)
        choice = data.get("choices", [{}])[0].get("message", {})
        tool_calls = choice.get("tool_calls") or []
        if tool_calls:
            msgs.append({"role": "assistant", "content": choice.get("content") or "", "tool_calls": tool_calls})
            for tc in tool_calls:
                fn = tc.get("function", {})
                name = fn.get("name", "")
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                query = str(args.get("query", ""))
                steps.append({"tool": name, "query": query})
                try:
                    result = execute_tool(name, query)
                except Exception as e:  # noqa: BLE001
                    result = f"(工具执行失败: {e})"
                msgs.append({"role": "tool", "tool_call_id": tc.get("id", ""), "content": result})
            continue
        text = choice.get("content") or ""
        if text.strip():
            return text, steps
    # 达到步数上限仍未给出最终回答 → 去掉工具强制生成一次
    data = await complete_raw(msgs, api_key=api_key)
    return data.get("choices", [{}])[0].get("message", {}).get("content") or "", steps
