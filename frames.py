"""从 Bilibili 官方 videoshot（10×10 帧拼图）裁出真实影片静帧。

不下载整部影片，只用播放器预览帧：
  GET /x/player/videoshot?bvid=...&cid=...&index=1
  -> data.image = ["//bimp.hdslb.com/...-0001.jpg", ...]

每张拼图 10×10 帧（默认 480×270/帧）。我们按时间轴均匀取 N 帧，
裁切后存到 static/frames/<bvid>/frame-01.jpg。
"""
import http.cookiejar
import io
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

BASE_DIR = Path(__file__).resolve().parent
FRAME_ROOT = BASE_DIR / "static" / "frames"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Referer": "https://www.bilibili.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
    "Origin": "https://www.bilibili.com",
}


def _opener():
    """Bilibili returns 412 unless the request has a real homepage cookie."""
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    try:
        req = urllib.request.Request("https://www.bilibili.com/", headers=HEADERS)
        with opener.open(req, timeout=8) as resp:
            resp.read(1024)
    except Exception:  # noqa: BLE001
        pass
    return opener


def _get(url, binary=False, timeout=20, opener=None):
    opener = opener or _opener()
    req = urllib.request.Request(url, headers=HEADERS)
    with opener.open(req, timeout=timeout) as resp:
        data = resp.read()
    return data if binary else data.decode("utf-8", "ignore")


def cid_for(bvid):
    data = json.loads(_get(f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}")).get("data") or {}
    pages = data.get("pages") or []
    return pages[0].get("cid") if pages else None


def extract_frames(bvid, count=6, cid=None):
    """返回可访问的 URL 列表（/static/frames/...）；失败返回空列表。"""
    opener = _opener()
    if not cid:
        view = json.loads(_get(f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}", opener=opener)).get("data") or {}
        pages = view.get("pages") or []
        cid = pages[0].get("cid") if pages else None
    if not cid:
        return []
    out_dir = FRAME_ROOT / bvid
    out_dir.mkdir(parents=True, exist_ok=True)

    query = urllib.parse.urlencode({"bvid": bvid, "cid": cid, "index": 1})
    payload = json.loads(_get(f"https://api.bilibili.com/x/player/videoshot?{query}", opener=opener))
    data = payload.get("data") or {}
    sprites = data.get("image") or []
    if not sprites:
        return []
    x_len = int(data.get("img_x_len", 10))
    y_len = int(data.get("img_y_len", 10))
    fw = int(data.get("img_x_size", 480))
    fh = int(data.get("img_y_size", 270))
    per_sprite = x_len * y_len
    total = per_sprite * len(sprites)

    # 均匀取帧（避开首尾黑场）
    positions = [int(total * (i + 0.6) / (count + 0.2)) for i in range(count)]
    positions = [min(total - 1, max(0, p)) for p in positions]

    saved = []
    for idx, pos in enumerate(positions, 1):
        sprite_index = pos // per_sprite
        if sprite_index >= len(sprites):
            break
        local = pos % per_sprite
        row, col = divmod(local, x_len)
        url = sprites[sprite_index]
        if url.startswith("//"):
            url = "https:" + url
        raw = _get(url, binary=True, opener=opener)
        image = Image.open(io.BytesIO(raw)).convert("RGB")
        box = (col * fw, row * fh, (col + 1) * fw, (row + 1) * fh)
        frame = image.crop(box)
        path = out_dir / f"frame-{idx:02d}.jpg"
        frame.save(path, "JPEG", quality=85)
        saved.append(f"/static/frames/{bvid}/{path.name}")
    return saved


def extract_video_frames(url: str, key: str, count: int = 6) -> list[str]:
    """Fallback for YouTube/other links: download a tiny video and sample frames.

    Used only when the Bilibili sprite endpoint is unavailable; keeps the
    reference library's stills real instead of showing only a thumbnail.
    """
    import contextlib
    import io
    import shutil
    import subprocess
    import tempfile

    key = re.sub(r"[^0-9A-Za-z_-]+", "", key or "")[:80]
    if not key:
        return []
    try:
        import yt_dlp
    except Exception:  # noqa: BLE001
        return []
    ffmpeg = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
    if not Path(ffmpeg).exists():
        return []
    out_dir = FRAME_ROOT / key
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            opts = {
                "quiet": True,
                "noplaylist": True,
                "no_warnings": True,
                "socket_timeout": 15,
                "format": "worstvideo[ext=mp4]/worst[ext=mp4]/18/best",
                "outtmpl": str(Path(tmp) / "source.%(ext)s"),
                "noprogress": True,
            }
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    source = Path(ydl.prepare_filename(info))
            duration = float(info.get("duration") or 30)
            saved = []
            for idx in range(1, count + 1):
                stamp = max(0.2, duration * idx / (count + 1))
                target = out_dir / f"frame-{idx:02d}.jpg"
                subprocess.run(
                    [ffmpeg, "-y", "-ss", f"{stamp:.2f}", "-i", str(source),
                     "-frames:v", "1", "-vf", "scale=480:-2", str(target)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=25,
                )
                if target.exists() and target.stat().st_size:
                    saved.append(f"/static/frames/{key}/{target.name}")
            return saved
    except Exception:  # noqa: BLE001
        return []
