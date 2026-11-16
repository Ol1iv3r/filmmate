"""灵感 → 题材 → 创作思路 → 相似片推荐（catalog 检索层）。

数据来自 data/library/catalog.json（由 scripts/build_catalog.py 生成：250 部可观看作品 + 每部 10 张静帧）。
零额外依赖：复用 rag.BM25Index / rag.tokenize（未装 jieba 时自动退化为字级分词）。

典型用法：
    import catalog
    catalog.kind_options()                 # 让用户先选题材
    catalog.suggest("外卖员在暴雨夜捡到一部手机")
    catalog.prompt_block("外卖员在暴雨夜捡到一部手机")   # 塞进 LLM 的灵感提示词

命令行：
    python3 catalog.py "一个外卖员在暴雨夜捡到一部手机"
"""
import json
import re
from pathlib import Path

import rag

ROOT = Path(__file__).resolve().parent
CATALOG_FILE = ROOT / "data" / "library" / "catalog.json"
KIND_ORDER = ["电影", "电视剧", "长片", "短片", "竖屏短剧",
              "广告/TVC", "教程/产品演示", "Vlog/美食", "动画"]
KIND_DESC = {
    "电影": "院线/主流叙事长片，90–180 分钟，适合「一个完整故事」的灵感",
    "电视剧": "多集剧集，适合人物弧光长、群像、连载式钩子",
    "长片": "独立/艺术/纪录长片，适合真实题材、观察式、作者表达",
    "短片": "≤40 分钟，适合一个概念、一个反转、一个情绪瞬间",
    "竖屏短剧": "竖屏 1–3 分钟/集、强钩子，适合爽点密集、强冲突的短内容",
    "广告/TVC": "30 秒–10 分钟的广告/品牌片，适合参考钩子、视觉概念与情绪浓度",
    "教程/产品演示": "官方 demo / 开箱 / 功能导览，适合参考「把功能讲清楚」的镜头组织",
    "Vlog/美食": "Vlog、美食制作与探店，适合参考手持节奏、特写与氛围声",
    "动画": "动画短片与作者动画，适合参考世界观设定、风格化与无对白叙事",
}
KIND_HINTS = {
    "竖屏短剧": ["竖屏", "短剧", "一分钟", "每集", "爽点", "反转爽", "节奏快", "切片"],
    "短片": ["短片", "几分钟", "学生作业", "概念片", "实验", "无对白", "一个瞬间"],
    "长片": ["纪录片", "真实事件", "采访", "观察", "跟拍", "素材", "独立电影", "作者"],
    "电视剧": ["剧集", "连载", "群像", "一季", "每一集", "成长线", "宇宙"],
}
MOODS = ["压抑", "孤独", "荒诞", "黑色幽默", "温暖", "治愈", "心碎", "紧张", "悬疑",
         "恐惧", "愤怒", "热血", "浪漫", "怀旧", "忧郁", "冷峻", "庄严", "疯狂", "希望",
         "绝望", "温柔", "成长", "欢乐", "刺激", "悲凉", "讽刺", "宿命", "敬畏", "沉重", "遗憾"]

_cache = {}


def _load():
    if "titles" not in _cache:
        if not CATALOG_FILE.exists():
            _cache["titles"] = []
        else:
            data = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
            _cache["titles"] = data.get("titles") or []
        _cache["by_id"] = {t["id"]: t for t in _cache["titles"]}
    return _cache["titles"]


def stats():
    titles = _load()
    by_kind = {}
    for t in titles:
        by_kind[t["kind"]] = by_kind.get(t["kind"], 0) + 1
    return {"count": len(titles), "by_kind": by_kind,
            "frames": sum(len(t.get("frames") or []) for t in titles)}


def kind_options():
    """给 UI/LLM 的「先选题材」选项。"""
    by_kind = stats()["by_kind"]
    return [{"kind": k, "count": by_kind.get(k, 0), "description": KIND_DESC[k]}
            for k in KIND_ORDER if by_kind.get(k)]


def genre_options(kind=None):
    from collections import Counter
    titles = _load()
    if kind:
        titles = [t for t in titles if t["kind"] == kind]
    return [{"genre": g, "count": n} for g, n in Counter(
        x for t in titles for x in t.get("genre") or []).most_common()]


def _doc(t):
    return " ".join([
        t.get("title_zh", ""), t.get("title_en", ""),
        " ".join(t.get("moods") or []), " ".join(t.get("genre") or []),
        " ".join(t.get("tags") or []), t.get("synopsis", ""),
        t.get("kind", ""),
    ])


def _index():
    if "index" not in _cache:
        _cache["index"] = rag.BM25Index([_doc(t) for t in _load()])
    return _cache["index"]


def _query_terms(query):
    return rag.tokenize(query or "")


def _overlap_reasons(t, query, tokens):
    """生成可解释的推荐理由。"""
    joined = (query or "").lower()
    hits = []
    for mood in t.get("moods") or []:
        if mood in joined or any(mood in tok for tok in tokens):
            hits.append("情绪:" + mood)
    for tag in t.get("tags") or []:
        if tag.lower() in joined:
            hits.append("母题:" + tag)
    for genre in t.get("genre") or []:
        if genre in joined:
            hits.append("类型:" + genre)
    return hits[:3]


def search(query, kind=None, k=8, min_score=0.5):
    """按灵感描述检索相似作品（BM25 + 情绪命中加权）。"""
    titles = _load()
    if not titles or not (query or "").strip():
        return []
    tokens = _query_terms(query)
    if not tokens:
        return []
    index = _index()
    low = query.lower()
    ranked = []
    for i, t in enumerate(titles):
        if kind and t["kind"] != kind:
            continue
        score = index.score(tokens, i)
        if score <= 0:
            continue
        bonus = 0.0
        for mood in t.get("moods") or []:
            if mood in low:
                bonus += 1.6
        for tag in t.get("tags") or []:
            if tag and tag.lower() in low:
                bonus += 1.2
        for genre in t.get("genre") or []:
            if genre in low:
                bonus += 0.8
        total = score + bonus
        if total < min_score:
            continue
        item = dict(t)
        item["score"] = round(float(total), 3)
        item["why"] = _overlap_reasons(t, query, tokens)
        ranked.append(item)
    ranked.sort(key=lambda x: -x["score"])
    return ranked[:k]


def similar(title_id, k=6):
    titles = _load()
    base = _cache["by_id"].get(title_id)
    if not base:
        return []
    return [x for x in search(" ".join(base.get("tags") or []) + " " + base.get("synopsis", ""),
                              kind=None, k=k + 1) if x["id"] != title_id][:k]


def suggest(idea, k=6):
    """一次给出：推荐题材 + 情绪 + 类型 + 相似作品（给前端/LLM 用）。"""
    from collections import Counter
    matches = search(idea, k=max(k * 3, 12))
    kinds = Counter(m["kind"] for m in matches)
    moods = Counter(m for m in matches for m in (m.get("moods") or []))
    genres = Counter(g for m in matches for g in (m.get("genre") or []))
    predicted = []
    for kind, n in kinds.most_common():
        predicted.append({"kind": kind, "score": n, "description": KIND_DESC[kind]})
    if not predicted:
        for kw, hints in KIND_HINTS.items():
            if any(h in idea for h in hints):
                predicted.append({"kind": kw, "score": 1, "description": KIND_DESC[kw]})
        if not predicted:
            predicted = [{"kind": k, "score": 0, "description": KIND_DESC[k]}
                         for k in KIND_ORDER[:1]]
    return {
        "idea": idea,
        "kinds": predicted[:3],
        "moods": [{"mood": m, "count": n} for m, n in moods.most_common(5)],
        "genres": [{"genre": g, "count": n} for g, n in genres.most_common(5)],
        "titles": matches[:k],
    }


def prompt_block(idea, k=6):
    """把真实影片库检索结果格式化成可直接塞进 LLM 提示词的文本。"""
    result = suggest(idea, k=k)
    lines = ["【Filmmate 真实影片参考库｜按灵感检索】",
             "用户灵感：" + (idea or "")]
    if result["kinds"]:
        lines.append("推荐先选题材：" + "；".join(
            f"{x['kind']}（{x['description']}）" for x in result["kinds"]))
    if result["moods"]:
        lines.append("情绪基调参考：" + "、".join(x["mood"] for x in result["moods"]))
    if result["genres"]:
        lines.append("类型参考：" + "、".join(x["genre"] for x in result["genres"]))
    lines.append("")
    lines.append("相似作品（每部都带 B 站可看链接与 10 张静帧）：")
    for i, t in enumerate(result["titles"], 1):
        why = "；".join(t.get("why") or []) or "；".join(t.get("tags") or [])[:40]
        lines.append(
            f"{i}. {t['title_zh']}（{t['title_en']}，{t['year']}，{t['duration']}）"
            f"｜情绪：{'/'.join(t.get('moods') or [])}｜{t.get('synopsis', '')}"
            f"｜参考点：{why}｜原片：{t.get('url', '')}")
    lines.append("")
    lines.append("请基于以上真实作品，给出 2–3 个可拍的创作思路（每个思路说明：题材定位、核心冲突、"
                 "参考影片的哪一点可借鉴、以及一个视觉/声音上的具体处理），不要虚构影片信息。")
    return "\n".join(lines)


def main():
    import sys
    idea = " ".join(sys.argv[1:]).strip() or "一个外卖员在暴雨夜捡到一部手机，里面有一段不该看到的视频"
    print("==", idea)
    print("库：", stats())
    print("\n可选题材：")
    for item in kind_options():
        print(f"  - {item['kind']}（{item['count']} 部）：{item['description']}")
    print("\n推荐：")
    print(prompt_block(idea))


if __name__ == "__main__":
    main()
