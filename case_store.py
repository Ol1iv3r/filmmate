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

CASES_FILE = config.BASE_DIR / "cases" / "cases.json"

_CACHE = {"cases": None, "bm25": None, "dense": None}


def load_cases():
    if _CACHE["cases"] is None:
        data = json.loads(CASES_FILE.read_text(encoding="utf-8"))
        _CACHE["cases"] = data["cases"]
        logger.info("案例库加载完成: %d 部作品", len(_CACHE["cases"]))
    return _CACHE["cases"]


def count():
    return len(load_cases())


def _doc_text(case):
    """案例的检索文本:标题+类型+题材+梗概+标签+经验教训。"""
    return " ".join([
        case["title"], case["type"], case["genre"], case["logline"],
        " ".join(case.get("tags", [])), " ".join(case.get("locations", [])),
        case.get("style", ""), case.get("lessons", ""),
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
            if str(npz["model"]) == str(model):
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
    """把案例压缩成给模型的文本(控制 token)。"""
    rundown = " / ".join(f"{r['time']} {r['item']}" for r in case.get("rundown", []))
    lines = [
        f"【案例】{case['title']}({case['type']}·{case['genre']}·{case['duration']}·{case['budget']})",
        f"梗概: {case['logline']}",
        f"分镜要点: {';'.join(case.get('storyboard_highlights', []))}",
        f"拍摄Rundown: {rundown}",
        f"设备: {'、'.join(case.get('equipment', []))}",
        f"经验教训: {case.get('lessons', '')}",
    ]
    return "\n".join(lines)


def cases_context(query: str, k: int = 2):
    """检索案例并生成 提示词上下文 + 前端引用列表。"""
    hits = search_cases(query, k=k)
    ctx = "\n\n".join(case_to_text(c) for c in hits)
    refs = [{"id": c["id"], "title": c["title"], "type": c["type"], "genre": c["genre"],
             "logline": c["logline"], "score": c["score"]} for c in hits]
    return ctx, refs
