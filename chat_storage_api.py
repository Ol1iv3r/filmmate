"""Phase 3 会话存储(chat storage):会话历史 REST 接口。

前端 `src/lib/conversations.ts` 的 `RemoteRepository` 早就写好了,这里只要满足
`docs/CONTRACT.md` §3:

    GET    /api/conversations        -> ConversationMeta[]
    GET    /api/conversations/:id    -> { messages: UIMessage[] } | 404
    PUT    /api/conversations/:id    -> ConversationMeta
    PATCH  /api/conversations/:id    -> {"ok": true}
    DELETE /api/conversations/:id    -> {"ok": true}

注意:PATCH / DELETE 必须回 JSON —— 前端 `req()` 会无条件 `res.json()`,
204 或空 body 会直接抛错。
"""
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import config
from chat_storage import (
    ConversationStore,
    ConversationStoreError,
    InvalidConversationId,
)

router = APIRouter(prefix="/api/conversations", tags=["conversations"])

_store: ConversationStore | None = None


def store() -> ConversationStore:
    global _store
    if _store is None:
        _store = ConversationStore(config.CONVERSATIONS_DIR)
    return _store


class SaveBody(BaseModel):
    messages: list[dict[str, Any]] = Field(default_factory=list)
    title: str | None = None


class RenameBody(BaseModel):
    title: str = ""


async def _call(coro):
    """把 store 的异常翻译成 HTTP 状态码。"""
    try:
        return await coro
    except InvalidConversationId as exc:
        raise HTTPException(status_code=400, detail=f"非法会话 id:{exc}") from exc
    except ConversationStoreError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("")
async def list_conversations():
    return await _call(store().list())


@router.get("/{conversation_id}")
async def get_conversation(conversation_id: str):
    data = await _call(store().load(conversation_id))
    if data is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"messages": data.get("messages") or []}


@router.put("/{conversation_id}")
async def save_conversation(conversation_id: str, body: SaveBody):
    if not all(isinstance(message, dict) for message in body.messages):
        raise HTTPException(status_code=400, detail="messages 必须是 UIMessage 对象数组")
    return await _call(store().save(conversation_id, body.messages, body.title))


@router.patch("/{conversation_id}")
async def rename_conversation(conversation_id: str, body: RenameBody):
    try:
        await _call(store().rename(conversation_id, body.title))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="会话不存在") from exc
    return {"ok": True}


@router.delete("/{conversation_id}")
async def delete_conversation(conversation_id: str):
    await _call(store().remove(conversation_id))
    return {"ok": True}
