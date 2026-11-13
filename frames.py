"""从 Bilibili 官方 videoshot（10×10 帧拼图）裁出真实影片静帧。

不下载整部影片，只用播放器预览帧：
  GET /x/player/videoshot?bvid=...&cid=...&index=1
  -> data.image = ["//bimp.hdslb.com/...-0001.jpg", ...]

每张拼图 10×10 帧（默认 480×270/帧）。我们按时间轴均匀取 N 帧，
裁切后存到 static/frames/<bvid>/frame-01.jpg。
"""
import io
import json
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

BASE_DIR = Path(__file__).resolve().parent
FRAME_ROOT = BASE_DIR / "static" / "frames"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com/"}


def _get(url, binary=False, timeout=20):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    return data if binary else data.decode("utf-8", "ignore")


def cid_for(bvid):
    data = json.loads(_get(f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}")).get("data") or {}
    pages = data.get("pages") or []
    return pages[0].get("cid") if pages else None


def extract_frames(bvid, count=6, cid=None):
    """返回可访问的 URL 列表（/static/frames/...）；失败返回空列表。"""
    cid = cid or cid_for(bvid)
    if not cid:
        return []
    out_dir = FRAME_ROOT / bvid
    out_dir.mkdir(parents=True, exist_ok=True)

    query = urllib.parse.urlencode({"bvid": bvid, "cid": cid, "index": 1})
    payload = json.loads(_get(f"https://api.bilibili.com/x/player/videoshot?{query}"))
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
        raw = _get(url, binary=True)
        image = Image.open(io.BytesIO(raw)).convert("RGB")
        box = (col * fw, row * fh, (col + 1) * fw, (row + 1) * fh)
        frame = image.crop(box)
        path = out_dir / f"frame-{idx:02d}.jpg"
        frame.save(path, "JPEG", quality=85)
        saved.append(f"/static/frames/{bvid}/{path.name}")
    return saved
