"""个人灵感库 REST：GET / POST / DELETE /api/library/personal"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import personal_library

router = APIRouter(prefix="/api/library", tags=["personal"])


class AddFilm(BaseModel):
    url: str = ""
    title: str = ""
    moods: list[str] = []
    script_text: str = ""
    script_name: str = ""


@router.get("/personal")
def list_personal():
    return {"films": personal_library.list_films()}


STYLE_PROMPT = """你是电影策展人。根据用户给的片名/平台/标签，推断这部电影的基本信息与风格。
只输出 JSON：{"summary": "一句话风格描述（题材+影像气质+情绪）", "tags": ["标签1", "标签2", "标签3"]}"""


@router.post("/personal")
async def add_personal(body: AddFilm):
    try:
        entry = personal_library.add_film(
            url=body.url, title=body.title, moods=body.moods,
            script_text=body.script_text, script_name=body.script_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # 用模型补全「风格分析」，后续回答会参考用户收藏的品味
    try:
        import llm
        if llm.available():
            data = await llm.complete_json(
                [{"role": "system", "content": STYLE_PROMPT},
                 {"role": "user", "content": f"片名：{entry.get('title')}｜平台：{entry.get('platform')}"
                                             f"｜用户标签：{'、'.join(entry.get('moods') or [])}"
                                             f"｜链接：{entry.get('url')}"}])
            personal_library.update_style(entry["id"], str(data.get("summary", "")), data.get("tags") or [])
            entry = next((f for f in personal_library.list_films() if f.get("id") == entry["id"]), entry)
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "film": entry}


@router.delete("/personal/{film_id}")
def delete_personal(film_id: str):
    if not personal_library.remove_film(film_id):
        raise HTTPException(status_code=404, detail="没有这条记录")
    return {"ok": True}
