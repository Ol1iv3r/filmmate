#!/usr/bin/env python3
"""按片名重配原片：清掉当前匹配（假原片/静态图/错片），用搜索页通道重新匹配并抽帧。

用法：.venv/bin/python scripts/fix_entries.py "小丑,摔跤吧！爸爸"
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_catalog as bc  # noqa: E402


def main():
    titles = [x.strip() for x in (sys.argv[1] if len(sys.argv) > 1 else "").split(",") if x.strip()]
    state = bc.load_state()
    failed = state.setdefault("failed_bvids", [])
    bili = bc.Bili()
    for title in titles:
        found = None
        for key, item in state["entries"].items():
            if item["entry"].get("title_zh") == title:
                found = (key, item)
                break
        if not found:
            print("skip（库中无此条）", title)
            continue
        key, item = found
        entry = item["entry"]
        if item.get("match") and item["match"]["bvid"] not in failed:
            failed.append(item["match"]["bvid"])
        item["match"] = None
        item["frames"] = []
        item["frame_distinct"] = 0
        bc.save_state(state)
        match = bc.resolve_entry(bili, entry, entry["kind"], None, set(failed))
        if not match:
            print("✗", title, "没有找到合格原片")
            continue
        item["match"] = match
        runtime = float(entry.get("runtime_min") or 0)
        expected = runtime * 60 if runtime else None
        frames = bc.extract_stills(bili, match["bvid"], match["cid"],
                                   bc.FRAME_ROOT / match["bvid"], count=10, expected_sec=expected)
        item["frames"] = frames
        item["frame_distinct"] = bc.verify_distinct(bc.FRAME_ROOT / match["bvid"], frames) if frames else 0
        print("✓", title, "->", match["video_title"][:46], "| dur", match["video_duration_sec"],
              "| frames", len(frames), "| distinct", item["frame_distinct"])
        bc.save_state(state)
    bc.save_state(state)


if __name__ == "__main__":
    main()
