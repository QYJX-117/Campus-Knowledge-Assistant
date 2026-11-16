"""
Hot FAQ semantic cache — ported from Design `hot_retriever.py`.
High-frequency Q&A cache with vector similarity matching + Jaccard penalty.
Adapted to use actual project's local BGE embedding instead of Alibaba API.

Storage: `data/hot_faq/hot_faq_meta.json`
Max entries: 500 (configurable via HOT_FAQ_MAX_SIZE)
Hit threshold: 0.85 (configurable via HOT_FAQ_THRESHOLD)
Expiry: 365 days (configurable via HOT_FAQ_EXPIRE_DAYS)
"""
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import numpy as np

HOT_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "hot_faq"
HOT_META_FILE = HOT_DIR / "hot_faq_meta.json"


def _get_embedding_model():
    """Lazy-load the local BGE embedding model (reuse engine's singleton)."""
    from .engine import _get_local_embedding_model
    return _get_local_embedding_model()


def embed_query_local(query: str) -> np.ndarray:
    """Vectorize a query using the local BGE model (not Alibaba API)."""
    model = _get_embedding_model()
    vec = model.encode(query, normalize_embeddings=True)
    return np.array(vec, dtype=np.float32)


def load_hot_faq() -> list[dict]:
    """Load hot_faq_meta.json; return empty list if missing or corrupt."""
    if not HOT_META_FILE.exists():
        return []
    try:
        with open(HOT_META_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, Exception) as e:
        print(f"  [热库] Load failed: {e}")
        return []


def _save_hot_faq(faqs: list[dict]) -> None:
    """Persist hot FAQ data to JSON."""
    HOT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(HOT_META_FILE, "w", encoding="utf-8") as f:
            json.dump(faqs, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"  [热库] Save failed: {e}")


def retrieve(query: str, threshold: float = 0.85) -> Optional[str]:
    """
    Hot-cache retrieval:
    1. Embed query via local BGE
    2. Compute cosine similarity (inner product) with every cached question
    3. Apply Jaccard character-overlap penalty for dissimilar questions
    4. Skip expired entries
    5. Return cached answer if best score >= threshold, else None
    """
    faqs = load_hot_faq()
    if not faqs:
        return None

    threshold = float(os.getenv("HOT_FAQ_THRESHOLD", str(threshold)))

    try:
        q_vec = embed_query_local(query)
    except Exception as e:
        print(f"  [热库] Query embedding failed: {e}")
        return None

    now_str = datetime.now(timezone.utc).isoformat()
    best_score = -1.0
    best_answer = None

    for faq in faqs:
        # Expiry check
        expire_at = faq.get("expire_at", "")
        if expire_at and expire_at < now_str:
            continue

        stored_vec = np.array(faq.get("question_vec", []), dtype=np.float32)
        if stored_vec.size == 0:
            continue

        score = float(np.dot(q_vec, stored_vec))

        # Jaccard character-overlap penalty
        faq_question = faq.get("question", "")
        if faq_question:
            query_chars = set(query)
            faq_chars = set(faq_question)
            jaccard = len(query_chars & faq_chars) / max(1, len(query_chars | faq_chars))
            if jaccard < 0.4:
                score = score * 0.85

        if score > best_score:
            best_score = score
            best_answer = faq.get("answer", "")

    if best_score >= threshold and best_answer:
        print(f"  [热库] 命中! similarity={best_score:.4f}")
        return best_answer

    return None


def add_to_hot_faq(question: str, answer: str) -> None:
    """
    Add or update a hot FAQ entry.
    - Deduplicates by exact question match
    - Enforces max size (FIFO eviction)
    - Sets 1-year expiry
    """
    max_size = int(os.getenv("HOT_FAQ_MAX_SIZE", "500"))
    expire_days = int(os.getenv("HOT_FAQ_EXPIRE_DAYS", "365"))

    faqs = load_hot_faq()

    # Embed the question
    try:
        vec = embed_query_local(question)
        vec_list = vec.tolist()
    except Exception as e:
        print(f"  [热库] Embedding failed for add: {e}")
        return

    # Deduplicate — update existing
    for faq in faqs:
        if faq.get("question") == question:
            faq["answer"] = answer
            faq["question_vec"] = vec_list
            faq["expire_at"] = (datetime.now(timezone.utc) + timedelta(days=expire_days)).isoformat()
            _save_hot_faq(faqs)
            print(f"  [热库] Updated: {question[:30]}...")
            return

    # Evict oldest if at capacity
    if len(faqs) >= max_size:
        removed = faqs.pop(0)
        print(f"  [热库] Evicted oldest: {removed.get('question', '')[:30]}...")

    faqs.append({
        "question": question,
        "question_vec": vec_list,
        "answer": answer,
        "expire_at": (datetime.now(timezone.utc) + timedelta(days=expire_days)).isoformat(),
    })
    _save_hot_faq(faqs)
    print(f"  [热库] Added: {question[:30]}... (total {len(faqs)})")


def hot_faq_stats() -> dict:
    """Return hot cache statistics."""
    faqs = load_hot_faq()
    now = datetime.now(timezone.utc).isoformat()
    active = sum(1 for f in faqs if f.get("expire_at", "") >= now)
    return {
        "total_entries": len(faqs),
        "active_entries": active,
        "expired_entries": len(faqs) - active,
        "max_size": int(os.getenv("HOT_FAQ_MAX_SIZE", "500")),
    }
