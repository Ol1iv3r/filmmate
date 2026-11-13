#!/usr/bin/env python3
"""构建「剧本 + 原片」双源电影库。

每部电影必须同时满足：
  1. scriptslug.com 有剧本页，且 PDF 直链可访问（HTTP 200）；
  2. Bilibili 搜索能找到该片原片（时长 > 40 分钟），并通过 view API 校验。

只保存来源可核验的字段。人工片单在 data/library/curated_script_films.json（含情绪标签）。

运行：python3 scripts/build_scripted_films.py
输出：data/library/films_scripted.json
"""
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CURATED = ROOT / "data" / "library" / "curated_script_films.json"
OUT = ROOT / "data" / "library" / "films_scripted.json"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Referer": "https://www.bilibili.com/"}

BAD_TITLE = re.compile(
    r"解说|拉片|影评|预告|混剪|速看|盘点|片段|cut|反应|reaction|解析|讲电影|游戏|攻略|原声|OST|"
    r"合集|动漫|漫画|剧集|一口气|剧情|推荐|细节|幕后|花絮|删减|彩蛋|影志|片单", re.I)
BAD_OWNER = re.compile(r"解说|说电影|说大片|影评|混剪|盘点|速看|剪辑|拉片")


def fetch(url, headers=None, timeout=20, retries=3):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers or HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read().decode("utf-8", "ignore")
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(0.8 + attempt)
    raise last


def check_script(slug):
    page = f"https://www.scriptslug.com/script/{slug}"
    pdf = f"https://assets.scriptslug.com/live/pdf/scripts/{slug}.pdf"
    status, _ = fetch(page)
    if status != 200:
        return None
    req = urllib.request.Request(pdf, headers=HEADERS, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            if resp.status != 200:
                return None
    except Exception:
        return None
    return {"page": page, "pdf": pdf}


def _js_string(raw):
    try:
        return json.loads('"' + raw + '"')
    except ValueError:
        return raw


def search_bilibili(keyword):
    url = "https://search.bilibili.com/all?" + urllib.parse.urlencode({"keyword": keyword})
    try:
        status, html = fetch(url)
    except Exception:
        return []
    if status != 200:
        return []
    items = []
    for m in re.finditer(r'bvid:"(BV[0-9A-Za-z]+)"', html):
        bvid = m.group(1)
        window = html[m.start(): m.start() + 3500]
        title = re.search(r'title:"((?:[^"\\]|\\.)*)"', window)
        pic = re.search(r'pic:"((?:[^"\\]|\\.)*)"', window)
        duration = re.search(r'duration:"([0-9+:]+)"', window)
        author = re.search(r'author:"((?:[^"\\]|\\.)*)"', window)
        play = re.search(r"play:(\d+)", window)
        if not (title and duration):
            continue
        items.append({
            "bvid": bvid,
            "title": _js_string(title.group(1)).replace('<em class="keyword">', "").replace("</em>", ""),
            "pic": "https:" + _js_string(pic.group(1)) if pic else "",
            "duration": duration.group(1),
            "author": _js_string(author.group(1)) if author else "",
            "play": int(play.group(1)) if play else 0,
        })
    return items


def dur_seconds(text):
    parts = [int(x) for x in text.split(":") if x.isdigit()]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return 0


def pick_candidates(items, zh, en, runtime_min, limit=3):
    """片长必须接近真实片长（±12 分钟），再按片名命中与播放量排序。"""
    zh_key = re.sub(r"[\s《》·：:（）()]", "", zh)
    en_key = en.lower()
    scored = []
    for item in items:
        title = item["title"]
        plain = re.sub(r"[\s《》·：:（）()]", "", title)
        secs = dur_seconds(item["duration"])
        if abs(secs - runtime_min * 60) > 15 * 60:
            continue
        if BAD_TITLE.search(title) or BAD_OWNER.search(item["author"]):
            continue
        hit = 0
        if zh_key and zh_key in plain:
            hit += 5
        if en_key and en_key in title.lower():
            hit += 3
        if not hit:
            continue
        # 标题越短通常越接近原片（长标题多是二创/解说）
        scored.append((hit - len(title) / 200, item["play"] / 1e7, item))
    scored.sort(key=lambda x: (-x[0], -x[1]))
    return [x[2] for x in scored[:limit]]


def verify(bvid):
    status, body = fetch(f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}")
    if status != 200:
        return None
    data = json.loads(body).get("data") or {}
    if not data.get("bvid"):
        return None
    return data


def main():
    curated = json.loads(CURATED.read_text(encoding="utf-8"))["films"]
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    results, misses = [], []

    for film in curated:
        slug, zh, en = film["slug"], film["title_zh"], film["title_en"]
        script = check_script(slug)
        if not script:
            misses.append({"title": zh, "reason": "scriptslug 无可用 PDF"})
            print(f"✗ {zh}: 无剧本")
            continue
        runtime = film.get("runtime_min") or 0
        candidates = []
        for query in (zh, f"{zh} 电影", f"{zh} 完整版", f"{zh} 中字", en):
            try:
                candidates.extend(search_bilibili(query))
            except Exception:  # noqa: BLE001
                continue
            time.sleep(0.8)
        picks = pick_candidates(candidates, zh, en, runtime)
        data = None
        for pick in picks:
            candidate = verify(pick["bvid"])
            if not candidate:
                continue
            secs = int(candidate.get("duration", 0))
            if candidate.get("videos", 0) != 1 or abs(secs - runtime * 60) > 15 * 60:
                continue
            data = candidate
            break
        if not data:
            misses.append({"title": zh, "reason": "无严格匹配的原片（片长/单 P/标题任一不符）"})
            print(f"✗ {zh}: 无合格原片（候选 {len(candidates)}）")
            time.sleep(1.0)
            continue
        secs = int(data.get("duration", 0))
        results.append({
            "id": f"bili-{data['bvid']}",
            "bvid": data["bvid"],
            "title": zh,
            "title_en": en,
            "year": slug.rsplit("-", 1)[-1],
            "url": f"https://www.bilibili.com/video/{data['bvid']}",
            "cover": (data.get("pic") or "").replace("http://", "https://"),
            "duration": f"{secs // 3600}:{secs % 3600 // 60:02d}:{secs % 60:02d}" if secs >= 3600
                        else f"{secs // 60}:{secs % 60:02d}",
            "duration_sec": secs,
            "owner": (data.get("owner") or {}).get("name", ""),
            "play": (data.get("stat") or {}).get("view", 0),
            "moods": film["moods"],
            "script": script,
            "sources": ["scriptslug", "bilibili"],
            "verified_at": now,
        })
        print(f"✓ {zh} -> {data['bvid']} ({results[-1]['duration']}, {results[-1]['play']} 播放)")
        time.sleep(1.2)

    payload = {
        "name": "Filmmate 剧本 + 原片双源库",
        "description": "每部电影都必须同时具备 scriptslug 剧本与 Bilibili 原片；人工挑选并按情绪标注。"
                       "只存可核验元数据，不含臆造的制作数据。",
        "verified_at": now,
        "curated": len(curated),
        "count": len(results),
        "films": results,
        "misses": misses,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n写入 {OUT.relative_to(ROOT)}：{len(results)}/{len(curated)} 部匹配成功")


if __name__ == "__main__":
    main()
