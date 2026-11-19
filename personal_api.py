"""Personal reference-film library REST API.

Supports single adds and batch adds. Bilibili/YouTube metadata lookup and
style analysis run off the event loop so adding a film cannot freeze chat.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import personal_library

router = APIRouter(prefix="/api/library", tags=["personal"])

STYLE_PROMPT = """你是电影策展人。根据用户给的片名/平台/标签，推断这部电影的基本信息与风格。
只输出 JSON：{"summary": "一句话风格描述（题材+影像气质+情绪）", "tags": ["标签1", "标签2", "标签3"]}"""

STYLE_PROMPT_EN = """You are a film curator. Infer the style of this film from its title, platform and user tags.
Return JSON only: {"summary": "one sentence covering genre + visual texture + mood", "tags": ["tag1", "tag2", "tag3"]}"""


class AddFilm(BaseModel):
    url: str = ""
    urls: list[str] = Field(default_factory=list)
    title: str = ""
    moods: list[str] = Field(default_factory=list)
    script_text: str = ""
    script_name: str = ""
    lang: str = "zh"


@router.get("/personal")
def list_personal():
    return {"films": personal_library.list_films()}


def _error_text(exc: Exception, lang: str) -> str:
    message = str(exc or "")
    if lang != "en":
        return message
    mapping = {
        "请至少填写片名，或提供可识别的 Bilibili / YouTube 链接": "Enter a title or a Bilibili / YouTube link.",
        "请提供影片链接（支持 Bilibili / YouTube）": "Provide a Bilibili / YouTube link.",
        "个人灵感库已满（200 条）": "The reference library is full (200 films).",
        "这部片已经在你的灵感库里了": "This film is already in your reference library.",
    }
    return mapping.get(message, message)


async def _analyze_style(entry: dict, lang: str) -> dict:
    """Best-effort style analysis; never fail the add because the model is slow."""
    try:
        import llm
        if not llm.available():
            return entry
        system = STYLE_PROMPT_EN if lang == "en" else STYLE_PROMPT
        data = await asyncio.wait_for(
            llm.complete_json(
                [{"role": "system", "content": system},
                 {"role": "user", "content": f"Title: {entry.get('title')} | Platform: {entry.get('platform')} "
                                             f"| User tags: {', '.join(entry.get('moods') or [])} "
                                             f"| Link: {entry.get('url')}"}],
                temperature=0.2,
            ),
            timeout=18,
        )
        personal_library.update_style(entry["id"], str(data.get("summary", "")), data.get("tags") or [])
        entry = next((f for f in personal_library.list_films() if f.get("id") == entry["id"]), entry)
        entry["analyzed"] = True
    except Exception:  # noqa: BLE001
        entry["analyzed"] = False
    return entry


@router.post("/personal")
async def add_personal(body: AddFilm):
    raw_urls = body.urls or ([body.url] if body.url else [])
    urls = []
    for raw in raw_urls:
        value = str(raw or "").strip()
        if value and value not in urls:
            urls.append(value)
    if not urls:
        raise HTTPException(status_code=400, detail="Provide at least one Bilibili / YouTube link.")
    if len(urls) > 20:
        raise HTTPException(status_code=400, detail="Add at most 20 reference films at a time.")

    try:
        import demo_fixtures
        if demo_fixtures.enabled() and demo_fixtures.all_demo_urls(urls):
            demo = await demo_fixtures.add_references(urls, body.lang)
            if demo is not None:
                return demo
    except Exception:  # noqa: BLE001
        pass

    semaphore = asyncio.Semaphore(3)
    single_title = body.title.strip() if len(urls) == 1 else ""

    async def add_one(url: str) -> dict:
        async with semaphore:
            try:
                entry = await asyncio.to_thread(
                    personal_library.add_film,
                    url,
                    single_title,
                    body.moods,
                    body.script_text,
                    body.script_name,
                )
            except ValueError as exc:
                return {"ok": False, "url": url, "error": _error_text(exc, body.lang)}
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "url": url, "error": _error_text(exc, body.lang)}
            entry = await _analyze_style(entry, body.lang)
            if entry.get("frames"):
                try:
                    import llm
                    if llm.vision_available():
                        visual = await asyncio.wait_for(
                            llm.analyze_reference_frames(entry["frames"], entry.get("title", ""), lang=body.lang),
                            timeout=40,
                        )
                        personal_library.update_visual(
                            entry["id"],
                            str(visual.get("summary") or ""),
                            visual.get("visual_tags") or [],
                            visual.get("beats") or [],
                        )
                        entry = next((f for f in personal_library.list_films() if f.get("id") == entry["id"]), entry)
                        entry["analyzed"] = bool(entry.get("style_summary"))
                        entry["visual_analyzed"] = True
                except Exception:  # noqa: BLE001
                    entry["visual_analyzed"] = False
            return {"ok": True, "url": url, "film": entry}

    results = await asyncio.gather(*(add_one(url) for url in urls))
    films = [item["film"] for item in results if item.get("ok")]
    errors = [{"url": item["url"], "error": item.get("error", "")} for item in results if not item.get("ok")]
    if not films:
        detail = errors[0]["error"] if errors else "Could not add the reference film."
        raise HTTPException(status_code=400, detail=detail)
    return {
        "ok": True,
        "films": films,
        "errors": errors,
        "film": films[0] if len(films) == 1 else None,
    }


@router.delete("/personal/{film_id}")
def delete_personal(film_id: str):
    if not personal_library.remove_film(film_id):
        raise HTTPException(status_code=404, detail="没有这条记录")
    return {"ok": True}
