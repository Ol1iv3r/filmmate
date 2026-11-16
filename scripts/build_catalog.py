#!/usr/bin/env python3
"""Filmmate 影视目录自动构建管线。

流程：
  1) resolve：读取 data/catalog_src/*.json（策展 agent 产出的候选片单），
     在 Bilibili 搜索原片/整剧/单集，按「标题命中 + 时长匹配 + 播放量 + 类型」打分，
     对候选做 view / videoshot 双重校验，得到可用 bvid + cid。
  2) frames：用 B 站官方 storyboard（videoshot 10x10 拼图）抽帧，
     自动挑「亮度/对比/边缘细节/肤色占比/色彩」综合分最高、且时间均匀分布的 10 张静帧，
     并裁掉黑边，存到 static/frames/catalog/<编号>/01..10.jpg。
  3) export：导出 data/library/catalog.json + docs 表格（csv/md/xlsx）+ HTML 画廊。

用法：
  .venv/bin/python scripts/build_catalog.py resolve --kinds 电影 --limit 3 --src /tmp/test_src.json
  .venv/bin/python scripts/build_catalog.py frames --kinds 电影 --limit 3
  .venv/bin/python scripts/build_catalog.py export
  .venv/bin/python scripts/build_catalog.py all
"""
import argparse
import bisect
import csv
import html
import io
import json
import math
import os
import random
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
import http.cookiejar
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageFilter

try:
    import numpy as np
except ImportError:  # 没有 numpy 也能跑，只是打分稍慢
    np = None

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "data" / "catalog_src"
BUILD_DIR = ROOT / "data" / "catalog_build"
STATE = BUILD_DIR / "matches.json"
FRAME_ROOT = ROOT / "static" / "frames" / "catalog"
CATALOG_JSON = ROOT / "data" / "library" / "catalog.json"
DOCS = ROOT / "docs"
LOG_PATH = BUILD_DIR / "build.log"

KINDS = ["电影", "电视剧", "长片", "短片", "竖屏短剧",
         "广告/TVC", "教程/产品演示", "Vlog/美食", "动画"]
CODE = {"电影": "D", "电视剧": "T", "长片": "F", "短片": "S", "竖屏短剧": "V",
        "广告/TVC": "G", "教程/产品演示": "U", "Vlog/美食": "L", "动画": "N"}
SRC_FILE = {"电影": "films", "电视剧": "series", "长片": "features", "短片": "shorts",
            "竖屏短剧": "verticals", "广告/TVC": "ads", "教程/产品演示": "tutorials",
            "Vlog/美食": "vlogs", "动画": "animation"}
SHORT_FORM_KINDS = ("电影", "长片", "短片", "广告/TVC", "教程/产品演示", "Vlog/美食", "动画")
TARGET_PER_KIND = 50

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Referer": "https://www.bilibili.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
    "Origin": "https://www.bilibili.com",
}

_LOG_LOCK = threading.Lock()


def log(msg):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    with _LOG_LOCK:
        print(line, flush=True)
        try:
            BUILD_DIR.mkdir(parents=True, exist_ok=True)
            with LOG_PATH.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass


# --------------------------------------------------------------------------- Bilibili
class Bili:
    """线程安全：每个线程独立 opener + 独立 cookie。

    B 站搜索接口对突发并发很敏感（HTTP 412），全局限速 + 412 长退避。
    """

    _RATE_LOCK = threading.Lock()
    _LAST_REQUEST = [0.0]
    MIN_INTERVAL = 2.6
    _API_BLOCKED_UNTIL = 0.0
    _PROXY_LOCK = threading.Lock()
    _LAST_PROXY = [0.0]
    PROXY_INTERVAL = 2.8
    _PAGE_LOCK = threading.Lock()
    _LAST_PAGE = [0.0]
    PAGE_INTERVAL = 1.8

    def __init__(self):
        self.local = threading.local()

    @classmethod
    def _throttle(cls):
        with cls._RATE_LOCK:
            wait = cls.MIN_INTERVAL - (time.time() - cls._LAST_REQUEST[0])
            if wait > 0:
                time.sleep(wait + random.uniform(0.0, 0.7))
            cls._LAST_REQUEST[0] = time.time()

    def _opener(self):
        op = getattr(self.local, "opener", None)
        if op is None:
            cj = http.cookiejar.CookieJar()
            op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
            self.local.opener = op
            self._bootstrap(op)
        return op

    def _bootstrap(self, opener):
        try:
            req = urllib.request.Request("https://www.bilibili.com/", headers={
                "User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})
            with opener.open(req, timeout=20) as r:
                r.read(4096)
        except Exception:  # noqa: BLE001
            pass
        time.sleep(random.uniform(0.1, 0.6))

    def _reset(self):
        self.local.opener = None

    def _request(self, url, binary=False, timeout=30):
        last = None
        for attempt in range(4):
            try:
                req = urllib.request.Request(url, headers=HEADERS)
                with self._opener().open(req, timeout=timeout) as r:
                    raw = r.read()
                return raw if binary else raw.decode("utf-8", "ignore")
            except urllib.error.HTTPError as exc:
                last = exc
                if exc.code in (403, 412, 429, 509, 503):
                    time.sleep(7.0 + attempt * 9.0)
                    self._reset()
                    continue
                raise
            except Exception as exc:  # noqa: BLE001
                last = exc
                time.sleep(1.2 + attempt * 2.0)
        raise RuntimeError(f"request failed: {url[:120]} ({last})")

    def get_json(self, url):
        raw = self._request(url)
        try:
            return json.loads(raw)
        except ValueError:
            return {}

    def search(self, keyword, page=1):
        """搜索视频：直连 API → 风控时改抓搜索结果页（换接口）→ 再失败走 r.jina.ai 代理。"""
        if time.time() < Bili._API_BLOCKED_UNTIL:
            return self._search_fallback(keyword, page)
        try:
            return self._search_direct(keyword, page)
        except Exception:  # noqa: BLE001
            Bili._API_BLOCKED_UNTIL = time.time() + 600
            log("  ! 直连搜索被风控，改用搜索结果页解析（10 分钟内）")
            return self._search_fallback(keyword, page)

    def _search_fallback(self, keyword, page=1):
        try:
            results = self.search_via_page(keyword, page)
            if results:
                return results
        except Exception:  # noqa: BLE001
            pass
        return self.search_via_proxy(keyword, page)

    def _throttle_page(self):
        with Bili._PAGE_LOCK:
            wait = Bili.PAGE_INTERVAL - (time.time() - Bili._LAST_PAGE[0])
            if wait > 0:
                time.sleep(wait + random.uniform(0.0, 0.7))
            Bili._LAST_PAGE[0] = time.time()

    @staticmethod
    def _grab_field(segment, key):
        m = re.search(r'\b' + key + r':(?:"((?:[^"\\]|\\.)*)"|([a-zA-Z]{1,2})(?=[,}]))', segment)
        if not m:
            return None
        if m.group(1) is not None:
            try:
                return json.loads('"' + m.group(1) + '"')
            except ValueError:
                return m.group(1)
        return None  # 变量引用（压缩后的 JS 字典），交给 view 接口补全

    def search_via_page(self, keyword, page=1):
        """抓 https://search.bilibili.com/all 的服务端直出数据（API 被 412 时的备用通道）。"""
        self._throttle_page()
        q = urllib.parse.quote(keyword)
        url = f"https://search.bilibili.com/all?keyword={q}&page={page}"
        page_html = self._request(url, timeout=30)
        if "验证码" in page_html[:3000] or 'bvid:"' not in page_html:
            raise RuntimeError("search page blocked or empty")
        out, seen = [], set()
        for m in re.finditer(r'bvid:"(BV[0-9A-Za-z]{10})"', page_html):
            bvid = m.group(1)
            if bvid in seen:
                continue
            seen.add(bvid)
            seg = page_html[m.end():m.end() + 460]
            title = self._grab_field(seg, "title")
            if not title or re.fullmatch(r"[a-zA-Z]{0,2}", title or ""):
                continue  # 标题被压缩成变量引用，无法判断相关性
            duration = self._grab_field(seg, "duration")
            play = self._grab_field(seg, "play")
            typename = self._grab_field(seg, "typename")
            out.append({
                "bvid": bvid,
                "title": re.sub(r"<.*?>", "", title),
                "duration_sec": parse_duration(duration),
                "play": int(play) if isinstance(play, str) and play.isdigit() else 0,
                "typename": typename or "",
                "author": "",
                "pubdate": 0,
                "description": "",
            })
        return out

    def _search_direct(self, keyword, page=1):
        self._throttle()
        q = urllib.parse.quote(keyword)
        data = self.get_json(
            "https://api.bilibili.com/x/web-interface/search/type"
            f"?search_type=video&keyword={q}&page={page}")
        if data.get("code") != 0:
            raise RuntimeError(f"search code {data.get('code')}")
        return self._parse_search(data)

    def search_via_proxy(self, keyword, page=1):
        q = urllib.parse.quote(keyword)
        api = ("https://api.bilibili.com/x/web-interface/search/type"
               f"?search_type=video&keyword={q}&page={page}")
        with Bili._PROXY_LOCK:
            wait = Bili.PROXY_INTERVAL - (time.time() - Bili._LAST_PROXY[0])
            if wait > 0:
                time.sleep(wait + random.uniform(0.0, 0.6))
            Bili._LAST_PROXY[0] = time.time()
        text = self._request("https://r.jina.ai/" + api, timeout=70)
        idx = text.find('{"code"')
        if idx < 0:
            return []
        try:
            data, _ = json.JSONDecoder().raw_decode(text[idx:])
        except ValueError:
            return []
        return self._parse_search(data)

    @staticmethod
    def _parse_search(data):
        result = ((data.get("data") or {}).get("result") or []
                  if data.get("code") == 0 else [])
        out = []
        for item in result:
            if not item.get("bvid"):
                continue
            out.append({
                "bvid": item.get("bvid"),
                "title": re.sub(r"<.*?>", "", item.get("title") or ""),
                "duration_sec": parse_duration(item.get("duration")),
                "play": int(item.get("play") or 0),
                "typename": item.get("typename") or "",
                "author": item.get("author") or "",
                "pubdate": item.get("pubdate") or 0,
                "description": item.get("description") or "",
            })
        return out

    def view(self, bvid):
        data = self.get_json(f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}")
        return data.get("data") if data.get("code") == 0 else None

    def videoshot(self, bvid, cid):
        data = self.get_json(
            "https://api.bilibili.com/x/player/videoshot"
            f"?bvid={bvid}&cid={cid}&index=1")
        payload = data.get("data") or {}
        if data.get("code") != 0 or not payload.get("image"):
            return None
        if not payload.get("index"):
            payload["index"] = []
        return payload

    def get_bytes(self, url):
        return self._request(url, binary=True, timeout=60)


def parse_duration(text):
    if not text:
        return 0
    parts = [p for p in str(text).strip().split(":") if p != ""]
    try:
        total = 0
        for part in parts:
            total = total * 60 + int(part)
        return total
    except ValueError:
        return 0


# --------------------------------------------------------------------------- 匹配
NEG_RE = re.compile(
    r"解说|影评|吐槽|混剪|盘点|推荐|排行|top\s*\d|预告|先导|花絮|幕后|片段|速看|拉片|"
    r"解析|讲解|速览|reaction|剧情简介|十分钟|几分钟|一口气|深度解读|影史|"
    r"第一次看|首次看|陪看|一起看|看剧|录屏|翻跳|串联|翻拍|仿拍|二创|配音|舞蹈|挑战|"
    r"速通|解读版|解说版|影视杂谈|观后感|影评人",
    re.I)
GOOD_TYPES = ("影视剪辑", "电影", "短片", "小剧场", "纪录片", "人文历史", "影视")

PUNCT_RE = re.compile(r"[\s\-_·・:：,，.。!！?？'\"“”‘’()（）\[\]【】《》<>/\\|+~—…]+")


def norm_text(text):
    if not text:
        return ""
    text = str(text).lower()
    return PUNCT_RE.sub("", text)


def title_hit(video_title, entry):
    """返回 0-1 的标题命中度。"""
    raw = str(video_title or "")
    vt = norm_text(raw)
    zh = norm_text(entry.get("title_zh"))
    en = norm_text(entry.get("title_en"))
    score = 0.0
    if zh and zh in vt:
        score = 1.0
    elif zh and len(zh) >= 2:
        chars = set(zh)
        score = 0.55 * (len(chars & set(vt)) / max(1, len(chars)))
    if en and len(en) >= 3 and en in vt:
        score = max(score, 0.95)
    # 短片名（≤4 字）极易命中无关视频：要求《片名》或标题以片名开头，否则降权
    if zh and len(zh) <= 4:
        if f"《{zh}》" not in raw and not raw.lstrip().startswith(zh):
            score *= 0.72
    return score


def duration_hit(video_sec, entry, kind):
    """返回 0-1 的时长匹配度。

    不对称容忍：B 站「完整版」常带片头/片尾/花絮，甚至访谈，因此比片长更长可以接受（逐步降分）；
    比片长还短则可能是剪辑版/片段，严格扣分。
    """
    if video_sec <= 0:
        return 0.1
    runtime = float(entry.get("runtime_min") or 0)
    episodes = int(entry.get("episodes") or 0)
    if runtime <= 0:
        return 0.5
    expected = runtime * 60
    options = [expected]
    if kind in ("电视剧", "竖屏短剧") and episodes:
        options.append(expected * episodes)
    if kind == "竖屏短剧":
        options.append(None)  # 整剧合集：10–250 分钟都算合理
    best = 0.0
    for option in options:
        if option is None:
            if 300 <= video_sec <= 15000:
                best = max(best, 0.62)
            continue
        ratio = video_sec / option
        if ratio >= 0.92:
            if ratio <= 1.06:
                val = 1.0
            elif ratio <= 1.20:
                val = 0.86
            elif ratio <= 1.40:
                val = 0.70
            elif ratio <= 1.62:
                val = 0.55
            else:
                val = 0.32
        else:
            if ratio >= 0.88:
                val = 0.90
            elif ratio >= 0.80:
                val = 0.62
            elif ratio >= 0.68:
                val = 0.30
            else:
                val = 0.05
        best = max(best, val)
    return best


def evaluate_candidate(entry, cand, kind):
    th = title_hit(cand["title"], entry)
    if th < 0.5:
        return None
    dh = duration_hit(cand["duration_sec"], entry, kind)
    if dh < 0.18:
        return None
    pop = min(1.0, math.log10(cand["play"] + 10) / 6.0)
    score = 0.58 * th + 0.30 * dh + 0.12 * pop
    tname = cand.get("typename") or ""
    if any(t in tname for t in GOOD_TYPES):
        score += 0.04
    if tname in ("影视杂谈", "预告·资讯", "资讯", "日常"):
        score -= 0.10
    title = cand["title"]
    if NEG_RE.search(title):
        score -= 0.34
    if title.count("《") >= 2:  # 标题里堆多个片名 = 混剪/串联/盘点
        score -= 0.26
    if len(re.findall(r"[+｜|、/]", title)) >= 3:  # 堆了多部片名
        score -= 0.10
    return {"score": round(score, 3), "title_score": round(th, 3),
            "duration_score": round(dh, 3), "cand": cand}


def build_queries(entry, kind):
    queries = [q for q in (entry.get("search_queries") or []) if q]
    zh = entry.get("title_zh") or ""
    defaults = {
        "电影": [f"{zh} 电影", f"{zh} 完整版"],
        "电视剧": [f"{zh} 第01集", f"{zh} 第一集", f"{zh} 全集"],
        "长片": [f"{zh} 纪录片", f"{zh} 完整版", f"{zh} 电影"],
        "短片": [f"{zh} 短片", f"{zh} 动画短片"],
        "竖屏短剧": [f"{zh} 短剧", f"{zh} 短剧 全集"],
    }.get(kind, [zh])
    for q in defaults:
        if q not in queries:
            queries.append(q)
    return queries[:4]


BAD_TITLE_RE = re.compile(
    r"无障碍|手语|原声带|mp3|有声书|广播剧|听书|学英语|解说|拉片|切片|混剪|速看|"
    r"预告|花絮|片段|盘点|排行榜|观影回|陪看|reaction|听歌|纯音频|吹替|日语配音|国语配音版|"
    r"分集剧情|剧情介绍|故事梗概|图文|幻灯片|PPT|(?<![a-z])ost(?![a-z])",
    re.I)


def title_placed(raw_title, title_zh):
    """片名是否出现在标题的「片名位」：开头 / 《》/【】/[] 里。"""
    raw = str(raw_title or "")
    zh = str(title_zh or "").strip()
    if not zh:
        return False
    for wrap in ("《" + zh + "》", "【" + zh + "】", "[" + zh + "]"):
        if wrap in raw:
            return True
    # 去掉开头的 【纪录片】/【高清】/（2023） 等前缀后，片名仍可能在片名位
    stripped = re.sub(r"^((\s*[【\[][^】\]]{0,14}[】\]])|(\s*[（(][^）)]{0,14}[）)])|\s)+", "", raw)
    head = norm_text(stripped[: max(14, len(zh) + 4)])
    return head.startswith(norm_text(zh))


def validate_match(entry, kind, video_title, actual_sec, actual_dh):
    """判断一个候选页是否真的能当作「原片」：标题位置 + 类型词 + 时长三条线。"""
    raw = str(video_title or "")
    if BAD_TITLE_RE.search(raw):
        return False
    if title_hit(raw, entry) < 0.62:
        return False
    zh = norm_text(entry.get("title_zh"))
    placed = title_placed(raw, entry.get("title_zh"))
    appears = bool(zh) and zh in norm_text(raw)
    if kind in SHORT_FORM_KINDS:
        if actual_dh < 0.45:
            return False
        if appears and not placed and actual_dh < 0.85:
            return False
        return True
    if kind == "电视剧":
        if actual_dh < 0.30:
            return False
        if appears and not placed and actual_dh < 0.62:
            return False
        return True
    # 竖屏短剧：允许整剧合集，但仍要求片名在片名位或时长高度吻合
    if actual_dh < 0.25:
        return False
    if appears and not placed and actual_dh < 0.55:
        return False
    return True


def select_page(view_data, entry, kind):
    """多 P 视频里挑时长最接近的一集；返回 (cid, page_sec, page_title, page_no)。"""
    pages = view_data.get("pages") or []
    if not pages:
        return None
    runtime = float(entry.get("runtime_min") or 0) * 60
    best = None
    for pg in pages:
        sec = int(pg.get("duration") or 0)
        if sec <= 0:
            continue
        hit = duration_hit(sec, entry, kind)
        if best is None or hit > best[0]:
            best = (hit, pg)
    if best is None:
        return None
    hit, pg = best
    if hit < 0.18 and len(pages) > 1:
        # 多 P 但都对不上：用第一 P
        pg = pages[0]
    return int(pg.get("cid")), int(pg.get("duration") or 0), pg.get("part") or "", int(pg.get("page") or 1)


def resolve_entry(bili, entry, kind, idx, exclude=None):
    queries = build_queries(entry, kind)
    ranked = []
    for query in queries:
        try:
            results = bili.search(query)
        except Exception as exc:  # noqa: BLE001
            log(f"  ! search fail {entry.get('title_zh')} / {query}: {exc}")
            results = []
        for cand in results[:20]:
            ev = evaluate_candidate(entry, cand, kind)
            if ev:
                ranked.append(ev)
        ranked.sort(key=lambda x: -x["score"])
        if ranked and ranked[0]["score"] >= 0.86 and ranked[0]["title_score"] >= 0.95:
            break
        time.sleep(random.uniform(0.15, 0.45))
    if not ranked:
        return None
    # 去重同一 bvid
    seen = set()
    uniq = []
    for ev in ranked:
        if ev["cand"]["bvid"] in seen:
            continue
        seen.add(ev["cand"]["bvid"])
        uniq.append(ev)
    for ev in uniq[:4]:
        cand = ev["cand"]
        if exclude and cand["bvid"] in exclude:
            continue
        try:
            view = bili.view(cand["bvid"])
        except Exception:  # noqa: BLE001
            view = None
        if not view:
            continue
        page = select_page(view, entry, kind)
        if not page:
            continue
        cid, page_sec, part, page_no = page
        actual_sec = page_sec or cand["duration_sec"]
        actual_dh = duration_hit(actual_sec, entry, kind)
        view_title = view.get("title") or cand["title"]
        if not validate_match(entry, kind, view_title, actual_sec, actual_dh):
            continue
        th = title_hit(view_title, entry)
        try:
            shot = bili.videoshot(cand["bvid"], cid)
        except Exception:  # noqa: BLE001
            shot = None
        if not shot:
            continue
        play = int((view.get("stat") or {}).get("view") or cand["play"])
        dh = actual_dh
        final = round(0.58 * th + 0.30 * dh + 0.12 * min(
            1.0, math.log10(play + 10) / 6.0), 3)
        note = ""
        if len(view.get("pages") or []) > 1:
            note = f"多P视频，已定位第 {page_no} P（{part or '无分P标题'}）"
        elif float(entry.get("runtime_min") or 0) > 0 and dh < 0.6:
            note = f"链接为完整合集，实际时长 {sec_to_timecode(actual_sec)}"
        url = f"https://www.bilibili.com/video/{cand['bvid']}"
        if len(view.get("pages") or []) > 1:
            url += f"?p={page_no}"
        return {
            "bvid": cand["bvid"],
            "cid": cid,
            "url": url,
            "video_title": view.get("title") or cand["title"],
            "part": part,
            "page_no": page_no,
            "page_count": len(view.get("pages") or []),
            "owner": (view.get("owner") or {}).get("name") or cand["author"],
            "play": int((view.get("stat") or {}).get("view") or cand["play"]),
            "video_duration_sec": page_sec or cand["duration_sec"],
            "match_score": final,
            "title_score": ev["title_score"],
            "duration_score": round(max(dh, ev["duration_score"]), 3),
            "typename": cand["typename"],
            "search_query": queries[0],
            "match_note": note,
            "verified_at": now_iso(),
        }
    return None


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


# --------------------------------------------------------------------------- 静帧
def dhash(frame):
    small = frame.convert("L").resize((9, 8), Image.LANCZOS)
    px = list(small.getdata())
    bits = 0
    for row in range(8):
        base = row * 9
        for col in range(8):
            bits = (bits << 1) | (1 if px[base + col] > px[base + col + 1] else 0)
    return bits


def hamming(a, b):
    return bin(a ^ b).count("1")


def frame_features(frame):
    if np is not None:
        arr = np.asarray(frame.resize((96, 54), Image.BILINEAR), dtype=np.float32)
        bright = float(arr.mean())
        contrast = float(arr.std())
        gray = arr.mean(axis=2)
        edge = float((abs(np.diff(gray, axis=0)).mean() + abs(np.diff(gray, axis=1)).mean()) / 2)
        r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
        color = float((abs(r - g).mean() + abs(g - b).mean() + abs(r - b).mean()) / 3)
        mx, mn = arr.max(axis=2), arr.min(axis=2)
        skin = float((((r > 95) & (g > 40) & (b > 20) & (mx - mn > 15)
                       & (abs(r - g) > 15) & (r > g) & (r > b)).mean()))
        dark = float((gray < 22).mean())
        bright_px = float((gray > 232).mean())
    else:
        stat = ImageStat.Stat(frame.resize((96, 54)))
        bright = sum(stat.mean) / 3
        contrast = sum(stat.stddev) / 3
        edge = ImageStat.Stat(frame.convert("L").filter(ImageFilter.FIND_EDGES)).mean[0]
        color = contrast
        skin = 0.0
        dark = 0.0
        bright_px = 0.0
    if bright < 12 or bright > 248 or contrast < 5:
        return None
    score = (0.95 * min(edge / 10.0, 1.0)
             + 0.55 * min(skin / 0.30, 1.0)
             + 0.35 * min(color / 20.0, 1.0)
             + 0.50 * math.exp(-((bright - 122) / 68.0) ** 2)
             + 0.30 * min(contrast / 45.0, 1.0))
    # 片头字幕卡 / 片尾字幕 / 推荐位：大面积纯黑或纯白且没有肤色，边缘多由文字提供
    if skin < 0.006 and edge > 6 and (dark > 0.45 or bright_px > 0.35):
        score -= 0.72
    return {"score": round(score, 4), "bright": round(bright, 1),
            "contrast": round(contrast, 1), "edge": round(edge, 2),
            "skin": round(skin, 3), "color": round(color, 1),
            "dark": round(dark, 3)}


def detect_crop_box(frames):
    """静态黑边检测：返回 (left, top, right, bottom) 的裁切比例；不裁返回 None。"""
    if np is None or not frames:
        return None
    luminances = []
    for frame in frames[:6]:
        arr = np.asarray(frame.convert("L").resize((160, 90), Image.BILINEAR), dtype=np.float32)
        luminances.append(arr)
    mean = np.mean(luminances, axis=0)  # 90x160
    rows, cols = mean.mean(axis=1), mean.mean(axis=0)
    h, w = rows.shape[0], cols.shape[0]

    def trim(values, thresh=9.0):
        lo = 0
        while lo < len(values) - 1 and values[lo] < thresh:
            lo += 1
        hi = len(values) - 1
        while hi > 0 and values[hi] < thresh:
            hi -= 1
        return lo, hi

    top, bottom = trim(rows)
    left, right = trim(cols)
    box = (left / w, top / h, (right + 1) / w, (bottom + 1) / h)
    area = (box[2] - box[0]) * (box[3] - box[1])
    w_frac = box[2] - box[0]
    h_frac = box[3] - box[1]
    trimmed = box[0] > 0.11 or box[1] > 0.09 or box[2] < 0.89 or box[3] < 0.91
    portrait = h_frac > 0.80 and w_frac < 0.62  # 竖屏短剧被塞进横屏画幅
    if trimmed and (area > 0.45 or portrait):
        return box
    return None


def _fetch_bytes(url, timeout=40):
    """下载 storyboard 拼图（CDN 不需要 cookie，普通 UA+Referer 即可）。"""
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": UA, "Referer": "https://www.bilibili.com/"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(0.6 + attempt * 1.2)
    raise RuntimeError(str(last))


def _download_sprites(pairs, workers=5):
    """并发下载拼图，返回 {sprite_index: raw_bytes}。"""
    out = {}

    def one(pair):
        idx, url = pair
        url = "https:" + url if url.startswith("//") else url
        try:
            return idx, _fetch_bytes(url)
        except Exception:  # noqa: BLE001
            return idx, None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for idx, raw in pool.map(one, pairs):
            if raw:
                out[idx] = raw
    return out


def extract_stills(bili, bvid, cid, out_dir, count=10, expected_sec=None):
    """抽 10 张代表性静帧：只下载需要的 storyboard 拼图，逐格打分后按时间桶挑选。"""
    payload = bili.videoshot(bvid, cid)
    if not payload:
        return []
    images = payload["image"]
    stamps = payload.get("index") or []
    x_len = int(payload.get("img_x_len") or 10)
    y_len = int(payload.get("img_y_len") or 10)
    fw = int(payload.get("img_x_size") or 480)
    fh = int(payload.get("img_y_size") or 270)
    per = x_len * y_len
    total = len(images) * per
    if len(stamps) != total:  # 时间戳缺失/uniform 补齐
        last = stamps[-1] if stamps else total * 5
        stamps = [int(last * i / max(1, total - 1)) for i in range(total)]
    if total < count:
        return []
    t_first, t_last = stamps[0], stamps[-1]
    span = max(1, t_last - t_first)

    start_frac, end_frac = 0.08, 0.94  # 避开片头字幕与片尾字幕
    if expected_sec and t_last > expected_sec * 1.12:
        # 上传版本比片长更长（带花絮/访谈/广告）：只从「正片应占的比例」里取帧
        end_frac = max(0.55, min(0.94, (expected_sec * 0.97 - t_first) / span))
    bucket = span * (end_frac - start_frac) / count
    plans, needed = [], []
    for i in range(count):
        target = t_first + span * (start_frac + (end_frac - start_frac) * (i + 0.5) / count)
        pos = max(0, min(total - 1, bisect.bisect_left(stamps, target)))
        sprite = min(len(images) - 1, pos // per)
        plans.append({"bin": i, "target": target, "sprite": sprite})
        if sprite not in needed:
            needed.append(sprite)
    raws = _download_sprites([(s, images[s]) for s in needed])
    if not raws:
        return []

    # 第一遍：只保留特征与 dHash（不保存图像，避免 6 并发时内存爆掉）
    scored = {}
    for sprite in sorted(raws):
        try:
            sheet = Image.open(io.BytesIO(raws[sprite])).convert("RGB")
        except Exception:  # noqa: BLE001
            continue
        for cell in range(per):
            pos = sprite * per + cell
            if pos >= total:
                break
            row, col = divmod(cell, x_len)
            frame = sheet.crop((col * fw, row * fh, (col + 1) * fw, (row + 1) * fh))
            feat = frame_features(frame)
            if not feat:
                continue
            scored[pos] = {"pos": pos, "sprite": sprite, "cell": cell,
                           "time": stamps[pos], "feat": feat, "hash": dhash(frame)}
        del sheet
    if not scored:
        return []

    def is_subtitle_card(feat):
        # 黑底 + 字幕：画面几乎全黑、几乎无肤色、边缘强（文字）
        return feat["dark"] > 0.60 and feat["skin"] < 0.012 and feat["edge"] > 4

    filtered = {k: v for k, v in scored.items() if not is_subtitle_card(v["feat"])}
    if len(filtered) >= count * 3:
        scored = filtered

    selected, used = [], []
    for plan in plans:
        cands = [s for s in scored.values()
                 if s["sprite"] == plan["sprite"]
                 and abs(s["time"] - plan["target"]) <= bucket * 0.62]
        if not cands:  # 该拼图下载失败：向相邻拼图借，保持时间轴不断裂
            cands = [s for s in scored.values()
                     if abs(s["sprite"] - plan["sprite"]) <= 2
                     and abs(s["time"] - plan["target"]) <= bucket * 1.1]
        if not cands:
            cands = [s for s in scored.values() if s["sprite"] == plan["sprite"]]
        if not cands:
            continue
        cands.sort(key=lambda s: -s["feat"]["score"])
        chosen = None
        for cand in cands:
            if all(hamming(cand["hash"], h) >= 10 for h in used):
                chosen = cand
                break
        if chosen is None:
            chosen = cands[0]
        used.append(chosen["hash"])
        selected.append(chosen)
    selected.sort(key=lambda s: s["time"])
    if len(selected) < count:
        picked = {s["pos"] for s in selected}
        for cand in sorted(scored.values(), key=lambda s: -s["feat"]["score"]):
            if len(selected) >= count:
                break
            if cand["pos"] in picked:
                continue
            if all(hamming(cand["hash"], h) >= 10 for h in used):
                used.append(cand["hash"])
                selected.append(cand)
        selected.sort(key=lambda s: s["time"])
    selected = selected[:count]
    if not selected:
        return []

    # 第二遍：按 sprite 分组重新解码，裁出选中的帧（一次只留一张拼图）
    by_sprite = {}
    for item in selected:
        by_sprite.setdefault(item["sprite"], []).append(item)
    picked_frames = {}
    for sprite, items in by_sprite.items():
        raw = raws.get(sprite)
        if not raw:
            continue
        try:
            sheet = Image.open(io.BytesIO(raw)).convert("RGB")
        except Exception:  # noqa: BLE001
            continue
        for item in items:
            row, col = divmod(item["cell"], x_len)
            picked_frames[item["pos"]] = sheet.crop(
                (col * fw, row * fh, (col + 1) * fw, (row + 1) * fh)).copy()
        del sheet
    frames = [(item, picked_frames[item["pos"]]) for item in selected
              if item["pos"] in picked_frames]
    if not frames:
        return []

    # 兜底：选出的 10 张里大多数仍是黑底字幕卡 → 这个上传不是电影画面，判定失败
    cards = sum(1 for item, _ in frames if is_subtitle_card(item["feat"]))
    if cards >= 5:
        return []
    crop = detect_crop_box([f for _, f in frames])
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for idx, (item, frame) in enumerate(frames, 1):
        if crop:
            w, h = frame.size
            box = (int(crop[0] * w), int(crop[1] * h), int(crop[2] * w), int(crop[3] * h))
            if box[2] - box[0] > 40 and box[3] - box[1] > 40:
                frame = frame.crop(box)
        if min(frame.size) < 300:  # 竖屏短剧等窄画幅：2x 便于查看
            frame = frame.resize((frame.width * 2, frame.height * 2), Image.LANCZOS)
        path = out_dir / f"{idx:02d}.jpg"
        frame.save(path, "JPEG", quality=92)
        results.append({
            "n": idx,
            "path": f"/static/frames/catalog/{out_dir.name}/{path.name}",
            "file": str(path.relative_to(ROOT)),
            "time_sec": int(item["time"]),
            "timecode": sec_to_timecode(int(item["time"])),
            "score": item["feat"]["score"],
            "size": list(frame.size),
        })
    return results


def sec_to_timecode(sec):
    h, rem = divmod(int(sec), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


# --------------------------------------------------------------------------- 状态
def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"built_at": now_iso(), "entries": {}}


def save_state(state):
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def load_sources(kinds, src_override=None):
    entries = []
    for kind in kinds:
        paths = ([Path(src_override)] if src_override
                 else [SRC_DIR / f"{SRC_FILE[kind]}.json",
                       SRC_DIR / f"{SRC_FILE[kind]}_extra.json"])
        offset = 0
        for path in paths:
            if not path.exists():
                if not src_override:
                    log(f"! 缺少源文件 {path}")
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            titles = data.get("titles") or []
            for i, item in enumerate(titles):
                entry = dict(item)
                entry["kind"] = kind
                entry["src_key"] = f"{kind}:{offset + i}"
                entries.append(entry)
            offset += len(titles)
    return entries


# --------------------------------------------------------------------------- 阶段
def stage_resolve(args):
    state = load_state()
    entries = load_sources(args.kinds, args.src)
    if args.limit:
        entries = entries[: args.limit]
    todo = [e for e in entries if e["src_key"] not in state["entries"]
            or not state["entries"][e["src_key"]].get("match")]
    log(f"resolve: 共 {len(entries)} 条，待处理 {len(todo)} 条，并发 {args.workers}")
    bili = Bili()
    lock = threading.Lock()
    done = 0

    exclude = set(state.get("failed_bvids") or [])

    def work(entry):
        try:
            match = resolve_entry(bili, entry, entry["kind"], None, exclude)
        except Exception as exc:  # noqa: BLE001
            log(f"  ✗ {entry.get('title_zh')}: {exc}")
            return entry["src_key"], None
        return entry["src_key"], match

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(work, e) for e in todo]
        for future in as_completed(futures):
            key, match = future.result()
            with lock:
                state["entries"][key] = {"entry": next(e for e in entries if e["src_key"] == key),
                                         "match": match,
                                         "frames": []}
                done += 1
                if done % 5 == 0 or match is None:
                    ok = sum(1 for v in state["entries"].values() if v.get("match"))
                    log(f"  {done}/{len(todo)} 完成，已匹配 {ok}")
                if done % 10 == 0:
                    save_state(state)
    save_state(state)
    ok = sum(1 for e in entries if state["entries"].get(e["src_key"], {}).get("match"))
    log(f"resolve 完成：{ok}/{len(entries)} 条拿到可用原片")
    return state


def _dhash_file(path):
    try:
        im = Image.open(path).convert("L").resize((9, 8), Image.LANCZOS)
    except Exception:  # noqa: BLE001
        return None
    px = list(im.getdata())
    bits = 0
    for row in range(8):
        base = row * 9
        for col in range(8):
            bits = (bits << 1) | (1 if px[base + col] > px[base + col + 1] else 0)
    return bits


def verify_distinct(dir_path, frames):
    """统计 10 张静帧里有多少张互不相似（<7 张基本可以判定是静态图/幻灯片）。"""
    hashes = []
    for f in frames:
        p = Path(f["file"])
        if not p.is_absolute():
            p = ROOT / p
        h = _dhash_file(p)
        if h is not None:
            hashes.append(h)
    if not hashes:
        return 0
    uniq = 1
    for i in range(1, len(hashes)):
        if all(hamming(hashes[i], h) >= 8 for h in hashes[:i]):
            uniq += 1
    return uniq


def stage_frames(args):
    state = load_state()
    todo = []
    for key, item in state["entries"].items():
        kind = item["entry"]["kind"]
        if kind not in args.kinds:
            continue
        if not item.get("match"):
            continue
        if args.limit and len(todo) >= args.limit:
            break
        if args.force or len(item.get("frames") or []) < 10:
            todo.append(key)
    log(f"frames: 待抽帧 {len(todo)} 条，并发 {args.workers}")
    bili = Bili()
    lock = threading.Lock()

    counts = {}

    def assign_id(kind):
        with lock:
            counts[kind] = counts.get(kind, 0) + 1
            return f"{CODE[kind]}{counts[kind]:03d}"

    # 编号在导出阶段统一分配；这里先用 bvid 目录
    def work(key):
        item = state["entries"][key]
        match = item["match"]
        entry = item["entry"]
        kind = entry["kind"]
        out_dir = FRAME_ROOT / match["bvid"]
        runtime = float(entry.get("runtime_min") or 0)
        episodes = int(entry.get("episodes") or 0)
        expected = runtime * 60 if runtime else None
        if expected and episodes and entry["kind"] in ("电视剧", "竖屏短剧"):
            total = expected * episodes
            if match["video_duration_sec"] > expected * 1.12:
                expected = total if match["video_duration_sec"] > total * 1.05 else expected
        try:
            frames = extract_stills(bili, match["bvid"], match["cid"], out_dir, count=10,
                                    expected_sec=expected)
        except Exception as exc:  # noqa: BLE001
            log(f"  ✗ {entry.get('title_zh')}: {exc}")
            return key, [], 0
        distinct = verify_distinct(out_dir, frames) if frames else 0
        return key, frames, distinct

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(work, key) for key in todo]
        done = 0
        for future in as_completed(futures):
            key, frames, distinct = future.result()
            with lock:
                state["entries"][key]["frames"] = frames
                state["entries"][key]["frame_distinct"] = distinct
                done += 1
                if frames:
                    log(f"  ✓ {state['entries'][key]['entry'].get('title_zh')}: {len(frames)} 帧")
                else:
                    log(f"  ✗ {state['entries'][key]['entry'].get('title_zh')}: 无静帧")
                if done % 10 == 0:
                    save_state(state)
    save_state(state)


# --------------------------------------------------------------------------- 导出
def _link_confidence(entry, match):
    """链接可信度：片名在主位 + 时长高度吻合 = 高；其余 = 中（建议人工复核）。"""
    vt = match.get("video_title") or ""
    dur = int(match.get("video_duration_sec") or 0)
    runtime = float(entry.get("runtime_min") or 0) * 60
    placed = title_placed(vt, entry.get("title_zh"))
    en = (entry.get("title_en") or "").strip()
    en_hit = bool(en) and len(en) >= 4 and norm_text(en) in norm_text(vt)
    if not dur or not runtime:
        return "中"
    ratio = dur / runtime
    if entry["kind"] in ("电视剧", "竖屏短剧"):
        episodes = int(entry.get("episodes") or 0)
        ok = 0.92 <= ratio <= 1.12 or (episodes and 0.9 <= dur / (runtime * episodes) <= 1.1)
    else:
        ok = 0.95 <= ratio <= 1.10
    return "高" if (placed or en_hit) and ok else "中"


def build_catalog(state, kinds):
    rows = []
    per_kind = {k: 0 for k in kinds}
    chosen = []
    # 按类目分：优先「10 张互不相似静帧」的条目，不足 50 时用静帧重复度偏高的条目补足并标注
    for kind in kinds:
        pool = [item for item in state["entries"].values()
                if item["entry"]["kind"] == kind and item.get("match")
                and len(item.get("frames") or []) >= 10]
        strict = [it for it in pool if int(it.get("frame_distinct") or 10) >= 7]
        strict.sort(key=lambda it: -it["match"]["match_score"])
        picked = strict[:TARGET_PER_KIND]
        if len(picked) < TARGET_PER_KIND:
            picked_ids = {id(it) for it in picked}
            loose = [it for it in pool if id(it) not in picked_ids]
            loose.sort(key=lambda it: (-int(it.get("frame_distinct") or 0), -it["match"]["match_score"]))
            picked += loose[:TARGET_PER_KIND - len(picked)]
        chosen.extend(picked)
    chosen.sort(key=lambda it: (KINDS.index(it["entry"]["kind"]),
                                -it["match"]["match_score"]))
    for item in chosen:
        entry, match, frames = item["entry"], item["match"], item["frames"]
        per_kind[entry["kind"]] += 1
        rid = f"{CODE[entry['kind']]}{per_kind[entry['kind']]:03d}"
        runtime = float(entry.get("runtime_min") or 0)
        episodes = entry.get("episodes")
        if entry["kind"] in ("电视剧", "竖屏短剧") and episodes:
            duration_label = entry.get("duration_label") or f"单集{int(runtime)}分钟 × {int(episodes)}集"
        else:
            duration_label = entry.get("duration_label") or (
                f"{int(runtime)}分钟" if runtime else "—")
        rows.append({
            "id": rid,
            "kind": entry["kind"],
            "title_zh": entry.get("title_zh"),
            "title_en": entry.get("title_en") or "",
            "year": entry.get("year"),
            "duration": duration_label,
            "runtime_min": runtime,
            "episodes": episodes,
            "moods": entry.get("moods") or [],
            "genre": entry.get("genre") or [],
            "synopsis": entry.get("synopsis") or "",
            "tags": entry.get("tags") or [],
            "bvid": match["bvid"],
            "url": match["url"],
            "platform": match.get("platform") or "Bilibili",
            "video_title": match["video_title"],
            "video_duration_sec": match["video_duration_sec"],
            "owner": match["owner"],
            "play": match["play"],
            "page_count": match.get("page_count") or 1,
            "match_score": match["match_score"],
            "link_confidence": _link_confidence(entry, match),
            "frame_distinct": int(item.get("frame_distinct") or 10),
            "frame_quality": "高" if int(item.get("frame_distinct") or 10) >= 7 else "低（画面重复度偏高）",
            "verified_at": match["verified_at"],
            "frames": [f["path"] for f in frames],
            "frame_meta": frames,
            "frame_dir": f"static/frames/catalog/{match['bvid']}",
        })
    catalog = {
        "name": "Filmmate 影视灵感目录（B 站原片 + 10 张静帧）",
        "description": "按「编号-种类-中文名-英文名-年份-时长-情绪-内容梗概-Tag-原片链接」组织的 250 部可观看作品库，"
                       "每部 10 张代表性静帧，用于「灵感→题材→创作思路→相似片推荐」。",
        "generated_at": now_iso(),
        "count": len(rows),
        "by_kind": per_kind,
        "kinds": kinds,
        "titles": rows,
    }
    return catalog


def export_all(args):
    state = load_state()
    catalog = build_catalog(state, args.kinds)
    CATALOG_JSON.parent.mkdir(parents=True, exist_ok=True)
    CATALOG_JSON.write_text(json.dumps(catalog, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"导出 catalog.json：{catalog['count']} 条 {catalog['by_kind']}")
    import catalog_export
    catalog_export.export_all(catalog)
    return catalog


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["resolve", "frames", "export", "all"])
    parser.add_argument("--kinds", default=",".join(KINDS))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--src", default="")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    args.kinds = [k for k in args.kinds.split(",") if k]
    if args.stage in ("resolve", "all"):
        stage_resolve(args)
    if args.stage in ("frames", "all"):
        stage_frames(args)
    if args.stage in ("export", "all"):
        export_all(args)


if __name__ == "__main__":
    main()
