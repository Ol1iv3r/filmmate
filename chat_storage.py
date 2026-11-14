"""Phase 3 会话存储(chat storage):会话历史落盘(每个会话一个 JSON 文件)。

对应 Electron 版 `src/main/sessions/store.ts`,保证同样的行为:

- 原子写入:先写 `.tmp`,再 `os.replace` 覆盖,崩溃不会留下半个会话
- 同一会话的写入经过锁排队,autosave 不会互相覆盖
- id 只允许 `[A-Za-z0-9_-]{6,64}`,绝不把标题当文件名
- 坏文件隔离成 `*.corrupt-<时间戳>`,不会拖垮侧边栏
- schema 版本号;未知版本只跳过,不擅自改写

落盘格式就是前端契约里的 `UIMessage[]`(docs/CONTRACT.md §3):

    { "version": 1, "id": "conv-…", "title": "…",
      "createdAt": 1762900000000, "updatedAt": 1762900131000,
      "messages": [ { "id": "…", "role": "user", "parts": [ … ] } ] }

`createdAt` / `updatedAt` 是毫秒时间戳(number),与前端
`ConversationMeta` 一致 —— 这一点和 Electron 版的 ISO 字符串不同。
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{6,64}$")
DEFAULT_TITLE = "新对话"


class InvalidConversationId(ValueError):
    """id 不满足 filename 安全规则。"""


class ConversationStoreError(RuntimeError):
    """读 / 写 / 解析失败。"""


def _now_ms() -> int:
    return int(time.time() * 1000)


def derive_title(messages: list[dict[str, Any]], fallback: str = DEFAULT_TITLE) -> str:
    """和前端 titleFromMessages() 一致:取第一条 user 消息的纯文本,截 24 字。"""
    for message in messages:
        if message.get("role") != "user":
            continue
        parts = message.get("parts") or []
        text = " ".join(
            str(part.get("text", ""))
            for part in parts
            if isinstance(part, dict) and part.get("type") == "text"
        )
        text = " ".join(text.split())
        if text:
            return text[:24] + "…" if len(text) > 24 else text
    return fallback


def meta_of(data: dict[str, Any]) -> dict[str, Any]:
    """只返回契约要求的 4 个字段。"""
    return {
        "id": data["id"],
        "title": data.get("title") or DEFAULT_TITLE,
        "createdAt": int(data.get("createdAt") or 0),
        "updatedAt": int(data.get("updatedAt") or 0),
    }


class ConversationStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        # 用 threading.Lock 而不是 asyncio.Lock:真正的读写都在 to_thread 里,
        # 而且锁不该绑定到某一个事件循环上。
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    # ── 内部工具 ────────────────────────────────────────────────

    def _lock(self, conversation_id: str) -> threading.Lock:
        with self._locks_guard:
            lock = self._locks.get(conversation_id)
            if lock is None:
                lock = threading.Lock()
                self._locks[conversation_id] = lock
            return lock

    def _file(self, conversation_id: str) -> Path:
        return self.root / f"{conversation_id}.json"

    @staticmethod
    def _validate(conversation_id: str) -> None:
        if not ID_PATTERN.match(conversation_id):
            raise InvalidConversationId(conversation_id)

    @staticmethod
    def _quarantine(file: Path) -> None:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        try:
            file.rename(file.with_name(f"{file.name}.corrupt-{stamp}"))
        except OSError:
            pass

    def _write_atomic(self, file: Path, data: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = file.with_name(f"{file.name}.{os.getpid()}.{time.time_ns()}.tmp")
        try:
            tmp.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            os.replace(tmp, file)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    # ── 对外 API ────────────────────────────────────────────────

    async def list(self) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._list_sync)

    def _list_sync(self) -> list[dict[str, Any]]:
        self.root.mkdir(parents=True, exist_ok=True)
        metas: list[dict[str, Any]] = []
        for file in self.root.glob("*.json"):
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue  # 坏文件不进侧边栏,也不在这里删
            if data.get("version") != SCHEMA_VERSION:
                continue
            metas.append(meta_of(data))
        metas.sort(key=lambda m: m["updatedAt"], reverse=True)
        return metas

    async def load(self, conversation_id: str) -> dict[str, Any] | None:
        self._validate(conversation_id)
        return await asyncio.to_thread(self._load_sync, conversation_id)

    def _load_sync(self, conversation_id: str) -> dict[str, Any] | None:
        file = self._file(conversation_id)
        try:
            raw = file.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise ConversationStoreError(f"读取会话失败:{exc}") from exc

        try:
            data = json.loads(raw)
        except ValueError:
            self._quarantine(file)
            return None

        # 未来版本的 schema 不猜、不改、不隔离,只当它不存在。
        if data.get("version") != SCHEMA_VERSION or data.get("id") != conversation_id:
            return None
        return data

    async def save(
        self,
        conversation_id: str,
        messages: list[dict[str, Any]],
        title: str | None = None,
    ) -> dict[str, Any]:
        self._validate(conversation_id)
        return await asyncio.to_thread(self._save_locked, conversation_id, messages, title)

    def _save_locked(
        self,
        conversation_id: str,
        messages: list[dict[str, Any]],
        title: str | None,
    ) -> dict[str, Any]:
        with self._lock(conversation_id):
            return self._save_sync(conversation_id, messages, title)

    def _save_sync(
        self,
        conversation_id: str,
        messages: list[dict[str, Any]],
        title: str | None,
    ) -> dict[str, Any]:
        file = self._file(conversation_id)
        existing: dict[str, Any] | None = None
        if file.exists():
            try:
                existing = json.loads(file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._quarantine(file)

        now = _now_ms()
        clean_title = (title or "").strip()
        if not clean_title:
            current = (existing or {}).get("title") or ""
            # 新建会话时前端会先 PUT 一次空 messages,标题先占位成"新对话";
            # 等第一条消息到了再自动补真实标题。
            if current and current != DEFAULT_TITLE:
                clean_title = current
            else:
                clean_title = derive_title(messages)

        data = {
            "version": SCHEMA_VERSION,
            "id": conversation_id,
            "title": clean_title,
            "createdAt": (existing or {}).get("createdAt") or now,
            "updatedAt": now,
            "messages": messages,
        }
        self._write_atomic(file, data)
        return meta_of(data)

    async def rename(self, conversation_id: str, title: str) -> dict[str, Any]:
        self._validate(conversation_id)
        return await asyncio.to_thread(self._rename_locked, conversation_id, title)

    def _rename_locked(self, conversation_id: str, title: str) -> dict[str, Any]:
        with self._lock(conversation_id):
            return self._rename_sync(conversation_id, title)

    def _rename_sync(self, conversation_id: str, title: str) -> dict[str, Any]:
        file = self._file(conversation_id)
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise KeyError(conversation_id) from exc
        except (OSError, ValueError) as exc:
            raise ConversationStoreError(f"会话文件损坏:{file.name}") from exc

        data["title"] = title.strip() or DEFAULT_TITLE
        data["updatedAt"] = _now_ms()
        self._write_atomic(file, data)
        return meta_of(data)

    async def remove(self, conversation_id: str) -> None:
        self._validate(conversation_id)
        await asyncio.to_thread(self._remove_locked, conversation_id)

    def _remove_locked(self, conversation_id: str) -> None:
        with self._lock(conversation_id):
            self._remove_sync(conversation_id)

    def _remove_sync(self, conversation_id: str) -> None:
        try:
            self._file(conversation_id).unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise ConversationStoreError(f"删除会话失败:{exc}") from exc
