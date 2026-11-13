"""案例库检索:把高质量视频作品的详细信息(剧本梗概、分镜要点、拍摄 Rundown、
设备清单、经验教训)做成可检索的样本库,供模型通过 search_cases 工具调用。

检索方式与知识库一致:BM25(零依赖)/ dense 向量(装了 sentence-transformers 时),
向量缓存到 cases/vectors/ 下。
"""
import json
import logging
import time
from pathlib import Path

import config
import rag

logger = logging.getLogger("cases")

# 优先用「剧本 + 原片」双源库；没有时退回真实短片库
_SCRIPTED = config.BASE_DIR / "data" / "library" / "films_scripted.json"
CASES_FILE = _SCRIPTED if _SCRIPTED.exists() else config.BASE_DIR / "data" / "library" / "films_real.json"

_CACHE = {"cases": None, "bm25": None, "dense": None}


def _film_to_case(film):
    """把「剧本 + 原片」或真实短片元数据转成检索用的案例结构。

    只保留来源可核验的字段；不臆造导演、预算、分镜、通告单。
    """
    moods = film.get("moods") or film.get("tags") or []
    script = film.get("script") or {}
    has_script = bool(script.get("page"))
    return {
        "id": film["id"],
        "title": film.get("title", ""),
        "title_en": film.get("title_en", ""),
        "year": film.get("year", ""),
        "type": "电影" if has_script else film.get("category", "短片"),
        "genre": " / ".join(moods) if moods else "短片",
        "duration": film.get("duration", ""),
        "budget": "—",
        "crew": film.get("owner", ""),
        "locations": [],
        "equipment": [],
        "logline": film.get("summary", "") if len(film.get("summary", "")) >= 30 else (
            f"{film.get('title_en', '')} ({film.get('year', '')})".strip() if film.get("title_en") else ""
        ),
        "tags": moods,
        "style": "",
        "lessons": "",
        "source": "scriptslug + bilibili" if has_script else "bilibili",
        "url": film.get("url", ""),
        "cover": film.get("cover", ""),
        "stat": film.get("stat") or {"view": film.get("play", 0)},
        "script_page": script.get("page", ""),
        "script_pdf": script.get("pdf", ""),
        "frames": film.get("frames", []),
        "verified_at": film.get("verified_at", ""),
    }


def load_cases():
    if _CACHE["cases"] is None:
        if not CASES_FILE.exists():
            logger.warning("真实短片库不存在：%s", CASES_FILE)
            _CACHE["cases"] = []
            return _CACHE["cases"]
        data = json.loads(CASES_FILE.read_text(encoding="utf-8"))
        films = data.get("films", [])
        _CACHE["cases"] = [_film_to_case(f) for f in films if f.get("title") and f.get("url")]
        logger.info("真实短片库加载完成: %d 部（来源 Bilibili，校验时间 %s）",
                    len(_CACHE["cases"]), data.get("verified_at", "?"))
    return _CACHE["cases"]


def count():
    return len(load_cases())


def _doc_text(case):
    """案例的检索文本：标题/类型/题材/梗概/标签 + v2 的结构、场次、镜头、制片信息。"""
    structure = case.get("structure") or {}
    beats = " ".join(f"{b.get('beat', '')} {b.get('note', '')}" for b in structure.get("beats", []))
    scenes = " ".join(
        f"{s.get('heading', '')} {s.get('synopsis', '')} {s.get('day_night', '')}"
        for s in case.get("scenes", [])
    )
    shots = " ".join(
        f"{s.get('size', '')} {s.get('angle', '')} {s.get('movement', '')} {s.get('purpose', '')}"
        for s in case.get("shot_list", [])[:10]
    )
    production = case.get("production") or {}
    return " ".join([
        case["title"], case["type"], case["genre"], case["logline"],
        " ".join(case.get("tags", [])), " ".join(case.get("locations", [])),
        case.get("style", ""), case.get("lessons", ""),
        " ".join(case.get("themes", [])), case.get("tone", ""),
        " ".join(case.get("reference_films", [])),
        structure.get("act1", ""), structure.get("act2", ""), structure.get("act3", ""),
        beats, scenes, shots,
        production.get("schedule_summary", ""), " ".join(production.get("risks", [])),
        case.get("rag_keywords", "") if isinstance(case.get("rag_keywords"), str)
        else " ".join(case.get("rag_keywords", [])),
    ])


def _bm25_search(query, k):
    if _CACHE["bm25"] is None:
        cases = load_cases()
        _CACHE["bm25"] = (rag.BM25Index([_doc_text(c) for c in cases]), cases)
    idx, cases = _CACHE["bm25"]
    q_tokens = rag.tokenize(query)
    raw = [(idx.score(q_tokens, i), i) for i in range(idx.n)]
    # 标签命中加权:查询原文直接包含 tag(+2),或查询词是 tag 的子串(+1),题材/类型匹配优先
    low_q = query.lower()
    scores = []
    for s, i in raw:
        bonus = 0.0
        # 片名命中权重最高：用户常常直接报片名
        title = str(cases[i].get("title", "")).lower()
        if title and title in low_q:
            bonus += 6.0
        else:
            for t in q_tokens:
                if len(t) >= 2 and t in title:
                    bonus += 3.0
        for tag in cases[i].get("tags", []):
            if tag.lower() in low_q:
                bonus += 2.0
            elif any(t in tag for t in q_tokens if len(t) >= 2):
                bonus += 1.0
        scores.append((s + bonus, i))
    scores.sort(key=lambda x: -x[0])
    return scores[:k]


def _dense_search(query, k):
    import numpy as np
    from sentence_transformers import SentenceTransformer

    if _CACHE["dense"] is None:
        cases = load_cases()
        cache_file = CASES_FILE.parent / "vectors" / "embeddings.npz"
        model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
        if cache_file.exists():
            npz = np.load(cache_file)
            # 案例数变化（如加载了扩充卷）时必须重建，否则索引会错位
            if str(npz["model"]) == str(model) and len(npz["vecs"]) == len(cases):
                _CACHE["dense"] = (model, npz["vecs"])
        if _CACHE["dense"] is None:
            t0 = time.time()
            vecs = model.encode([_doc_text(c) for c in cases], normalize_embeddings=True, show_progress_bar=False)
            cache_file.parent.mkdir(exist_ok=True)
            np.savez(cache_file, vecs=vecs, model=str(model))
            logger.info("案例向量化完成(%d 部, %.1fs)", len(cases), time.time() - t0)
            _CACHE["dense"] = (model, vecs)
    model, vecs = _CACHE["dense"]
    q = model.encode([query], normalize_embeddings=True)[0]
    sims = vecs @ q
    return [(float(sims[i]), int(i)) for i in np.argsort(-sims)[:k]]


def search_cases(query: str, k: int = 3, min_score: float = 0.0):
    """按语义/关键词检索相关案例。返回案例 dict 列表(带 score)。"""
    cases = load_cases()
    mode = config.EMBEDDING_MODE
    if mode == "auto":
        try:
            import sentence_transformers  # noqa: F401
            mode = "dense"
        except ImportError:
            mode = "bm25"
    if mode == "dense":
        try:
            ranked = _dense_search(query, k)
            logger.info("案例检索模式: dense 向量")
        except Exception as e:  # noqa: BLE001
            logger.warning("dense 案例检索失败(%s),回退 BM25", e)
            ranked = _bm25_search(query, k)
    else:
        ranked = _bm25_search(query, k)
        logger.info("案例检索模式: BM25")
    results = []
    for s, i in ranked:
        if s < min_score:
            continue
        c = dict(cases[i])
        c["score"] = round(float(s), 4)
        results.append(c)
    return results


def case_to_text(case):
    """把真实短片压缩成给模型的参考文本（只陈述来源可核验的信息）。"""
    views = (case.get("stat") or {}).get("view")
    lines = [
        f"【真实短片参考】《{case['title']}》（{case['type']}·{case['duration']}·来源 Bilibili）",
        f"简介：{case.get('logline', '')}",
    ]
    if case.get("tags"):
        lines.append(f"题材/看点标签：{'、'.join(case['tags'])}")
    if case.get("crew"):
        lines.append(f"发布者：{case['crew']}")
    if views:
        lines.append(f"播放量：{views:,}")
    if case.get("url"):
        lines.append(f"来源链接：{case['url']}（可直接播放）")
    if case.get("script_page"):
        lines.append(f"原始剧本：{case['script_page']}（PDF: {case.get('script_pdf', '')}）")
    lines.append("说明：以上为平台公开元数据与剧本来源，不含制作预算/分镜/通告单；引用时请注明来源。")
    return "\n".join(lines)


def cases_context(query: str, k: int = 2):
    """检索案例并生成 提示词上下文 + 前端引用列表。"""
    hits = search_cases(query, k=k)
    ctx = "\n\n".join(case_to_text(c) for c in hits)
    refs = [{"id": c["id"], "title": c["title"], "type": c["type"], "genre": c["genre"],
             "logline": c["logline"], "score": c["score"], "url": c.get("url", ""),
             "cover": c.get("cover", ""), "duration": c.get("duration", ""),
             "source": c.get("source", ""), "tags": c.get("tags", [])} for c in hits]
    return ctx, refs
