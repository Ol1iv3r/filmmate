"""RAG 检索模块。

两种模式(EMBEDDING_MODE):
  - dense: sentence-transformers 多语言模型把知识条目录入向量,查询用余弦相似度检索
           (需要 pip install sentence-transformers,首次运行会下载模型并缓存向量)
  - bm25 : 经典 Okapi BM25 关键词检索 + jieba 中文分词(零额外依赖,离线可用)
  - auto : 检测到 sentence-transformers 就用 dense,否则回退 bm25(默认)
"""
import json
import logging
import math
import re
import time
from pathlib import Path

import config

logger = logging.getLogger("rag")

_CACHE = {"entries": None, "bm25": None, "dense": None}
_last_mode = "bm25"


def current_mode():
    """最近一次检索使用的模式(dense/bm25),供调用方决定分数阈值。"""
    mode = config.EMBEDDING_MODE
    if mode == "auto":
        try:
            import sentence_transformers  # noqa: F401
            mode = "dense"
        except ImportError:
            mode = "bm25"
    return mode


def is_relevant(query: str):
    """判断查询是否与知识库相关。

    短查询（如「香港」）会被 BM25 的长度归一化压低分数，光看阈值会误判，
    因此额外检查标题/分类的字面命中。
    """
    query = (query or "").strip()
    if not query:
        return False
    mode = current_mode()
    if mode == "dense":
        return len(retrieve(query, k=1, min_score=0.25)) > 0

    hits = retrieve(query, k=1, min_score=0)
    if not hits:
        return False
    top = hits[0]
    low = query.lower()
    label = f"{top.get('title', '')} {top.get('category', '')}".lower()
    if len(query) <= 8 and low in label:
        return True
    return top.get("score", 0) >= 4.5


def _load_entries():
    if _CACHE["entries"] is None:
        data = json.loads(config.KNOWLEDGE_FILE.read_text(encoding="utf-8"))
        entries = list(data["entries"])
        # 扩充卷：data/library/knowledge_extra.json（缺失时静默跳过）
        extra_file = config.BASE_DIR / "data" / "library" / "knowledge_extra.json"
        if extra_file.exists():
            try:
                extra = json.loads(extra_file.read_text(encoding="utf-8")).get("entries", [])
                known = {e.get("id") for e in entries}
                added = [e for e in extra if e.get("id") not in known and e.get("content")]
                entries.extend(added)
                logger.info("知识库扩充卷加载 %d 条", len(added))
            except (ValueError, OSError) as exc:
                logger.warning("知识库扩充卷读取失败(%s)，仅使用基础库", exc)
        _CACHE["entries"] = entries
        logger.info("知识库加载完成: %d 条", len(_CACHE["entries"]))
    return _CACHE["entries"]


# 疑问词/虚词：会稀释检索信号（例如「推镜头什么时候用」被「什么时候用」带偏）
STOPWORDS = {
    "什么", "什么时候", "怎么", "怎样", "如何", "为什么", "哪个", "哪些", "多少", "是否",
    "可以", "应该", "需要", "一下", "这个", "那个", "我们", "你们", "他们", "时候",
    "的话", "一个", "一些", "还是", "或者", "以及", "对于", "关于", "有没有", "请问",
    "the", "a", "an", "is", "are", "of", "to", "how", "what", "when", "why", "which",
    "should", "can", "do", "does", "i", "we", "you", "it", "for", "and", "or",
}


def tokenize(text: str):
    """中文用 jieba 分词,英文/数字按词切分,统一小写,并去掉疑问词/虚词。"""
    text = text.lower()
    tokens = []
    try:
        import jieba
        for seg in jieba.cut(re.sub(r"[^\w\u4e00-\u9fff]+", " ", text)):
            seg = seg.strip()
            if not seg:
                continue
            if re.fullmatch(r"[\u4e00-\u9fff]+", seg):  # 纯中文词
                tokens.append(seg)
            else:  # 英文/数字再按词拆分
                tokens.extend(re.findall(r"[a-z0-9]+", seg))
    except ImportError:
        tokens = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", text)
    return [t for t in tokens if len(t) > 0 and t not in STOPWORDS]


class BM25Index:
    """经典 Okapi BM25 实现,针对短知识库条目。"""

    def __init__(self, docs):
        self.k1, self.b = 1.5, 0.75
        self.docs = docs
        self.doc_tokens = [tokenize(d) for d in docs]
        self.avgdl = sum(len(t) for t in self.doc_tokens) / max(1, len(docs))
        self.df = {}
        for toks in self.doc_tokens:
            for t in set(toks):
                self.df[t] = self.df.get(t, 0) + 1
        self.n = len(docs)

    def score(self, query_tokens, doc_idx):
        toks = self.doc_tokens[doc_idx]
        if not toks:
            return 0.0
        tf = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        score = 0.0
        for q in query_tokens:
            if q not in self.df:
                continue
            idf = math.log(1 + (self.n - self.df[q] + 0.5) / (self.df[q] + 0.5))
            f = tf.get(q, 0)
            score += idf * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * len(toks) / self.avgdl))
        return score


def _bm25_retrieve(query: str, k: int):
    if _CACHE["bm25"] is None:
        entries = _load_entries()
        _CACHE["bm25"] = BM25Index([_searchable_text(e) for e in entries])
    idx = _CACHE["bm25"]
    q_tokens = tokenize(query)
    scores = [(idx.score(q_tokens, i), i) for i in range(idx.n)]
    scores.sort(key=lambda x: -x[0])
    return scores[:k]


def _dense_retrieve(query: str, k: int):
    """sentence-transformers 向量检索,向量缓存到 knowledge/vectors/ 下。"""
    import numpy as np
    from sentence_transformers import SentenceTransformer

    if _CACHE["dense"] is None:
        entries = _load_entries()
        cache_dir = config.KNOWLEDGE_FILE.parent / "vectors"
        cache_file = cache_dir / "embeddings.npz"
        model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
        if cache_file.exists():
            npz = np.load(cache_file)
            vecs, model_name = npz["vecs"], str(npz["model"])
            # 条目数变化（如加载了扩充卷）时必须重建，否则索引会错位
            if model_name == str(model) and len(vecs) == len(entries):
                _CACHE["dense"] = (model, vecs)
        if _CACHE["dense"] is None:
            t0 = time.time()
            vecs = model.encode([_searchable_text(e) for e in entries], normalize_embeddings=True, show_progress_bar=False)
            cache_dir.mkdir(exist_ok=True)
            np.savez(cache_file, vecs=vecs, model=str(model))
            logger.info("向量化完成(%d 条, %.1fs),已缓存", len(entries), time.time() - t0)
            _CACHE["dense"] = (model, vecs)
    model, vecs = _CACHE["dense"]
    q = model.encode([query], normalize_embeddings=True)[0]
    sims = (vecs @ q)
    top = np.argsort(-sims)[:k]
    return [(float(sims[i]), int(i)) for i in top]


def _searchable_text(entry):
    return f"{entry['title']} {entry.get('category','')} {' '.join(entry.get('keywords', []))} {entry['content']}"


def retrieve(query: str, k: int = None, min_score: float = None):
    """返回 Top-K 知识条目:[{title, category, content, score}]"""
    k = k or config.TOP_K
    min_score = min_score if min_score is not None else config.MIN_SCORE
    entries = _load_entries()
    mode = config.EMBEDDING_MODE
    if mode == "auto":
        try:
            import sentence_transformers  # noqa: F401
            mode = "dense"
        except ImportError:
            mode = "bm25"
    if mode == "dense":
        try:
            ranked = _dense_retrieve(query, k)
            logger.info("检索模式: dense 向量")
            return [
                {**{kk: v for kk, v in entries[i].items() if kk != "keywords"},
                 "score": round(float(s), 4)}
                for s, i in ranked if s >= min_score
            ]
        except Exception as e:  # 模型未下载等异常时回退
            logger.warning("dense 检索失败(%s),回退 BM25", e)
    ranked = _bm25_retrieve(query, k)
    logger.info("检索模式: BM25")
    return [
        {**{kk: v for kk, v in entries[i].items() if kk != "keywords"},
         "score": round(float(s), 4)}
        for s, i in ranked if s >= min_score
    ]


def count():
    return len(_load_entries())


def build_rag_context(query: str):
    """把检索结果拼成提示词上下文,并返回给前端展示的引用列表。"""
    hits = retrieve(query)
    ctx_parts = []
    citations = []
    for h in hits:
        ctx_parts.append(f"[{h['category']}] {h['title']}\n{h['content']}")
        citations.append({"title": h["title"], "category": h["category"], "score": h["score"]})
    return "\n\n---\n\n".join(ctx_parts), citations
