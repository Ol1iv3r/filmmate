#!/usr/bin/env python3
"""严格校验现有匹配，清掉「标题像原片、内容不是原片」的条目，并尝试换更好的原片。

规则：
 1) 标题/内容词：解说/一口气/评论音轨/OST/BGM/剧场版/真人秀/音频/广播/花絮/预告/片段/混剪/盘点/拉片/速看/玩片/放映室…
 2) 时长比例：单片类 0.86–1.20；剧集需「单集 0.84–1.30」或「整剧合集 0.85–1.15」；短剧放宽
 3) 片名位置：片名在开头/《》/【】/英文名命中，否则要求时长高度吻合（0.95–1.05）
 4) 静帧重复：10 张里互不相同 < 5 张 → 判定静态图文
 5) 去重：同名作品只保留一条（按 KIND_ORDER 优先级）

用法：
  .venv/bin/python scripts/strict_clean.py            # 预览
  .venv/bin/python scripts/strict_clean.py --apply    # 清空 + 自动重配 + 抽帧
"""
import argparse
import re
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_catalog as bc  # noqa: E402

ONE_OFF = ("电影", "长片", "短片", "广告/TVC", "教程/产品演示", "Vlog/美食", "动画")
SERIES = ("电视剧", "竖屏短剧")
KIND_ORDER = list(bc.KINDS)
BAD = re.compile(
    r"解说|一口气|评论音轨|原声大碟|(?<![a-z])ost(?![a-z])|BGM|剧场版|真人秀|音频|广播剧|有声书|"
    r"花絮|预告|片花|片段|混剪|盘点|排行|拉片|速看|玩片|放映室|观影|reaction|陪看|手语|无障碍|mp3|"
    r"图文|壁纸|幻灯片|PPT|AI制作|AI短剧|翻拍|蹭热度|影评|解读|解析|吐槽|"
    r"十分钟|几分钟|速览|完整合集|全集解说|万字|详解|精讲|通关|名场面|资源|访谈|看完|抢先看|"
    r"全流程|全收集|玄学破案|黑暗森林|多空大战|灵魂救赎|高分电视剧|高分韩剧",
    re.I)
RELAXED = ("广告/TVC", "教程/产品演示", "Vlog/美食")  # 用户标注时长多为约数，放宽比例
MULTI_EP = re.compile(r"\d+\s*[-~–至]\s*\d+\s*集|第\s*\d+\s*[-~–至]\s*\d+\s*集")


def check(entry, match, frame_distinct):
    """返回 (是否可疑, 原因列表)。"""
    kind = entry["kind"]
    vt = match.get("video_title") or ""
    dur = int(match.get("video_duration_sec") or 0)
    runtime = float(entry.get("runtime_min") or 0) * 60
    episodes = int(entry.get("episodes") or 0)
    reasons = []
    if BAD.search(vt):
        reasons.append("可疑内容词:" + BAD.search(vt).group())
    if kind in ONE_OFF:
        if kind in RELAXED:
            if runtime and dur:
                ratio = dur / runtime
                if ratio < 0.50 or ratio > 2.00:
                    reasons.append(f"时长比例{ratio:.2f}")
        else:
            if runtime and dur:
                ratio = dur / runtime
                if ratio < 0.86 or ratio > 1.25:
                    reasons.append(f"时长比例{ratio:.2f}")
            placed = bc.title_placed(vt, entry.get("title_zh"))
            en = (entry.get("title_en") or "").strip()
            en_hit = bool(en) and len(en) >= 4 and bc.norm_text(en) in bc.norm_text(vt)
            ratio_close = runtime and dur and 0.90 <= dur / runtime <= 1.10
            if not placed and not en_hit and not ratio_close:
                reasons.append("片名不在标题主位")
            if MULTI_EP.search(vt):
                reasons.append("单片却是连集标题")
    elif kind == "电视剧":
        if runtime and dur:
            ratio_ep = dur / runtime
            ratio_total = dur / (runtime * episodes) if episodes else ratio_ep
            ok = (0.80 <= ratio_ep <= 1.40) or (0.85 <= ratio_total <= 1.15)
            if not ok:
                reasons.append(f"剧集时长比例 单集{ratio_ep:.2f}/整剧{ratio_total:.2f}")
            if episodes and MULTI_EP.search(vt) and not (0.85 <= ratio_total <= 1.15):
                reasons.append("连集合集但时长不匹配")
    else:  # 竖屏短剧：合集形态多，只靠内容词/静帧质量判断
        pass
    if frame_distinct is not None and frame_distinct < 5:
        reasons.append(f"静帧重复({frame_distinct}/10 张不重复)")
    return bool(reasons), reasons


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--no-resolve", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--force-titles", default="", help="强制清掉并重配的片名，逗号分隔")
    args = ap.parse_args()

    state = bc.load_state()
    failed = state.setdefault("failed_bvids", [])
    force = {x.strip() for x in (args.force_titles or "").split(",") if x.strip()}
    clear, seen_titles = [], {}
    for key, item in state["entries"].items():
        entry, match = item["entry"], item.get("match")
        if not match:
            continue
        distinct = item.get("frame_distinct")
        bad, reasons = check(entry, match, distinct if distinct is not None else len(item.get("frames") or []))
        if entry.get("title_zh") in force:
            bad = True
            reasons.append("人工指定重配")
        # 跨类目去重：同名只留优先级最高的那条
        title_key = bc.norm_text(entry.get("title_zh"))
        if title_key:
            prev = seen_titles.get(title_key)
            order = KIND_ORDER.index(entry["kind"]) if entry["kind"] in KIND_ORDER else 99
            if prev is not None:
                prev_item, prev_order = prev
                if prev_order <= order:
                    bad = True
                    reasons.append("与其它类目重复")
                else:
                    # 当前更优先：把之前那条也清掉
                    bad = True
                    reasons.append("保留更优先类目副本")
            else:
                seen_titles[title_key] = (item, order)
        if bad:
            clear.append((key, entry, match, reasons))
    print(f"可疑 {len(clear)} 条 / 已匹配 {sum(1 for v in state['entries'].values() if v.get('match'))} 条")
    print(dict(Counter(k[1]["kind"] for k in clear)))
    for key, entry, match, reasons in clear:
        print(f'  {entry["kind"]:6s} {entry["title_zh"]:14s} | {match["video_title"][:44]:44s} | {"；".join(reasons)}')
    if not args.apply:
        print("\n预览模式：加 --apply 才会清空并重新匹配")
        return

    for key, entry, match, reasons in clear:
        item = state["entries"][key]
        if match["bvid"] not in failed:
            failed.append(match["bvid"])
        item["match"] = None
        item["frames"] = []
        item["frame_distinct"] = 0
    bc.save_state(state)
    if args.no_resolve:
        return

    # 重新匹配被清掉的条目
    todo = [k for k, _, _, _ in clear]
    bili = bc.Bili()
    print(f"\n重新匹配 {len(todo)} 条…", flush=True)
    exclude = set(failed)
    lock = __import__("threading").Lock()

    def work(key):
        item = state["entries"][key]
        entry = item["entry"]
        try:
            match = bc.resolve_entry(bili, entry, entry["kind"], None, exclude)
        except Exception:  # noqa: BLE001
            return key, None, []
        if not match:
            return key, None, []
        frames = []
        try:
            if match.get("platform") == "YouTube":
                return key, match, []
            runtime = float(entry.get("runtime_min") or 0)
            expected = runtime * 60 if runtime else None
            if entry["kind"] in SERIES and entry.get("episodes"):
                total = expected * entry["episodes"] if expected else None
                if expected and match["video_duration_sec"] > expected * 1.12 and total:
                    expected = total if match["video_duration_sec"] > total * 1.05 else expected
            frames = bc.extract_stills(bili, match["bvid"], match["cid"],
                                       bc.FRAME_ROOT / match["bvid"], count=10, expected_sec=expected)
        except Exception:  # noqa: BLE001
            frames = []
        return key, match, frames

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(work, k) for k in todo]
        for future in as_completed(futures):
            key, match, frames = future.result()
            with lock:
                item = state["entries"][key]
                if match and len(frames) >= 10:
                    distinct = bc.verify_distinct(bc.FRAME_ROOT / match["bvid"], frames)
                    bad, reasons = check(item["entry"], match, distinct)
                    if bad:
                        print(f'  ⚠ {item["entry"]["title_zh"]} 新匹配仍可疑（{"；".join(reasons)}），丢弃', flush=True)
                        continue
                    item["match"] = match
                    item["frames"] = frames
                    item["frame_distinct"] = distinct
                    print(f'  ✓ {item["entry"]["title_zh"]} -> {match["video_title"][:40]}', flush=True)
                else:
                    print(f'  ✗ {item["entry"]["title_zh"]} 仍未找到合格原片', flush=True)
    bc.save_state(state)
    left = sum(1 for v in state["entries"].values() if v.get("match") and len(v.get("frames") or []) >= 10)
    print(f"\n完成：仍有 {left} 条可用")


if __name__ == "__main__":
    main()
