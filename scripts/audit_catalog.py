#!/usr/bin/env python3
"""审计 catalog 构建状态：清掉「假原片」（解说/音频/无障碍/混剪/错片）与抽帧失败的匹配。
清理后下一轮 resolve / frames 会自动换一个上传版本重试。

用法：.venv/bin/python scripts/audit_catalog.py [--apply]
"""
import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_catalog as bc  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="真正清空；不加只预览")
    args = parser.parse_args()
    state = bc.load_state()
    failed = state.setdefault("failed_bvids", [])
    cleared = []
    for key, item in state["entries"].items():
        match = item.get("match")
        entry = item["entry"]
        if not match:
            continue
        dh = bc.duration_hit(match["video_duration_sec"], entry, entry["kind"])
        ok = bc.validate_match(entry, entry["kind"], match["video_title"],
                               match["video_duration_sec"], dh)
        frames_ok = len(item.get("frames") or []) >= 10
        if ok and frames_ok:
            continue
        reason = "假原片" if not ok else "抽帧失败"
        cleared.append((entry["kind"], entry["title_zh"], reason, match["video_title"][:44]))
        if args.apply:
            if match["bvid"] not in failed:
                failed.append(match["bvid"])
            item["match"] = None
            item["frames"] = []
    if args.apply:
        bc.save_state(state)
    print(("已清空 " if args.apply else "将清空 ") + str(len(cleared)) + " 条")
    print(dict(Counter(c[0] for c in cleared)))
    print(dict(Counter(c[2] for c in cleared)))
    for c in cleared:
        print("  ", c)


if __name__ == "__main__":
    main()
