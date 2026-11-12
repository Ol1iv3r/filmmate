"""Phase 3 会话存储(chat storage)预留:LangChain `BaseMessage` <-> 落盘 dict。

当前 `/api/chat` 还不是 LangChain(由组员后续接手)。等聊天层换成 LangChain 的
消息类之后,只要在写库前调用 `messages_to_dicts(messages)`,就能复用
`chat_storage` 的落盘格式,存储层一行都不用改:

    history = messages_to_dicts(chat_history)      # BaseMessage -> dict
    # ... 存进 data/conversations/<id>.json ...

刻意不写进 requirements.txt:LangChain 没装时 import 本模块也不会失败,
只有真正调用 `dicts_to_messages()` 时才需要 `langchain-core`。
"""
from typing import Any, Sequence


def messages_to_dicts(messages: Sequence[Any]) -> list[dict[str, Any]]:
    """`BaseMessage.to_dict()` 就是官方的 dict 形式:

        {"type": "human", "data": {"content": "...", "additional_kwargs": {}, ...}}
    """
    return [message.to_dict() for message in messages]


def dicts_to_messages(payloads: Sequence[dict[str, Any]]) -> list[Any]:
    """把落盘的 dict 读回 `BaseMessage`(需要 langchain-core)。"""
    try:
        from langchain_core.messages import messages_from_dict
    except ImportError as exc:  # pragma: no cover - 只会在未安装时触发
        raise RuntimeError(
            "需要 langchain-core 才能读回 BaseMessage:pip install langchain-core"
        ) from exc
    return messages_from_dict(list(payloads))


_ROLE = {
    "human": "user",
    "ai": "assistant",
    "system": "system",
    "tool": "assistant",
    "function": "assistant",
}


def dicts_to_ui_messages(payloads: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """LangChain dict -> 前端契约里的 `UIMessage`(纯文本部分)。

    tool_call / tool_result 的映射留给 Phase 4 的组员补;这里只保证文本消息
    能在前端正常显示。
    """
    messages: list[dict[str, Any]] = []
    for index, payload in enumerate(payloads):
        kind = str(payload.get("type", "human"))
        data = payload.get("data") or {}
        content = data.get("content")
        if isinstance(content, str):
            text = content
        else:
            text = "".join(
                str(block.get("text", ""))
                for block in content or []
                if isinstance(block, dict) and block.get("type") == "text"
            )
        messages.append(
            {
                "id": f"lc-{index}",
                "role": _ROLE.get(kind, "assistant"),
                "parts": [{"type": "text", "text": text}],
            }
        )
    return messages
