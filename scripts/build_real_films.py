#!/usr/bin/env python3
"""从 Bilibili 公开 API 构建「真实短片库」。

原则：
- 只存**可核验的元数据**：BV 号、标题、UP 主、时长、封面、简介、播放量、链接；
- 不编造导演、预算、档期、分镜、通告单——这些数据平台并不提供；
- 每条都记录 `verified_at`（本次通过 api.bilibili.com 校验的时间）。

做法：
1. 从几个已知短片 BV 号出发，用 related 接口扩展；
2. 过滤：时长 1–45 分钟、排除预告/花絮/解说/合集/混剪；
3. 用 view 接口补全简介、封面、UP 主、播放量；
4. 按「获奖/奥斯卡/短片/学生作品 + 播放量」打分，取前 N 条。

运行：python3 scripts/build_real_films.py [--limit 60]
输出：data/library/films_real.json
"""
import argparse
import json
import math
import re
import time
import urllib.parse
import urllib.request
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "library" / "films_real.json"

SEEDS = [
    "BV1WggVzJEMx",  # 动画短片《08年的梦》
    "BV1z94y1z7qX",  # 神奇飞书
    "BV1B3411Z77D",  # 雇佣人生
    "BV1Hu4y1976A",  # 洞穴
    # 真人短片 / 奥斯卡真人短片
    "BV19x411A7rn",  # 调音师
    "BV1Mp4y1E7yt",  # 邻居的窗
    "BV1Ft411q7zT",  # 沉默的孩子
    "BV148411e7w3",  # 肤色
    "BV1fp4y167eo",  # 无论如何我爱你
    "BV1qTqHBmEcf",  # 爱尔兰式告别
    "av418085771",   # 两个遥远的陌生人
    "av2198511",     # 精神分裂症
    # 经典动画短片
    "BV1U64y12765",  # 暴力云与送子鹳
    "BV1Fz411v7C5",  # 蓝雨伞之恋
    "av583615466",   # 纸人
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/122.0 Safari/537.36",
    "Referer": "https://www.bilibili.com/",
}

EXCLUDE = ["预告", "花絮", "解说", "合集", "混剪", "reaction", "直播回放", "完整电影", "速看", "盘点", "推荐榜"]
SIGNAL_WORDS = {
    "获奖": ["获奖", "奥斯卡", "戛纳", "柏林", "威尼斯", "安妮奖", "BAFTA", "金像奖", "金马", "first青年"],
    "学生作品": ["学生作品", "毕业作品", "学院奖", "北电", "中传"],
    "动画": ["动画", "animation", "定格", "stop motion", "二维", "三维", "CG"],
    "真人": ["真人", "剧情短片", "live action"],
}
TAG_WORDS = {
    "亲情": ["父亲", "母亲", "父子", "母女", "家人", "亲情", "外婆", "奶奶", "爷爷"],
    "战争": ["战争", "士兵", "战场"],
    "环保": ["环保", "自然", "地球", "污染"],
    "音乐": ["音乐", "钢琴", "小提琴", "歌声"],
    "校园": ["校园", "学校", "学生", "毕业"],
    "职场": ["职场", "上班", "打工", "公司"],
    "悬疑": ["悬疑", "谜", "真相"],
    "犯罪": ["犯罪", "小偷", "抢劫", "警察"],
    "女性": ["女性", "母亲", "女孩"],
    "历史": ["历史", "年代", "二战"],
    "爱情": ["爱情", "暗恋", "情侣", "恋爱", "告白"],
    "科幻": ["科幻", "机器人", "未来", "太空", "AI", "赛博"],
    "恐怖": ["恐怖", "惊悚", "灵异", "鬼"],
    "喜剧": ["喜剧", "搞笑", "幽默"],
    "治愈": ["治愈", "温暖", "暖心"],
    "反转": ["反转", "结局", "意想不到"],
    "默片": ["无对白", "默片", "没有台词"],
    "黑白": ["黑白"],
    "实验": ["实验", "抽象", "意识流"],
    "成长": ["成长", "青春", "少年", "童年"],
    "社会": ["社会", "现实", "底层", "打工"],
}


def api(path, **params):
    url = f"https://api.bilibili.com{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fmt_duration(sec):
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def collect(limit_candidates=220):
    seen, queue, found = set(SEEDS), deque(SEEDS), {}
    while queue and len(found) < limit_candidates:
        seed = queue.popleft()
        try:
            if seed.startswith("av"):
                data = api("/x/web-interface/view", aid=seed[2:]).get("data") or {}
            else:
                data = api("/x/web-interface/view", bvid=seed).get("data") or {}
        except Exception as exc:  # noqa: BLE001
            print("view 失败", seed, exc)
            continue
        bvid = data.get("bvid")
        duration = int(data.get("duration", 0))
        title = data.get("title", "")
        if 60 <= duration <= 2700 and not any(w in title.lower() for w in EXCLUDE):
            found[bvid] = data
        try:
            related = api("/x/web-interface/archive/related", bvid=bvid).get("data") or []
        except Exception:
            related = []
        for item in related:
            nb = item.get("bvid")
            if nb and nb not in seen:
                seen.add(nb)
                queue.append(nb)
        time.sleep(0.25)
    return found


def score(film):
    title = film.get("title", "")
    desc = film.get("desc", "")
    blob = title + " " + desc
    s = 0.0
    for _, words in SIGNAL_WORDS.items():
        if any(w.lower() in blob.lower() for w in words):
            s += 3
    stats = film.get("stat") or {}
    views = stats.get("view", 0)
    s += min(6, math.log10(max(views, 1)) * 1.2)
    if "短片" in title:
        s += 2
    if 120 <= film.get("duration", 0) <= 1200:
        s += 1.5  # 2–20 分钟更像「短片」
    return s


def tags_for(text):
    return [tag for tag, words in TAG_WORDS.items() if any(w.lower() in text.lower() for w in words)]


def canonical_title(title):
    """B 站标题常带 UP 主加的噱头，优先取《》里的片名。"""
    names = re.findall(r"《([^》]{1,40})》", title)
    if names:
        return names[0].strip()
    cleaned = re.sub(r"^(获奖无数！|全球播放\d+万|豆瓣\d+\.\d+)[，,！!\s]*", "", title)
    return cleaned.strip()[:48] or title[:48]


def clean_summary(desc):
    text = re.sub(r"https?://\S+", "", desc)
    text = re.sub(r"#\S+#?", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:180]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=60)
    args = parser.parse_args()

    found = collect()
    print(f"候选 {len(found)} 条")
    ranked = sorted(found.values(), key=score, reverse=True)

    # 去重：同一片名 + 时长接近（±90s）视为重复上传，保留播放量最高的
    deduped, keys = [], {}
    for f in ranked:
        key = (canonical_title(f.get("title", "")).lower(), round(int(f.get("duration", 0)) / 90))
        if key in keys:
            old = keys[key]
            if (f.get("stat") or {}).get("view", 0) > (old.get("stat") or {}).get("view", 0):
                deduped[deduped.index(old)] = f
                keys[key] = f
            continue
        keys[key] = f
        deduped.append(f)

    # 过滤标题党/无关条目
    junk = re.compile(r"播放\d+万|老泪纵横|完整电影|电影解说|预告片|混剪|盘点|推荐榜")
    deduped = [f for f in deduped if not junk.search(f.get("title", ""))]
    ranked = deduped[: args.limit]

    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    films = []
    for f in ranked:
        title = re.sub(r"\s+", " ", f.get("title", "")).strip()
        desc = re.sub(r"\s+", " ", f.get("desc") or "").strip()
        text = title + " " + desc
        signals = [name for name, words in SIGNAL_WORDS.items()
                   if any(w.lower() in text.lower() for w in words)]
        category = "动画" if "动画" in signals else ("真人" if "真人" in signals else "短片")
        films.append({
            "id": f"bili-{f['bvid']}",
            "bvid": f["bvid"],
            "title": canonical_title(title),
            "title_raw": title,
            "summary": clean_summary(desc),
            "url": f"https://www.bilibili.com/video/{f['bvid']}",
            "cover": (f.get("pic") or "").replace("http://", "https://"),
            "duration_sec": int(f.get("duration", 0)),
            "duration": fmt_duration(f.get("duration", 0)),
            "owner": (f.get("owner") or {}).get("name", ""),
            "pubdate": datetime.fromtimestamp(f.get("pubdate", 0)).strftime("%Y-%m-%d"),
            "description": desc[:400],
            "category": category,
            "signals": signals,
            "tags": tags_for(text),
            "stat": {
                "view": (f.get("stat") or {}).get("view", 0),
                "like": (f.get("stat") or {}).get("like", 0),
            },
            "source": "bilibili",
            "verified_at": now,
        })

    payload = {
        "name": "Filmmate 真实短片库",
        "description": "从 Bilibili 公开 API 校验的真实短片元数据（标题/时长/UP 主/简介/封面/链接）。"
                       "只引用来源，不编造制作数据；版权归原作者，仅用于学习参考。",
        "source": "api.bilibili.com",
        "verified_at": now,
        "count": len(films),
        "films": films,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"写入 {OUT.relative_to(ROOT)}：{len(films)} 部")
    for film in films[:10]:
        print(f"  {film['duration']:>8}  {film['category']}  {film['title'][:46]}  ({film['stat']['view']} 播放)")


if __name__ == "__main__":
    main()
