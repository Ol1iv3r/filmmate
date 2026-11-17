#!/usr/bin/env python3
"""Generate an English edition of data/library/catalog.json.

The Chinese catalog is the source of truth. This script translates the
controlled fields and synopses with the configured chat model and writes
data/library/catalog_en.json. Safe to re-run: already-translated ids are kept.

Usage:
    .venv/bin/python scripts/translate_catalog.py
    .venv/bin/python scripts/translate_catalog.py --batch 8 --limit 40
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import llm  # noqa: E402
SOURCE = ROOT / "data" / "library" / "catalog.json"
TARGET = ROOT / "data" / "library" / "catalog_en.json"
FIELDS = ("id", "title_zh", "title_en", "year", "genre", "moods", "tags", "synopsis", "video_title")
KIND_EN = {
    "电影": "Film",
    "电视剧": "TV series",
    "长片": "Feature",
    "短片": "Short",
    "竖屏短剧": "Vertical drama",
    "广告/TVC": "Ad / TVC",
    "教程/产品演示": "Tutorial",
    "Vlog/美食": "Vlog / Food",
    "动画": "Animation",
}
PROMPT = """Translate the translatable fields of these film catalog entries into natural English.

Return JSON only, in this shape:
{"entries":[{"id":"D001","genre":["..."],"moods":["..."],"tags":["..."],"synopsis":"...","video_title":"..."}]}

Rules:
- Include every input id exactly once and keep ids unchanged.
- Translate genre, moods, tags and synopsis into idiomatic film-industry English.
- Keep tags as short searchable labels; do not add new facts.
- Translate video_title, preserving the film title and year.
- Do not translate ids, title_en, year or URLs.
- No markdown, no commentary.

Entries:
"""


async def translate_batch(entries: list[dict]) -> dict[str, dict]:
    payload = [{k: e.get(k) for k in FIELDS} for e in entries]
    user = PROMPT + json.dumps(payload, ensure_ascii=False)
    data = await llm.complete_json(
        [{"role": "system", "content": "You are a professional film catalog translator. Return JSON only."},
         {"role": "user", "content": user}],
        temperature=0.2,
    )
    translated = {}
    for item in data.get("entries", []) or []:
        if not isinstance(item, dict):
            continue
        entry_id = item.get("id")
        if entry_id:
            translated[entry_id] = item
    return translated


def load_existing() -> dict[str, dict]:
    if not TARGET.exists():
        return {}
    try:
        data = json.loads(TARGET.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    return {item.get("id"): item for item in data.get("titles", []) if item.get("id")}


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=int, default=10)
    parser.add_argument("--limit", type=int, default=0, help="translate at most N new entries")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    titles = source.get("titles", [])
    existing = load_existing()
    todo = [t for t in titles if t.get("id") not in existing]
    if args.limit:
        todo = todo[: args.limit]
    logging.info("catalog entries=%d existing=%d to_translate=%d", len(titles), len(existing), len(todo))

    for start in range(0, len(todo), args.batch):
        batch = todo[start:start + args.batch]
        logging.info("translating %d/%d: %s", start + len(batch), len(todo), batch[0].get("id"))
        try:
            translated = await translate_batch(batch)
        except Exception as exc:  # noqa: BLE001
            logging.error("batch failed (%s); rerun to retry these ids", exc)
            continue
        missing = [e.get("id") for e in batch if e.get("id") not in translated]
        if missing:
            logging.warning("missing ids: %s", missing)
        for entry in batch:
            item = translated.get(entry.get("id"))
            if not item:
                continue
            merged = dict(entry)
            for field in ("genre", "moods", "tags"):
                values = item.get(field)
                if isinstance(values, list) and values:
                    merged[field] = [str(x).strip() for x in values if str(x).strip()]
            for field in ("synopsis", "video_title"):
                value = item.get(field)
                if isinstance(value, str) and value.strip():
                    merged[field] = value.strip()
            merged["kind_en"] = KIND_EN.get(entry.get("kind", ""), entry.get("kind", ""))
            existing[entry["id"]] = merged

        out_titles = [existing.get(t["id"], t) for t in titles if t.get("id") in existing]
        out = {
            "name": "Filmmate Film Catalog (English edition)",
            "description": "English metadata generated from data/library/catalog.json",
            "source": "data/library/catalog.json",
            "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "count": len(out_titles),
            "titles": out_titles,
        }
        TARGET.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        logging.info("saved %d entries to %s", len(out_titles), TARGET)

    logging.info("done: %s", TARGET)


if __name__ == "__main__":
    asyncio.run(main())
