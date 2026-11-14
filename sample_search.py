"""Retrieve timestamped clips from the original video annotations."""
import hashlib
import json
import logging
import os
import tempfile
from functools import lru_cache
from threading import Lock

import config
import rag

MODEL = "intfloat/multilingual-e5-small"
SOURCE = config.BASE_DIR / "_ref" / "AI-Project" / "AI-Project"
CACHE = config.BASE_DIR / "data" / "sample-index" / "embeddings.npz"
logger = logging.getLogger(__name__)
_index_lock = Lock()


@lru_cache(maxsize=1)
def _corpus():
    videos = {}
    records = {}
    for path in sorted(SOURCE.glob("samplesv*.json")):
        video = json.loads(path.read_text(encoding="utf-8-sig"))
        video_id = video["youtube_video_id"]
        segments = videos.setdefault(video_id, {})
        for segment in video["segments"]:
            start, end = segment["time_start"], segment["time_end"]
            key = (video_id, start, end)
            segments.setdefault((start, end), segment["description"])
            records.setdefault(key, {
                "video_id": video_id, "title": video["title"], "start": start, "end": end,
                "description": segment["description"],
                "keywords": video.get("video_keywords", []) + segment.get("keywords", []),
            })
    return list(records.values()), {
        video_id: sorted(segments.items(), key=lambda item: _seconds(item[0][0]))
        for video_id, segments in videos.items()
    }


def _seconds(timestamp):
    seconds = 0
    for part in timestamp.split(":"):
        seconds = seconds * 60 + int(part)
    return seconds


@lru_cache(maxsize=1)
def _documents():
    records, _ = _corpus()
    return [f"{item['title']}. {item['description']} {' '.join(item['keywords'])}" for item in records]


@lru_cache(maxsize=1)
def _keyword_index():
    return rag.BM25Index(_documents())


@lru_cache(maxsize=1)
def _vector_index():
    import numpy as np
    from sentence_transformers import SentenceTransformer

    passages = [f"passage: {document}" for document in _documents()]
    fingerprint = hashlib.sha256(json.dumps([MODEL, passages], ensure_ascii=False).encode()).hexdigest()
    model = SentenceTransformer(MODEL)
    try:
        with np.load(CACHE) as saved:
            vectors = saved["vectors"]
            if str(saved["fingerprint"]) == fingerprint and vectors.shape == (
                len(passages), model.get_sentence_embedding_dimension()
            ):
                return model, vectors
    except (OSError, ValueError, KeyError):
        pass

    vectors = model.encode(passages, normalize_embeddings=True, show_progress_bar=False)
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=CACHE.parent, suffix=".npz", delete=False) as temp:
            temp_path = temp.name
        try:
            np.savez(temp_path, fingerprint=fingerprint, vectors=vectors)
            os.replace(temp_path, CACHE)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
    except OSError:
        logger.warning("Could not save the sample vector index", exc_info=True)
    return model, vectors


def _rank(query):
    if config.EMBEDDING_MODE != "bm25":
        try:
            with _index_lock:
                model, vectors = _vector_index()
            embedding = model.encode([f"query: {query}"], normalize_embeddings=True)[0]
            return vectors @ embedding
        except ImportError:
            logger.info("SentenceTransformers unavailable; using sample keyword search")
        except Exception:
            logger.warning("Sample vector search failed; using keyword search", exc_info=True)
    index = _keyword_index()
    tokens = rag.tokenize(query)
    return [index.score(tokens, i) for i in range(index.n)]


def search_segments(query, k=3):
    """Return the best matched segment per video and its surrounding shots."""
    query = query.strip()
    records, videos = _corpus()
    if not query or not records or k <= 0:
        return []
    scores = _rank(query)
    ranked = sorted(range(len(scores)), key=scores.__getitem__, reverse=True)
    results = []
    seen = set()
    for i in ranked:
        score = float(scores[i])
        record = records[i]
        video_id = record["video_id"]
        if score <= 0 or video_id in seen:
            continue
        sequence = videos[video_id]
        match = (record["start"], record["end"])
        position = next(i for i, (times, _) in enumerate(sequence) if times == match)
        results.append({
            **record, "score": round(score, 4),
            "url": f"https://www.youtube.com/watch?v={video_id}&t={_seconds(record['start'])}s",
            "neighboring_shots": [
                {"start": start, "end": end, "description": description}
                for (start, end), description in sequence[max(0, position - 1):position + 2]
                if (start, end) != match
            ],
        })
        seen.add(video_id)
        if len(results) == k:
            break
    return results


def segment_context(hits):
    fields = ("title", "video_id", "start", "end", "description", "url", "neighboring_shots")
    return json.dumps([{field: hit[field] for field in fields} for hit in hits], ensure_ascii=False)
