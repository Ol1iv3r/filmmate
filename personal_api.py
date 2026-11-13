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


@router.post("/personal")
def add_personal(body: AddFilm):
    try:
        entry = personal_library.add_film(
            url=body.url, title=body.title, moods=body.moods,
            script_text=body.script_text, script_name=body.script_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "film": entry}


@router.delete("/personal/{film_id}")
def delete_personal(film_id: str):
    if not personal_library.remove_film(film_id):
        raise HTTPException(status_code=404, detail="没有这条记录")
    return {"ok": True}
