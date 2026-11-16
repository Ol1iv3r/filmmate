#!/usr/bin/env python3
"""把用户补充的 CSV（YouTube 检索链接）并入 catalog：
1) 先按片名去重（已在库里的跳过）；
2) 先试 Bilibili 原片（复用 build_catalog 的匹配/校验/抽帧）；
3) Bilibili 找不到时，走 YouTube：yt-dlp 检索 → 校验标题/时长 → 解析 YouTube storyboard 抽 10 张静帧。

用法：
  .venv/bin/python scripts/add_catalog_rows.py "/path/to/catalog_20 (1).csv" [--limit N] [--only-bili]
"""
import argparse
import csv
import html as html_mod
import io
import json
import math
import random
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_catalog as bc  # noqa: E402
from PIL import Image, ImageFilter  # noqa: E402

KIND_MAP = {
    "短片": "短片", "竖屏短剧": "竖屏短剧", "广告/TVC": "广告/TVC",
    "教程/产品演示": "教程/产品演示", "Vlog/美食": "Vlog/美食", "动画": "动画",
}
GENRE_BY_KIND = {
    "短片": ["短片"], "竖屏短剧": ["竖屏短剧"], "广告/TVC": ["广告"],
    "教程/产品演示": ["产品演示"], "Vlog/美食": ["美食", "Vlog"], "动画": ["动画短片"],
}
YT_UA = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
}


# ------------------------------------------------------------------ 解析 CSV
def parse_minutes(text):
    m = re.search(r"(\d+(?:\.\d+)?)", str(text or ""))
    return int(round(float(m.group(1)))) if m else 0


def split_list(text, seps=r"[,/、|]"):
    if not text:
        return []
    return [x.strip() for x in re.split(seps, str(text)) if x.strip()]


def csv_rows_to_entries(path):
    entries = []
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
    for i, row in enumerate(rows):
        kind = KIND_MAP.get((row.get("种类") or "").strip())
        if not kind:
            continue
        zh = (row.get("中文名") or "").strip()
        en = (row.get("英文名") or "").strip()
        runtime = parse_minutes(row.get("时长"))
        tags = split_list(row.get("Tag"))
        moods = split_list(row.get("情绪"))
        genre = GENRE_BY_KIND.get(kind, ["短片"])
        queries = []
        if kind == "广告/TVC":
            queries = [zh + " 广告", zh + " TVC", zh]
        elif kind == "教程/产品演示":
            queries = [zh + " 演示", zh + " 官方", en]
        elif kind == "Vlog/美食":
            queries = [zh + " 美食", zh, en]
        elif kind == "动画":
            queries = [zh + " 动画短片", zh + " 动画", en]
        else:
            queries = [zh + " 完整版", zh, en]
        queries = [q for q in dict.fromkeys(queries) if q]
        entries.append({
            "csv_id": row.get("编号") or f"X{i}",
            "kind": kind,
            "title_zh": zh,
            "title_en": en,
            "year": int(row.get("年份") or 0) or None,
            "runtime_min": runtime,
            "episodes": None,
            "duration_label": (row.get("时长") or "").strip(),
            "moods": moods[:4] or ["温暖"],
            "genre": genre,
            "synopsis": (row.get("内容梗概") or "").strip(),
            "tags": tags[:8],
            "search_queries": queries,
        })
    return entries


# ------------------------------------------------------------------ YouTube
def yt_fetch_text(url, timeout=40):
    last = None
    for _ in range(3):
        try:
            req = urllib.request.Request(url, headers=YT_UA)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", "ignore")
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(1.5)
    raise RuntimeError(str(last))


def yt_search(query, limit=5):
    import yt_dlp

    opts = {"quiet": True, "no_warnings": True, "skip_download": True,
            "noplaylist": True, "extract_flat": False, "socket_timeout": 20}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
    out = []
    for ent in (info.get("entries") or []):
        if not ent or not ent.get("id"):
            continue
        out.append({
            "id": ent.get("id"),
            "title": ent.get("title") or "",
            "duration": int(ent.get("duration") or 0),
            "channel": ent.get("channel") or ent.get("uploader") or "",
        })
    return out


def score_yt(entry, cand):
    zh = bc.norm_text(entry.get("title_zh"))
    en = bc.norm_text(entry.get("title_en"))
    vt = bc.norm_text(cand["title"])
    hit = 0.0
    if zh and zh in vt:
        hit = 1.0
    elif en and len(en) >= 4 and en in vt:
        hit = 0.95
    else:
        tokens = [t for t in re.split(r"\s+", (entry.get("title_en") or "").lower()) if len(t) > 2]
        if tokens:
            hit = 0.6 * sum(1 for t in tokens if bc.norm_text(t) in vt) / len(tokens)
    expected = (entry.get("runtime_min") or 0) * 60
    if expected and cand["duration"]:
        ratio = cand["duration"] / expected
        dur = 1.0 if 0.85 <= ratio <= 1.25 else (0.6 if 0.6 <= ratio <= 1.6 else 0.1)
    else:
        dur = 0.5
    return 0.7 * hit + 0.3 * dur


def yt_resolve(entry, exclude=None):
    queries = []
    en = (entry.get("title_en") or "").strip()
    zh = entry.get("title_zh") or ""
    if en:
        queries.append(en)
    if zh:
        queries.append(zh)
    if en:
        queries.append(en + " official video")
    if zh:
        queries.append(zh + " 完整")
    cands = []
    for q in dict.fromkeys(queries):
        try:
            for c in yt_search(q, limit=5):
                cands.append(c)
        except Exception:  # noqa: BLE001
            continue
        if cands:
            break
        time.sleep(0.4)
    if not cands:
        return None
    seen = set()
    ranked = []
    for c in cands:
        if c["id"] in seen:
            continue
        seen.add(c["id"])
        ranked.append((score_yt(entry, c), c))
    ranked.sort(key=lambda x: -x[0])
    for score, cand in ranked[:3]:
        if score < 0.55:
            continue
        try:
            meta = yt_watch_info(cand["id"])
        except Exception:  # noqa: BLE001
            continue
        if not meta.get("spec"):
            continue
        actual_dur = meta.get("duration") or cand["duration"]
        expected = (entry.get("runtime_min") or 0) * 60
        if expected and actual_dur:
            ratio = actual_dur / expected
            if not (0.55 <= ratio <= 1.75):
                continue
        score2 = round(0.6 * score + 0.4 * min(1.0, actual_dur / max(1, expected)) if expected else score, 3)
        return {
            "bvid": "yt" + cand["id"],
            "cid": None,
            "url": f"https://www.youtube.com/watch?v={cand['id']}",
            "video_title": meta.get("title") or cand["title"],
            "part": "",
            "page_no": 1,
            "page_count": 1,
            "owner": cand["channel"],
            "play": 0,
            "video_duration_sec": actual_dur,
            "match_score": round(score, 3),
            "title_score": round(score, 3),
            "duration_score": 1.0,
            "typename": "YouTube",
            "search_query": q,
            "match_note": "YouTube 原片（storyboard 抽帧）",
            "verified_at": bc.now_iso(),
            "platform": "YouTube",
            "spec": meta["spec"],
        }
    return None


def yt_watch_info(vid):
    page = yt_fetch_text(f"https://www.youtube.com/watch?v={vid}")
    spec = None
    m = re.search(r'"playerStoryboardSpecRenderer":\{"spec":"((?:[^"\\]|\\.)*)"', page)
    if m:
        spec = json.loads('"' + m.group(1) + '"')
    lm = re.search(r'"lengthSeconds":"(\d+)"', page)
    tm = re.search(r'<meta name="title" content="([^"]*)"', page)
    return {
        "spec": spec,
        "duration": int(lm.group(1)) if lm else 0,
        "title": html_mod.unescape(tm.group(1)) if tm else vid,
    }


def yt_spec_levels(spec):
    parts = spec.split("|")
    if len(parts) < 2:
        return []
    base = parts[0]
    levels = []
    for idx, raw in enumerate(parts[1:]):
        fields = raw.split("#")
        if len(fields) < 6:
            continue
        try:
            width, height, count, cols, rows, interval = (int(fields[0]), int(fields[1]),
                                                          int(fields[2]), int(fields[3]),
                                                          int(fields[4]), int(fields[5]))
        except ValueError:
            continue
        levels.append({"idx": idx, "base": base, "w": width, "h": height, "count": count,
                       "cols": cols, "rows": rows, "interval": interval,
                       "name": fields[6] if len(fields) > 6 else "",
                       "sig": fields[7] if len(fields) > 7 else ""})
    return levels


def _fetch_image(url, timeout=30):
    req = urllib.request.Request(url, headers=YT_UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return Image.open(io.BytesIO(resp.read())).convert("RGB")


def _dhash(im):
    small = im.convert("L").resize((9, 8), Image.LANCZOS)
    px = list(small.getdata())
    bits = 0
    for r in range(8):
        base = r * 9
        for c in range(8):
            bits = (bits << 1) | (1 if px[base + c] > px[base + c + 1] else 0)
    return bits


def yt_extract_stills(match, out_dir, count=10):
    levels = yt_spec_levels(match["spec"])
    if not levels:
        return []
    usable = [lv for lv in levels if lv["cols"] * lv["rows"] >= 4 and lv["interval"] > 0]
    if not usable:
        usable = [lv for lv in levels if lv["cols"] * lv["rows"] >= 4]
    if not usable:
        return []
    # 优先选分辨率最高的层级，但要求总帧数够 10
    usable.sort(key=lambda lv: (lv["w"] * lv["h"]))
    level = next((lv for lv in reversed(usable) if lv["count"] >= count), usable[-1])
    duration = max(1, match.get("video_duration_sec") or 0)
    per_sheet = max(1, level["cols"] * level["rows"])
    interval = level["interval"] or max(1, duration * 1000 // max(1, level["count"]))
    base = level["base"].replace("$L", str(level["idx"])).replace("$M", "M").replace("$N", "M{n}")
    if level.get("sig"):
        base += "&sigh=" + level["sig"]

    def sheet_url(n):
        return base.replace("{n}", str(n))

    targets = [duration * (0.08 + 0.86 * (i + 0.5) / count) for i in range(count)]
    plans, needed = [], []
    for t in targets:
        idx = int(t * 1000 / interval)
        idx = max(0, min(level["count"] - 1, idx))
        sheet = idx // per_sheet
        cell = idx % per_sheet
        plans.append({"idx": idx, "sheet": sheet, "cell": cell, "t": t})
        if sheet not in needed:
            needed.append(sheet)
    sheets = {}
    for n in needed[:12]:
        try:
            sheets[n] = _fetch_image(sheet_url(n))
        except Exception:  # noqa: BLE001
            continue

    def collect(use_features, threshold):
        picked, used_hashes = [], []
        for plan in plans:
            sheet = sheets.get(plan["sheet"])
            if sheet is None:
                continue
            row, col = divmod(plan["cell"], level["cols"])
            box = (col * level["w"], row * level["h"],
                   (col + 1) * level["w"], (row + 1) * level["h"])
            try:
                frame = sheet.crop(box)
            except Exception:  # noqa: BLE001
                continue
            score = 0.0
            if use_features:
                feat = bc.frame_features(frame)
                if not feat:
                    continue
                score = feat["score"]
            h = _dhash(frame)
            if threshold > 0 and any(bin(h ^ x).count("1") < threshold for x in used_hashes):
                continue
            used_hashes.append(h)
            picked.append({"t": plan["t"], "frame": frame, "score": score})
        return picked

    picked = collect(True, 8)
    if len(picked) < count:
        picked = collect(False, 3)
    if len(picked) < count:
        picked = collect(False, 0)
    if len(picked) < count:
        return []
    picked.sort(key=lambda x: x["t"])
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for i, item in enumerate(picked[:count], 1):
        frame = item["frame"]
        if min(frame.size) < 260:
            factor = max(2, int(math.ceil(260 / max(1, min(frame.size)))))
            frame = frame.resize((frame.width * factor, frame.height * factor), Image.LANCZOS)
        path = out_dir / f"{i:02d}.jpg"
        frame.save(path, "JPEG", quality=90)
        results.append({
            "n": i,
            "path": f"/static/frames/catalog/{out_dir.name}/{path.name}",
            "file": str(path.relative_to(ROOT)),
            "time_sec": int(item["t"]),
            "timecode": bc.sec_to_timecode(int(item["t"])),
            "score": item["score"],
            "size": list(frame.size),
        })
    return results


# ------------------------------------------------------------------ 主流程
def load_existing_titles(state):
    titles = set()
    for item in state["entries"].values():
        e = item["entry"]
        titles.add(bc.norm_text(e.get("title_zh")))
        titles.add(bc.norm_text(e.get("title_en")))
    return titles


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--only-bili", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    entries = csv_rows_to_entries(args.csv_path)
    state = bc.load_state()
    existing = load_existing_titles(state)
    # 去重：CSV 内部 + 与现有库
    todo, seen = [], set()
    for e in entries:
        key = bc.norm_text(e["title_zh"])
        key_en = bc.norm_text(e["title_en"])
        if key in existing or (key_en and key_en in existing):
            continue
        if key in seen:
            continue
        seen.add(key)
        todo.append(e)
    if args.limit:
        todo = todo[: args.limit]
    print(f"CSV {len(entries)} 条，去重后新增 {len(todo)} 条", flush=True)

    bili = bc.Bili()
    lock = __import__("threading").Lock()
    done = 0

    yt_first = ("广告/TVC", "教程/产品演示", "Vlog/美食")

    def work(entry):
        kind = entry["kind"]
        match = None
        platform = "Bilibili"
        # YouTube 原生内容：先 YouTube，省掉注定失败的 B 站搜索
        if kind in yt_first and not args.only_bili:
            try:
                match = yt_resolve(entry)
                platform = "YouTube"
            except Exception:  # noqa: BLE001
                match = None
        if not match:
            try:
                match = bc.resolve_entry(bili, entry, kind, None, None)
            except Exception:  # noqa: BLE001
                match = None
        if not match and kind not in yt_first and not args.only_bili:
            try:
                match = yt_resolve(entry)
                platform = "YouTube"
            except Exception:  # noqa: BLE001
                match = None
        if not match:
            return entry, None, None, None
        frames = []
        try:
            if match.get("platform") == "YouTube":
                frames = yt_extract_stills(match, bc.FRAME_ROOT / match["bvid"], count=10)
            else:
                runtime = float(entry.get("runtime_min") or 0)
                frames = bc.extract_stills(bili, match["bvid"], match["cid"],
                                           bc.FRAME_ROOT / match["bvid"], count=10,
                                           expected_sec=runtime * 60 if runtime else None)
        except Exception:  # noqa: BLE001
            frames = []
        distinct = bc.verify_distinct(bc.FRAME_ROOT / match["bvid"], frames) if frames else 0
        return entry, match, frames, distinct

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(work, e) for e in todo]
        for future in as_completed(futures):
            entry, match, frames, distinct = future.result()
            with lock:
                done += 1
                if not match or len(frames or []) < 10:
                    print(f"  ✗ {entry['csv_id']} {entry['title_zh']} 未找到原片", flush=True)
                    continue
                entry["platform"] = match.get("platform") or "Bilibili"
                entry["csv_id"] = entry["csv_id"]
                key = "add:" + entry["csv_id"] + ":" + str(int(time.time() * 1000))[-5:]
                match.pop("spec", None)
                state["entries"][key] = {
                    "entry": entry, "match": match,
                    "frames": frames, "frame_distinct": distinct,
                }
                print(f"  ✓ {entry['csv_id']} {entry['title_zh']} [{entry['platform']}] "
                      f"{match['video_title'][:34]} | {distinct}/10 不重复帧", flush=True)
                if done % 5 == 0:
                    bc.save_state(state)
    bc.save_state(state)
    ok = sum(1 for v in state["entries"].values() if v.get("match") and len(v.get("frames") or []) >= 10
             and bc.norm_text(v["entry"].get("title_zh")) in {bc.norm_text(e["title_zh"]) for e in todo})
    print(f"完成：新增可用 {ok}/{len(todo)} 条", flush=True)


if __name__ == "__main__":
    main()
