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
UA = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com/"}

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
    req = urllib.request.Request(api, headers=UA)
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8")).get("data") or {}
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
    meta = {}
    if bvid:
        try:
            meta = _fetch_bili(bvid) or {}
        except Exception:
            meta = {}
        url = f"https://www.bilibili.com/video/{bvid}"
    if not (title or meta.get("title")):
        raise ValueError("请至少填写片名，或提供可识别的 Bilibili 链接")
    if not url:
        raise ValueError("请提供影片链接（目前支持 Bilibili）")

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

    entry = {
        "id": bvid or f"personal-{int(datetime.now().timestamp())}",
        "title": title.strip() or meta.get("title", ""),
        "url": url,
        "cover": meta.get("cover", ""),
        "duration": meta.get("duration", ""),
        "duration_sec": meta.get("duration_sec", 0),
        "owner": meta.get("owner", ""),
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
