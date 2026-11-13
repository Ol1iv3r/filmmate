"""扩充资料库的统一加载与检索。

四类新数据（都放在 data/library/，见 docs/DATA_SCHEMA.md）：
  - scenes.json            场面模式（戏剧功能 / 节拍 / 调度 / 镜头建议 / 页数八分之一 / 拍摄分钟）
  - shots.json             镜头模式（景别机位运镜焦段 / 用途 / 常见误用）
  - stripboards.json       通告单模板（crew_call→setup→scene→move→meal→wrap + totals）
  - samples_enriched.json  50 个视频样本的专业富化（scenes/shots/节奏统计）

检索沿用 rag.BM25Index（零依赖、离线可用），并按命中字段加权：
标题/关键词命中 > 正文命中。所有函数在文件缺失时返回空结果，不影响主流程。
"""
import json
import logging
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
LIB_DIR = BASE_DIR / "data" / "library"

FILES = {
    "scenes": LIB_DIR / "scenes.json",
    "shots": LIB_DIR / "shots.json",
    "stripboards": LIB_DIR / "stripboards.json",
    "samples": LIB_DIR / "samples_enriched.json",
}

logger = logging.getLogger("library")
_CACHE = {}


# ------------------------------------------------------------------ 加载
def _read(key, list_key):
    if key in _CACHE:
        return _CACHE[key]
    path = FILES[key]
    items = []
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            items = data.get(list_key, []) if isinstance(data, dict) else data
        except (ValueError, OSError) as exc:  # 数据损坏不应拖垮服务
            logger.warning("读取 %s 失败：%s", path.name, exc)
            items = []
    _CACHE[key] = items
    logger.info("资料库 %s 加载 %d 条", key, len(items))
    return items


def load_scenes():
    return _read("scenes", "scenes")


def load_shots():
    return _read("shots", "shots")


def load_templates():
    return _read("stripboards", "templates")


def load_samples():
    return _read("samples", "videos")


def stats():
    return {
        "scenes": len(load_scenes()),
        "shots": len(load_shots()),
        "stripboards": len(load_templates()),
        "samples": len(load_samples()),
        "sample_shots": sum(v.get("stats", {}).get("shot_count", 0) for v in load_samples()),
    }


# ------------------------------------------------------------------ 检索文本
def scene_doc(s):
    return " ".join([
        s.get("name_zh", ""), s.get("name_en", ""), " ".join(s.get("genre", [])),
        s.get("dramatic_function", ""), s.get("conflict", ""), s.get("subtext", ""),
        " ".join(s.get("beat_structure", [])), s.get("lighting", ""), s.get("sound", ""),
        s.get("staging", ""), " ".join(s.get("keywords", [])),
    ])


def shot_doc(s):
    return " ".join([
        s.get("name_zh", ""), s.get("name_en", ""), s.get("size", ""), s.get("angle", ""),
        s.get("movement", ""), s.get("lens", ""), s.get("purpose", ""),
        " ".join(s.get("best_for", [])), " ".join(s.get("keywords", [])),
    ])


def template_doc(t):
    scenes = " ".join(
        f"{x.get('heading', '')} {x.get('synopsis', '')} {x.get('day_night', '')}"
        for x in t.get("scenes", [])
    )
    return " ".join([
        t.get("name", ""), t.get("type", ""), scenes,
        " ".join(x.get("name", "") for x in t.get("locations", [])),
        " ".join(t.get("tips", [])),
    ])


def sample_doc(v):
    scenes = " ".join(
        f"{sc.get('label', '')} {sc.get('setting', '')} "
        + " ".join(sh.get("subject", "") for sh in sc.get("shots", [])[:3])
        for sc in v.get("scenes", [])
    )
    return " ".join([
        v.get("title", ""), v.get("format", ""), " ".join(v.get("keywords", [])),
        v.get("stats", {}).get("coverage_note", ""), scenes,
    ])


# ------------------------------------------------------------------ 排序
def _search(key, list_key, doc_fn, query, k=3, keyword_fields=("keywords",)):
    import rag  # 延迟导入，避免与 rag 的模块级依赖形成环

    items = _read(key, list_key)
    if not items or not (query or "").strip():
        return []
    idx = _CACHE.get(f"bm25:{key}")
    if idx is None:
        idx = rag.BM25Index([doc_fn(x) for x in items])
        _CACHE[f"bm25:{key}"] = idx

    tokens = rag.tokenize(query)
    low = query.lower()
    ranked = []
    for score, i in ((idx.score(tokens, i), i) for i in range(len(items))):
        item = items[i]
        bonus = 0.0
        for field in keyword_fields:
            values = item.get(field) or []
            if isinstance(values, str):
                values = [values]
            for value in values:
                value = str(value)
                if value and value.lower() in low:
                    bonus += 2.0
                elif any(t in value.lower() for t in tokens if len(t) >= 2):
                    bonus += 0.8
        # 名称命中（如「推镜」 vs 查询「推镜头」）：按前两个字做弱匹配，避免分词粒度不一致
        name = str(item.get("name_zh") or item.get("name") or item.get("title") or "").lower()
        for token in tokens:
            if len(token) >= 2 and (token in name or token[:2] in name):
                bonus += 1.2
        ranked.append((score + bonus, i))
    ranked.sort(key=lambda x: -x[0])
    out = []
    for score, i in ranked[:k]:
        if score <= 0:
            continue
        item = dict(items[i])
        item["score"] = round(float(score), 3)
        out.append(item)
    return out


def search_scenes(query, k=3):
    return _search("scenes", "scenes", scene_doc, query, k, ("keywords", "genre"))


def search_shots(query, k=3):
    return _search("shots", "shots", shot_doc, query, k, ("keywords", "best_for"))


def search_templates(query, k=2):
    return _search("stripboards", "templates", template_doc, query, k, ("type",))


def search_samples(query, k=3):
    return _search("samples", "videos", sample_doc, query, k)


# ------------------------------------------------------------------ 提示词文本
def scene_to_text(s):
    beats = " → ".join(s.get("beat_structure", []))
    shots = "; ".join(
        f"{x.get('size', '')}/{x.get('angle', '')}/{x.get('movement', '')}：{x.get('purpose', '')}"
        for x in s.get("shots", [])
    )
    return (
        f"【场面模式】{s.get('name_zh', '')}（{s.get('name_en', '')}｜{'/'.join(s.get('genre', []))}）\n"
        f"戏剧功能：{s.get('dramatic_function', '')}\n"
        f"节拍：{beats}\n"
        f"冲突：{s.get('conflict', '')}｜潜台词：{s.get('subtext', '')}\n"
        f"调度：{s.get('staging', '')}\n"
        f"建议镜头：{shots}\n"
        f"光线：{s.get('lighting', '')}｜声音：{s.get('sound', '')}\n"
        f"时长 {s.get('duration_sec', '?')}s｜页数 {s.get('page_eighths', '?')}/8｜预计拍摄 {s.get('shoot_minutes', '?')} 分钟\n"
        f"常见问题：{'；'.join(s.get('common_pitfalls', []))}　修正：{s.get('fix', '')}"
    )


def shot_to_text(s):
    return (
        f"【镜头】{s.get('name_zh', '')}（{s.get('name_en', '')}｜"
        f"{s.get('size', '')}/{s.get('angle', '')}/{s.get('movement', '')}｜{s.get('lens', '')}）"
        f"用途：{s.get('purpose', '')}　适用：{'、'.join(s.get('best_for', []))}　"
        f"声音：{s.get('sound', '')}　误用：{'；'.join(s.get('pitfalls', []))}"
    )


def template_to_text(t, max_scenes=8):
    scenes = "; ".join(
        f"#{x.get('scene_no')} {x.get('int_ext')} {x.get('heading')}"
        f"（{x.get('pages_eighths')}/8 页，{x.get('est_minutes')} 分钟，{x.get('cast')}）"
        for x in t.get("scenes", [])[:max_scenes]
    )
    days = "；".join(
        f"Day {d.get('day')} {d.get('call', '')}-{d.get('wrap', '')}，"
        f"{d.get('totals', {}).get('pages_eighths', '?')}/8 页，"
        f"{d.get('totals', {}).get('company_moves', 0)} 次转场"
        for d in t.get("days", [])
    )
    return (
        f"【通告单模板】{t.get('name', '')}（{t.get('type', '')}，{t.get('shoot_days', '?')} 天）\n"
        f"场景：{scenes}\n日程：{days}\n"
        f"提示：{'；'.join(t.get('tips', [])[:3])}"
    )


def sample_to_text(v, max_shots=6):
    shots = []
    for sc in v.get("scenes", []):
        for sh in sc.get("shots", []):
            shots.append(
                f"{sh.get('start')}-{sh.get('end')} {sh.get('size')}/{sh.get('angle')}/{sh.get('movement')}"
                f"：{sh.get('subject', '')[:60]}"
            )
        if len(shots) >= max_shots:
            break
    return (
        f"【视频样本】{v.get('title', '')}（{v.get('format', '')}，{v.get('duration_sec', 0)}s）\n"
        f"{v.get('stats', {}).get('coverage_note', '')}\n"
        f"镜头示例：{'；'.join(shots[:max_shots])}"
    )
