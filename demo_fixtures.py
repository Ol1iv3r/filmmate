"""Deterministic demo fixtures for the live presentation.

Enable with DEMO_MODE=1 in .env. All demo responses are fixed; the only
randomness is which of the three prepared variants is shown, and how long the
UI reports the generation took (always < 5 seconds).
"""
from __future__ import annotations

import asyncio
import copy
import json
import random
import re
from datetime import datetime, timezone
from pathlib import Path

import config
import personal_library

FIXTURE_FILE = config.BASE_DIR / "data" / "demo" / "demo_fixtures.json"
_state: dict = {"set_index": None, "theme_index": 0, "fixtures": None, "demo_refs": set(), "demo_flow": False, "genre_mode": False}


def enabled() -> bool:
    return bool(getattr(config, "DEMO_MODE", False))


def _load() -> dict:
    if _state["fixtures"] is None:
        try:
            _state["fixtures"] = json.loads(FIXTURE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _state["fixtures"] = {}
    return _state["fixtures"]


def _variants(key: str) -> list:
    return _load().get(key) or []


def _is_hong_kong(text: str) -> bool:
    return bool(re.search(r"\bhong\s*kong\b|香港", text or "", re.I))


def _is_reference_trigger(text: str) -> bool:
    return bool(re.search(
        r"life\s*of\s*riza|cinematic\s*everyday|everyday\s*life|slow\s*living|vlog",
        text or "", re.I,
    ))


def all_demo_urls(urls: list[str]) -> bool:
    return bool(urls) and all(_find_ref(str(u or "")) is not None for u in urls)


def _ensure_set() -> int:
    if _state.get("set_index") is None:
        _state["set_index"] = random.randrange(3)
        _state["theme_index"] = 0
    return int(_state["set_index"]) % 3


def _script_index() -> int:
    set_i = _ensure_set()
    theme_i = int(_state.get("theme_index") or 0) % 3
    return set_i * 3 + theme_i


def _select_theme(message: str = "") -> None:
    text = message or ""
    m = re.search(r"(?:theme|主题)\s*([123])", text, re.I)
    if m:
        _state["theme_index"] = int(m.group(1)) - 1
        return
    # Also allow the title of one of the current set's themes.
    variants = _variants("scripts")
    set_i = _ensure_set()
    for theme_i in range(3):
        item = variants[set_i * 3 + theme_i] if set_i * 3 + theme_i < len(variants) else None
        title = ((item or {}).get("logline") or {}).get("title", "")
        if title and title.lower() in text.lower():
            _state["theme_index"] = theme_i
            return


async def _timed(payload: dict, low: int = 1100, high: int = 3800) -> dict:
    """Sleep for a natural-looking, non-fixed delay under five seconds."""
    ms = random.randint(low, high)
    await asyncio.sleep(ms / 1000)
    out = copy.deepcopy(payload)
    out["ms"] = ms
    out["mode"] = "online"
    return out


def _render_inspiration(payload: dict, idea: str) -> str:
    films = payload.get("films") or []
    styles = payload.get("styles") or []
    lines = [f"**Genre**: Film　｜　**Keywords**: {idea or '(not given)'}", ""]
    for i, style in enumerate(styles):
        film = films[i] if i < len(films) else {}
        personal = film.get("source") == "personal"
        title = film.get("title_zh") or film.get("title_en") or "Untitled"
        lines.append(f"### Style {i + 1}: {style.get('style_name', '')}")
        lines.append(f"- **Why it fits there**: {style.get('why_fits', '')}")
        lines.append(f"- **Theme {i + 1}**: {style.get('theme', '')}")
        if personal:
            lines.append(f"- **Matching film {i + 1}**: *{title}* — **your saved reference**")
        else:
            lines.append(f"- **Matching film {i + 1}**: *{title}* ({film.get('year', '')})")
        if film.get("synopsis"):
            lines.append(f"  - Story: {film.get('synopsis')}")
        if film.get("url"):
            lines.append(f"  - Watch: [{film.get('platform') or 'link'}]({film['url']})")
        if style.get("film_reason"):
            lines.append(f"  - Reference point: {style['film_reason']}")
        lines.append("")
    lines.append("---")
    lines.append("Want me to write the script based on **Theme 1**? Reply 'write script'. "
                 "For another theme in this set, reply 'write script: theme 2' or 'theme 3'.")
    return "\n".join(lines)


async def inspiration(idea: str, kind: str | None = None, history: list | None = None) -> dict | None:
    if not enabled():
        return None
    if kind not in (None, "电影", "Film"):
        _state["demo_flow"] = False
        return None
    if _is_hong_kong(idea):
        _state["demo_flow"] = True
        _state["genre_mode"] = False
        _state["set_index"] = random.randrange(3)
        _state["theme_index"] = 0
        payload = copy.deepcopy(_variants("inspiration")[_state["set_index"]])
        payload["kind"] = "Film"
        payload["idea"] = idea
        payload["text"] = _render_inspiration(payload, idea)
        return await _timed(payload, 1100, 3400)
    if reference_ready() and _is_reference_trigger(idea):
        _state["demo_flow"] = False
        _state["genre_mode"] = False
        ref_variants = _variants("reference_inspiration")
        payload = copy.deepcopy(ref_variants[random.randrange(len(ref_variants))])
        payload["idea"] = idea
        payload["text"] = _render_inspiration(payload, idea)
        return await _timed(payload, 1000, 3000)
    _state["demo_flow"] = False
    _state["genre_mode"] = False
    return None


def _is_review_request(text: str) -> bool:
    return bool(re.search(r"\b(check|review|analy[sz]e|analyse|feedback)\b|检查|分析|审阅|漏洞", text or "", re.I))


def _is_vlog(kind: str | None) -> bool:
    return str(kind or "").strip() in ("Vlog/美食", "Vlog / Food", "Vlog", "Food", "美食")


def _genre_payload(kind: str, key: str) -> dict | None:
    sets = _load().get("genre_sets") or {}
    return copy.deepcopy((sets.get(kind) or {}).get(key))


async def script(message: str = "", script_text: str = "", kind: str | None = None) -> dict | None:
    if not enabled():
        return None
    if script_text and _is_review_request(message):
        payload = copy.deepcopy(_load().get("review") or {})
        if not payload:
            return None
        payload["script_text"] = script_text
        payload["text"] = str(payload.get("text") or "").replace(
            "~310 characters", f"~{len(script_text)} characters"
        )
        return await _timed(payload, 8800, 9800)
    if _is_vlog(kind) and personal_library.list_films():
        payload = _genre_payload("Vlog/美食", "script")
        if payload is not None:
            _state["genre_mode"] = True
            _state["demo_flow"] = False
            return await _timed(payload, 8800, 9800)
    if not _state.get("demo_flow"):
        return None
    _select_theme(message)
    payload = copy.deepcopy(_variants("scripts")[_script_index()])
    return await _timed(payload, 8800, 9800)


async def storyboard() -> dict | None:
    if not enabled():
        return None
    if _state.get("genre_mode"):
        payload = _genre_payload("Vlog/美食", "storyboard")
        if payload is not None:
            return await _timed(payload, 8800, 9800)
    if not _state.get("demo_flow"):
        return None
    payload = copy.deepcopy(_variants("storyboards")[_script_index()])
    return await _timed(payload, 8800, 9800)


async def schedule() -> dict | None:
    if not enabled():
        return None
    if _state.get("genre_mode"):
        payload = _genre_payload("Vlog/美食", "schedule")
        if payload is not None:
            return await _timed(payload, 8800, 9800)
    if not _state.get("demo_flow"):
        return None
    payload = copy.deepcopy(_variants("schedules")[_script_index()])
    return await _timed(payload, 8800, 9800)


# --------------------------------------------------------------------------
# Reference films
# --------------------------------------------------------------------------
def _refs() -> list[dict]:
    return _load().get("reference_films") or []


def _youtube_id(url: str) -> str | None:
    m = re.search(r"(?:[?&]v=|youtu\.be/|youtube\.com/shorts/)([A-Za-z0-9_-]{11})", url or "")
    return m.group(1) if m else None


def _find_ref(url: str) -> dict | None:
    video_id = _youtube_id(url)
    if not video_id:
        return None
    return next((r for r in _refs() if _youtube_id(r.get("url", "")) == video_id), None)


def _entry(ref: dict) -> dict:
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    return {
        "id": ref["id"], "title": ref["title"], "url": ref["url"],
        "cover": "", "duration": ref.get("duration", ""), "duration_sec": 0,
        "owner": ref.get("owner", "Life Of Riza"), "platform": "YouTube",
        "moods": ref.get("moods") or [], "frames": ref.get("frames") or [],
        "script_name": "", "script_text": "", "source": "personal",
        "added_at": now, "style_summary": ref.get("style_summary", ""),
        "style_tags": ref.get("style_tags") or [],
        "visual_summary": ref.get("visual_summary", ""),
        "visual_tags": ref.get("style_tags") or [], "visual_beats": [],
    }


def reference_ready() -> bool:
    if not enabled():
        return False
    saved = {(_youtube_id(f.get("url", "")) or "") for f in personal_library.list_films()}
    wanted = {(_youtube_id(r.get("url", "")) or "") for r in _refs()}
    added = _state.get("demo_refs") or set()
    return bool(wanted) and wanted.issubset(saved) and wanted.issubset(added)


async def add_references(urls: list[str], lang: str = "en") -> dict | None:
    """Demo path: each Life Of Riza link takes exactly five seconds and is stored."""
    if not enabled():
        return None
    urls = [str(u or "").strip() for u in urls if str(u or "").strip()]
    if not urls:
        return None
    films, errors = [], []
    for url in urls:
        ref = _find_ref(url)
        if ref is None:
            errors.append({"url": url, "error": "Demo mode only supports the three Life Of Riza links."})
            continue
        await asyncio.sleep(5.0)
        existing = next((f for f in personal_library.list_films()
                         if f.get("url") == ref.get("url")), None)
        if existing is not None:
            entry = existing
            # Keep the user's saved entry and frames; only fill missing demo fields.
            if not entry.get("frames"):
                entry = _entry(ref)
                personal_library.save_entry(entry)
        else:
            entry = _entry(ref)
            personal_library.save_entry(entry)
        _state.setdefault("demo_refs", set()).add(_youtube_id(ref.get("url", "")) or "")
        entry["analyzed"] = True
        entry["visual_analyzed"] = True
        films.append(entry)
    if not films:
        return {"ok": False, "films": [], "errors": errors,
                "detail": errors[0]["error"] if errors else "No demo references added."}
    return {"ok": True, "films": films, "errors": errors,
            "film": films[0] if len(films) == 1 else None}
