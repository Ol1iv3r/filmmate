#!/usr/bin/env python3
"""为「剧本 + 原片」库里的每部电影抽取真实静帧。

运行：python3 scripts/build_frames.py [--count 6]
输出：
  - static/frames/<bvid>/frame-01.jpg ...
  - 回写 data/library/films_scripted.json 的 frames 字段
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import frames  # noqa: E402
LIB = ROOT / "data" / "library" / "films_scripted.json"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=6)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    data = json.loads(LIB.read_text(encoding="utf-8"))
    ok = skipped = failed = 0
    for film in data["films"]:
        bvid = film["bvid"]
        if film.get("frames") and not args.force:
            skipped += 1
            continue
        try:
            urls = frames.extract_frames(bvid, count=args.count)
        except Exception as exc:  # noqa: BLE001
            print(f"✗ {film['title']}: {exc}")
            failed += 1
            continue
        if not urls:
            print(f"✗ {film['title']}: 没有可用帧")
            failed += 1
            continue
        film["frames"] = urls
        ok += 1
        print(f"✓ {film['title']}: {len(urls)} 帧")

    data["frames_verified_at"] = __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc
    ).astimezone().isoformat(timespec="seconds")
    LIB.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n完成：新增 {ok}，跳过 {skipped}，失败 {failed}")


if __name__ == "__main__":
    main()
