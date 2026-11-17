"""个人灵感库：用户把自己想参考的电影/短片加进来（Bilibili 链接 + 情绪标签）。

存储：data/personal/films.json（本机数据，已 .gitignore，不进仓库）
- 添加时若给的是 Bilibili 链接，会用公开 API 补全标题/封面/时长；
- 只存元数据与用户自己的标签，不下载视频。
"""
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
STORE = BASE_DIR / "data" / "personal" / "films.json"
UA_FULL = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
UA = {"User-Agent": UA_FULL, "Referer": "https://www.bilibili.com/",
      "Accept": "application/json, text/plain, */*",
      "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
      "Origin": "https://www.bilibili.com"}

MAX_ITEMS = 200


def _load():
    if not STORE.exists():
        return {"films": []}
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {"films": []}


def _save(data):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def list_films():
    return _load().get("films", [])


def _bvid_from(url: str):
    m = re.search(r"(BV[0-9A-Za-z]{10})", url or "")
    return m.group(1) if m else None


def _fetch_bili(bvid: str):
    api = "https://api.bilibili.com/x/web-interface/view?" + urllib.parse.urlencode({"bvid": bvid})
    # B 站接口需要先拿 cookie（buvid3），否则会 412
    import http.cookiejar
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    try:
        req0 = urllib.request.Request("https://www.bilibili.com/", headers=UA)
        with opener.open(req0, timeout=5) as resp0:
            resp0.read(2048)
    except Exception:  # noqa: BLE001
        pass
    import time as _time
    data = {}
    for attempt in range(2):
        try:
            req = urllib.request.Request(api, headers=UA)
            with opener.open(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8")).get("data") or {}
            break
        except Exception:  # noqa: BLE001
            _time.sleep(1 + attempt * 2)
    if not data.get("bvid"):
        return None
    secs = int(data.get("duration", 0))
    return {
        "title": data.get("title", ""),
        "cover": (data.get("pic") or "").replace("http://", "https://"),
        "duration": f"{secs // 60}:{secs % 60:02d}",
        "duration_sec": secs,
        "owner": (data.get("owner") or {}).get("name", ""),
    }


def add_film(url: str, title: str = "", moods=None, script_text: str = "", script_name: str = ""):
    url = (url or "").strip()
    moods = [m.strip() for m in (moods or []) if str(m).strip()][:6]
    bvid = _bvid_from(url)
    ytid = _youtube_id(url)
    meta = {}
    platform = "Bilibili"
    if bvid:
        try:
            meta = _fetch_bili(bvid) or {}
        except Exception:
            meta = {}
        url = f"https://www.bilibili.com/video/{bvid}"
    elif ytid:
        platform = "YouTube"
        try:
            meta = _fetch_youtube(ytid) or {}
        except Exception:
            meta = {"platform": "YouTube"}
        url = f"https://www.youtube.com/watch?v={ytid}"
    if not (title or meta.get("title")):
        raise ValueError("请至少填写片名，或提供可识别的 Bilibili / YouTube 链接")
    if not url:
        raise ValueError("请提供影片链接（支持 Bilibili / YouTube）")

    data = _load()
    films = data.get("films", [])
    if len(films) >= MAX_ITEMS:
        raise ValueError("个人灵感库已满（200 条）")
    if any(f.get("url") == url for f in films):
        raise ValueError("这部片已经在你的灵感库里了")

    frames = []
    if bvid:
        try:
            import frames as frame_lib
            frames = frame_lib.extract_frames(bvid, count=6)
        except Exception:  # noqa: BLE001
            frames = []
    if not frames and ytid:
        try:
            import frames as frame_lib
            frames = frame_lib.extract_video_frames(url, f"yt-{ytid}", count=6)
        except Exception:  # noqa: BLE001
            frames = []
    if not frames and meta.get("cover"):
        frames = [meta["cover"]]

    entry = {
        "id": bvid or f"personal-{int(datetime.now().timestamp())}",
        "title": title.strip() or meta.get("title", ""),
        "url": url,
        "cover": meta.get("cover", ""),
        "duration": meta.get("duration", ""),
        "duration_sec": meta.get("duration_sec", 0),
        "owner": meta.get("owner", ""),
        "platform": platform,
        "moods": moods or ["未分类"],
        "frames": frames,
        "script_name": script_name,
        "script_text": script_text[:100000],
        "source": "personal",
        "added_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    }
    films.append(entry)
    data["films"] = films
    _save(data)
    return entry


def remove_film(film_id: str):
    data = _load()
    films = [f for f in data.get("films", []) if f.get("id") != film_id]
    if len(films) == len(data.get("films", [])):
        return False
    data["films"] = films
    _save(data)
    return True


def _youtube_id(url: str):
    m = re.search(r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)([A-Za-z0-9_-]{11})", url or "")
    return m.group(1) if m else None


def _fetch_youtube(vid: str):
    """YouTube oEmbed：拿到标题/作者/封面（免费、无需 key）。"""
    import json as _json
    oembed = "https://www.youtube.com/oembed?" + urllib.parse.urlencode(
        {"url": f"https://www.youtube.com/watch?v={vid}", "format": "json"})
    req = urllib.request.Request(oembed, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = _json.loads(resp.read().decode("utf-8"))
    return {
        "title": data.get("title", ""),
        "cover": data.get("thumbnail_url", "") or f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
        "owner": data.get("author_name", ""),
        "platform": "YouTube",
    }


def update_visual(film_id: str, summary: str = "", tags=None, beats=None):
    data = _load()
    for film in data.get("films", []):
        if film.get("id") == film_id:
            film["visual_summary"] = (summary or "").strip()[:600]
            film["visual_tags"] = [str(t).strip() for t in (tags or []) if str(t).strip()][:12]
            film["visual_beats"] = [str(t).strip() for t in (beats or []) if str(t).strip()][:8]
            _save(data)
            return True
    return False


def update_frames(film_id: str, frames=None):
    data = _load()
    for film in data.get("films", []):
        if film.get("id") == film_id:
            film["frames"] = [str(x) for x in (frames or []) if str(x)]
            _save(data)
            return True
    return False


def update_style(film_id: str, summary: str = "", tags=None):
    data = _load()
    for film in data.get("films", []):
        if film.get("id") == film_id:
            film["style_summary"] = (summary or "").strip()[:200]
            film["style_tags"] = [str(t).strip() for t in (tags or []) if str(t).strip()][:8]
            _save(data)
            return True
    return False


def taste_profile(limit: int = 10) -> dict:
    """Return structured taste signals from the most recent saved films."""
    films = list_films()[-limit:]
    titles = [str(f.get("title") or "").strip() for f in films if f.get("title")]
    moods: list[str] = []
    tags: list[str] = []
    summaries: list[str] = []
    visual: list[str] = []
    for f in films:
        for value in f.get("moods") or []:
            value = str(value).strip()
            if value and value not in moods and value != "未分类":
                moods.append(value)
        for value in f.get("style_tags") or []:
            value = str(value).strip()
            if value and value not in tags:
                tags.append(value)
        if f.get("style_summary"):
            summaries.append(str(f["style_summary"]).strip())
        if f.get("visual_summary"):
            visual.append(str(f["visual_summary"]).strip())
        for value in f.get("visual_tags") or []:
            value = str(value).strip()
            if value and value not in tags:
                tags.append(value)
    return {"titles": titles, "moods": moods, "tags": tags, "summaries": summaries,
            "visual": visual}


def taste_context(limit: int = 10, lang: str = "zh") -> str:
    """把用户收藏的参考片整理成给模型看的「品味上下文」。"""
    films = list_films()[-limit:]
    if not films:
        return ""
    en = lang == "en"
    lines = [("【用户已收藏的参考片：这是本次创作最强的风格约束，必须优先贴近】" if not en else
              "【User's saved reference films — the strongest style constraint for this task】")]
    for f in films:
        parts = [f.get("title") or "", f.get("platform") or ""]
        if f.get("style_tags"):
            parts.append(("标签：" if not en else "Tags: ") + ("、".join(f["style_tags"]) if not en else ", ".join(f["style_tags"])))
        if f.get("moods"):
            parts.append(("情绪：" if not en else "Moods: ") + ("/".join(f["moods"])))
        if f.get("visual_summary"):
            parts.append(("画面：" if not en else "On screen: ") + f["visual_summary"])
        if f.get("style_summary"):
            parts.append(f["style_summary"])
        if f.get("url"):
            parts.append(("链接：" if not en else "Link: ") + f["url"])
        lines.append("- " + (" | ".join([p for p in parts if p]) if en else " ｜ ".join([p for p in parts if p])))
    if en:
        lines.append("Treat these references as hard style anchors: match their texture, mood, themes and pacing. "
                     "If the user's wording conflicts with them, prioritise the references and explain the synthesis.")
    else:
        lines.append("把以上参考片当作硬性风格锚点：贴近其影像质感、情绪、母题与节奏；"
                     "如果用户描述与参考片冲突，优先参考片并说明如何融合。")
    return "\n".join(lines)
