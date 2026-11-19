"""Storyboard CSV upload parser.

Accepts the CSV that the Storyboard panel exports (English or Chinese headers)
and converts every row into the same shot shape used by the normal storyboard
payload, so the existing analysis / shooting-plan tools can consume it.
"""
from __future__ import annotations

import csv
import io
import re

from fastapi import APIRouter, File, HTTPException, UploadFile

router = APIRouter(prefix="/api", tags=["storyboard"])
MAX_BYTES = 5 * 1024 * 1024

ALIASES = {
    "id": ("shot", "shot #", "#", "id", "镜号", "镜头"),
    "scene": ("scene", "场次", "场景"),
    "shot_type": ("size", "shot type", "景别", "shooting size"),
    "angle": ("angle", "机位", "角度"),
    "movement": ("movement", "运镜", "move"),
    "lens": ("lens", "焦段"),
    "duration": ("duration", "时长"),
    "description": ("frame", "description", "画面", "画面内容"),
    "dialogue": ("dialogue", "台词", "对白"),
    "lighting": ("lighting", "光线", "灯光"),
    "sound": ("sound", "声音", "音效"),
    "purpose": ("purpose", "目的"),
    "transition": ("transition", "转场"),
}


def _norm_header(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _column_map(headers: list[str]) -> dict[str, int]:
    normalized = [_norm_header(h) for h in headers]
    out: dict[str, int] = {}
    for field, aliases in ALIASES.items():
        for alias in aliases:
            alias_norm = _norm_header(alias)
            if alias_norm in normalized:
                out[field] = normalized.index(alias_norm)
                break
    return out


def _scene_no(value: str, fallback: int) -> int:
    text = str(value or "")
    m = re.search(r"(?:scene|第)\s*(\d+)", text, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"^\s*(\d+)\s*[.\-:：]", text)
    if m:
        return int(m.group(1))
    return fallback


def _parse(raw: bytes, filename: str = "") -> dict:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "big5"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text))
    rows = [row for row in reader if any(str(cell).strip() for cell in row)]
    if len(rows) < 2:
        raise HTTPException(status_code=400, detail="CSV 至少需要表头和一行镜头 / CSV needs a header and at least one shot row")
    headers = [str(h).strip() for h in rows[0]]
    columns = _column_map(headers)
    if "scene" not in columns and "description" not in columns:
        raise HTTPException(status_code=400, detail="CSV 表头无法识别 / Unrecognised CSV headers")
    shots = []
    for index, row in enumerate(rows[1:], 1):
        def cell(name: str) -> str:
            pos = columns.get(name)
            return str(row[pos]).strip() if pos is not None and pos < len(row) else ""
        scene = cell("scene")
        description = cell("description")
        if not scene and not description:
            continue
        try:
            shot_id = int(float(cell("id") or index))
        except ValueError:
            shot_id = index
        shots.append({
            "id": shot_id,
            "scene_no": _scene_no(scene, index),
            "scene": scene,
            "shot_type": cell("shot_type"),
            "angle": cell("angle"),
            "movement": cell("movement"),
            "lens": cell("lens"),
            "duration": cell("duration"),
            "description": description,
            "dialogue": cell("dialogue"),
            "lighting": cell("lighting"),
            "sound": cell("sound"),
            "purpose": cell("purpose"),
            "transition": cell("transition"),
        })
    if not shots:
        raise HTTPException(status_code=400, detail="CSV 中没有可识别的镜头 / No shot rows found")
    scene_count = len({s["scene_no"] for s in shots})
    return {
        "kind": "storyboard",
        "filename": filename or "storyboard.csv",
        "shots": shots,
        "scene_count": scene_count,
        "chars": len(text),
        "logline": None,
    }


@router.post("/storyboard/parse")
async def parse_storyboard(file: UploadFile = File(...)):
    name = (file.filename or "").lower()
    if not name.endswith(".csv"):
        raise HTTPException(status_code=415, detail="请上传 CSV / Please upload a .csv storyboard")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="文件是空的 / The file is empty")
    if len(raw) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="文件超过 5 MB / File is larger than 5 MB")
    return _parse(raw, file.filename or "storyboard.csv")
