"""RAG Engine — modular pipeline with dense/sparse/hybrid retrieval + streaming LLM.
Advanced strategies: cache, query-decomposition, context-compression, Self-RAG, CRAG."""

from __future__ import annotations

import json
import hashlib
import copy
import re
import shutil
import sqlite3
import tempfile
import threading
import time
import random
from collections import OrderedDict
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import faiss
import numpy as np
from llama_index.core import Settings, StorageContext, VectorStoreIndex
from llama_index.core.chat_engine import CondensePlusContextChatEngine
from llama_index.core.llms import ChatMessage, MessageRole
from llama_index.core.memory import ChatMemoryBuffer
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import Document, MetadataMode, NodeWithScore, TextNode
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.llms.openai import OpenAI
from llama_index.vector_stores.faiss import FaissVectorStore
from rank_bm25 import BM25Okapi
import jieba

from ..config import settings
from ..database import connect, utc_now
from ..utils.guardrails import is_question_safe, sanitize_output as guard_sanitize
from .hot_cache import retrieve as hot_cache_retrieve, add_to_hot_faq as hot_cache_add

# ── Question-Answer Cache ────────────────────────────────────────
_CACHE: OrderedDict[str, tuple[float, dict]] = OrderedDict()
_CACHE_LOCK = threading.Lock()
_CACHE_MAX_SIZE = 512


def _cache_key(question: str, strategy: str) -> str:
    return hashlib.sha256(f"{question}|{strategy}".encode("utf-8")).hexdigest()


def _cache_get(question: str, strategy: str) -> dict | None:
    if not settings.cache_enabled:
        return None
    key = _cache_key(question, strategy)
    with _CACHE_LOCK:
        entry = _CACHE.get(key)
        if entry is None:
            return None
        ts, result = entry
        if time.time() - ts > settings.cache_ttl_seconds:
            del _CACHE[key]
            return None
        # Move to end (LRU)
        _CACHE.move_to_end(key)
        return dict(result)


def _cache_set(question: str, strategy: str, result: dict) -> None:
    if not settings.cache_enabled:
        return
    key = _cache_key(question, strategy)
    with _CACHE_LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
        _CACHE[key] = (time.time(), result)
        while len(_CACHE) > _CACHE_MAX_SIZE:
            _CACHE.popitem(last=False)

# ── Semantic Chunker ────────────────────────────────────────────
class SemanticChunker:
    """Split text by semantic boundaries using embedding similarity between sentences.

    Course §13.4: Instead of fixed character-length chunking, detect semantic shifts
    by measuring cosine similarity between consecutive sentence embeddings. When
    similarity drops below the threshold, insert a chunk boundary.

    Falls back to length-based chunking when embeddings are unavailable.
    """

    def __init__(self, embed_model, threshold: float = 0.6,
                 min_chunk_size: int = 100, max_chunk_size: int = 1000):
        self._embed = embed_model
        self.threshold = threshold
        self.min_chunk = min_chunk_size
        self.max_chunk = max_chunk_size

    def _sentences(self, text: str) -> list[str]:
        raw = re.split(r"(?<=[。！？!?；;])\s*|\n{2,}", text)
        return [s.strip() for s in raw if len(s.strip()) > 2]

    def _embed_sentences(self, sentences: list[str]) -> list[list[float]] | None:
        try:
            return self._embed._get_text_embeddings(sentences)
        except Exception:
            pass
        # Fallback: use the local model directly
        try:
            return _get_local_embedding_model().encode(sentences, normalize_embeddings=True).tolist()
        except Exception:
            return None

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na = np.linalg.norm(a)
        nb = np.linalg.norm(b)
        if na == 0 or nb == 0:
            return 0.0
        return float(dot / (na * nb))

    def split(self, text: str) -> list[str]:
        """Split text into semantically coherent chunks."""
        sentences = self._sentences(text)
        if len(sentences) <= 1:
            return [text] if text.strip() else []

        embeddings = self._embed_sentences(sentences)
        if embeddings is None or len(embeddings) != len(sentences):
            # Fallback: simple length-based splitting
            return self._length_fallback(text)

        # Compute pairwise similarities between consecutive sentences
        sims = []
        for i in range(len(embeddings) - 1):
            sims.append(self._cosine(embeddings[i], embeddings[i + 1]))

        # Find breakpoints: where similarity < threshold AND we've accumulated enough content
        breakpoints: list[int] = []
        current_len = 0
        for i, sim in enumerate(sims):
            current_len += len(sentences[i])
            if sim < self.threshold and current_len >= self.min_chunk:
                breakpoints.append(i + 1)
                current_len = 0

        # Build chunks
        chunks: list[str] = []
        start = 0
        for bp in breakpoints:
            chunk = "".join(sentences[start:bp])
            if len(chunk) > self.max_chunk:
                # Sub-split oversized chunks
                for sub in self._length_split(chunk, self.max_chunk):
                    chunks.append(sub)
            else:
                chunks.append(chunk)
            start = bp

        # Last chunk
        if start < len(sentences):
            chunk = "".join(sentences[start:])
            if len(chunk) > self.max_chunk:
                chunks.extend(self._length_split(chunk, self.max_chunk))
            else:
                chunks.append(chunk)

        # Filter out too-small chunks, but keep at least one if all would be dropped
        filtered = [c for c in chunks if len(c.strip()) >= self.min_chunk]
        if not filtered and chunks:
            # When all chunks are smaller than min_chunk (e.g., short document),
            # keep the largest one rather than returning nothing
            filtered = [max(chunks, key=lambda c: len(c.strip()))]
        return filtered

    def _length_fallback(self, text: str) -> list[str]:
        return self._length_split(text, self.max_chunk)

    @staticmethod
    def _length_split(text: str, size: int) -> list[str]:
        """Simple length-based splitting as fallback."""
        chunks = []
        for i in range(0, len(text), size):
            chunks.append(text[i:i + size])
        return chunks


# ── Parent-Child store ─────────────────────────────────────────
# Maps parent_id → {"text": str, "title": str, "metadata": dict}
_parent_map: dict[str, dict] = {}
_PARENT_MAP_LOCK = threading.Lock()


def _get_parent_map() -> dict:
    with _PARENT_MAP_LOCK:
        return dict(_parent_map)


def _set_parent_map(data: dict) -> None:
    global _parent_map
    with _PARENT_MAP_LOCK:
        _parent_map = data


def _update_parent_map(entries: dict) -> None:
    with _PARENT_MAP_LOCK:
        _parent_map.update(entries)


# ── Local Embedding ────────────────────────────────────────────
_LOCAL_EMBED_MODEL = None
_LOCAL_EMBED_LOADED = False


class HashingEmbeddingModel:
    """Dependency-free 512d fallback for offline classroom demos."""

    dimension = 512

    def get_embedding_dimension(self) -> int:
        return self.dimension

    def encode(self, texts, normalize_embeddings: bool = True, show_progress_bar: bool = False):
        single = isinstance(texts, str)
        values = [texts] if single else list(texts)
        vectors = np.zeros((len(values), self.dimension), dtype=np.float32)
        for row, text in enumerate(values):
            compact = re.sub(r"\s+", "", str(text))
            features = list(jieba.cut(str(text)))
            features.extend(compact[i:i + 2] for i in range(max(0, len(compact) - 1)))
            for feature in features:
                if not feature.strip():
                    continue
                digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
                index = int.from_bytes(digest, "little") % self.dimension
                vectors[row, index] += 1.0
            if normalize_embeddings:
                norm = np.linalg.norm(vectors[row])
                if norm:
                    vectors[row] /= norm
        return vectors[0] if single else vectors


def _get_local_embedding_model():
    global _LOCAL_EMBED_MODEL, _LOCAL_EMBED_LOADED
    if _LOCAL_EMBED_LOADED:
        return _LOCAL_EMBED_MODEL
    from sentence_transformers import SentenceTransformer
    try:
        _LOCAL_EMBED_MODEL = SentenceTransformer(
            settings.local_embedding_model,
            local_files_only=not settings.allow_model_download,
        )
    except Exception as exc:
        print(f"[WARN] Local embedding unavailable, using offline hashing fallback: {exc}")
        _LOCAL_EMBED_MODEL = HashingEmbeddingModel()
    _LOCAL_EMBED_LOADED = True
    dim = _LOCAL_EMBED_MODEL.get_embedding_dimension()
    print(f"[OK] Local embedding loaded: {settings.local_embedding_model} ({dim}d)")
    return _LOCAL_EMBED_MODEL


from llama_index.core.embeddings import BaseEmbedding


class LocalEmbedding(BaseEmbedding):
    _model_name: str = ""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._m = _get_local_embedding_model()
        self._model_name = settings.local_embedding_model

    def _get_text_embedding(self, text: str) -> list[float]:
        return self._m.encode(text, normalize_embeddings=True).tolist()

    def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        batch_size = max(1, settings.embedding_batch_size)
        for start in range(0, len(texts), batch_size):
            batch = texts[start:start + batch_size]
            vectors.extend(
                self._m.encode(batch, normalize_embeddings=True, show_progress_bar=False).tolist()
            )
        return vectors

    def _get_query_embedding(self, query: str) -> list[float]:
        return self._get_text_embedding(query)

    async def _aget_text_embedding(self, text: str) -> list[float]:
        return self._get_text_embedding(text)

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return self._get_query_embedding(query)


# ── OpenAI-compatible LLM wrapper ──────────────────────────────
class CompatibleLLM(OpenAI):
    def _get_model_name(self) -> str:
        return "gpt-3.5-turbo"


# ── System Prompt ──────────────────────────────────────────────
HHU_SYSTEM_PROMPT = """你是河海大学校园问答助手。你需要基于检索资料，运用语言模型的归纳、解释、比较和组织能力，给出自然、完整且有层次的回答。

【回答要求】
1. 参考资料是事实边界，不得编造资料中没有的校内事实、数据、政策或结论
2. 先理解用户真正想解决的问题，再综合多份资料作答；禁止逐段复述、简单拼接原文或按来源逐条罗列
3. 用户要求评价或分析时，可以基于资料作审慎推断，但必须明确区分“资料事实”和“分析判断”
4. 资料不足以支持结论时，明确说明“现有资料仅能确认……，无法据此判断……”
5. 使用简洁、专业、自然的中文回答。每项关键事实应在对应语句末尾用 [1]、[2] 标注来源
6. 对于招生、录取等时效性问题，提醒用户核实最新信息
7. 不要在开头重复用户问题，也不要使用“根据提供的资料”之类空泛套话；直接给出结论或概览

【严禁事项 — 必须严格遵守】
- 绝对禁止编造参考资料中不存在的时间、日期、数字、电话号码、网址、地址、人名、金额等具体事实
- 绝对禁止将参考资料中只言片语拼接成看似合理的"答案"，如果资料不足就直接说不足
- 每一个 [N] 引用所指向的事实，必须在对应编号的参考资料中能找到原文支持
- 如果资料不足，礼貌说明"抱歉，当前知识库暂无足以可靠回答该问题的相关内容"，不要试图猜测答案"""

NO_CONTEXT_MESSAGE = (
    "抱歉，当前知识库暂无足以可靠回答该问题的相关内容。"
    "您可以尝试补充更具体的关键词或换一种问法；如仍无结果，可能需要管理员补充相关资料。"
)


# ═══════════════════════════════════════════════════════════════
# Main Engine
# ═══════════════════════════════════════════════════════════════
class HHURAGEngine:
    _instance: HHURAGEngine | None = None

    def __new__(cls) -> "HHURAGEngine":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_ready", False):
            return
        self._ready = True
        self._configure()
        self._lock = threading.RLock()
        self.persist_dir = settings.data_dir / "llama_index_storage"
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self._tombstone_path = self.persist_dir / "deleted_documents.json"
        self._deleted_document_keys = self._load_document_tombstones()
        self.index = self._load_or_build()
        self._bm25_index = None
        self._bm25_chunks: list[str] = []
        self._bm25_node_ids: list[str] = []
        self._load_bm25()
        self._load_parent_map()

    # ── Config ─────────────────────────────────────────────────
    def _configure(self) -> None:
        if settings.use_local_embedding:
            Settings.embed_model = LocalEmbedding()
        else:
            if not settings.dashscope_api_key:
                raise RuntimeError("DASHSCOPE_API_KEY required for cloud embedding")
            Settings.embed_model = OpenAIEmbedding(
                model="text-embedding-ada-002",
                model_name=settings.embedding_model,
                api_base=settings.llm_base_url,
                api_key=settings.dashscope_api_key,
                embed_batch_size=10,
            )

        if not settings.llm_api_key:
            raise RuntimeError("LLM_API_KEY required")
        Settings.llm = CompatibleLLM(
            model=settings.llm_model,
            api_base=settings.llm_base_url,
            api_key=settings.llm_api_key,
            temperature=0.1,
            max_tokens=1024,
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )
        Settings.node_parser = SentenceSplitter(
            chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap
        )
        Settings.context_window = 8192

    # ── Index ──────────────────────────────────────────────────
    def _embed_dim(self) -> int:
        if settings.use_local_embedding:
            return _get_local_embedding_model().get_embedding_dimension()
        return 1024

    @staticmethod
    def _faiss_temp_dir() -> Path:
        """Temp dir guaranteed to be ASCII-only (FAISS can't handle Unicode paths on Windows)."""
        # settings.data_dir works in production, but tests put it under a
        # pytest temp dir whose path may contain non-ASCII characters.
        # Fall back to the (ASCII) working directory before giving up.
        for candidate in (settings.data_dir / "tmp", Path.cwd() / ".faiss_tmp"):
            if all(ord(ch) < 128 for ch in str(candidate)):
                candidate.mkdir(parents=True, exist_ok=True)
                return candidate
        raise RuntimeError("FAISS requires an ASCII-only temp directory")

    @staticmethod
    def _faiss_write(faiss_index: faiss.Index, target: Path) -> None:
        """Write FAISS index via a tempfile to work around Unicode path issues on Windows."""
        tmp = HHURAGEngine._faiss_temp_dir() / "faiss_tmp.index"
        try:
            faiss.write_index(faiss_index, str(tmp))
            shutil.move(str(tmp), str(target))
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)

    @staticmethod
    def _faiss_read(source: Path) -> faiss.Index:
        """Read FAISS index via a tempfile to work around Unicode path issues on Windows."""
        tmp = HHURAGEngine._faiss_temp_dir() / "faiss_tmp.index"
        try:
            shutil.copy2(str(source), str(tmp))
            return faiss.read_index(str(tmp))
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)

    def _load_or_build(self) -> VectorStoreIndex:
        docstore_p = self.persist_dir / "docstore.json"
        faiss_p = self.persist_dir / "faiss.index"
        idx_p = self.persist_dir / "index_store.json"

        if docstore_p.exists():
            from llama_index.core.storage.docstore import SimpleDocumentStore
            from llama_index.core.storage.index_store import SimpleIndexStore
            try:
                docstore = SimpleDocumentStore.from_persist_path(str(docstore_p))
                if faiss_p.exists() and idx_p.exists():
                    idx_store = SimpleIndexStore.from_persist_path(str(idx_p))
                    fi = self._faiss_read(faiss_p)
                    vs = FaissVectorStore(faiss_index=fi)
                    sc = StorageContext.from_defaults(docstore=docstore, index_store=idx_store, vector_store=vs)
                    from llama_index.core import load_index_from_storage
                    index = load_index_from_storage(sc)
                    print(f"[OK] Index loaded: {len(index.docstore.docs)} nodes")
                    return index
                print("[WARN] Vector files missing, rebuilding from docstore")
                return self._rebuild_from_docstore(docstore)
            except Exception as e:
                print(f"[WARN] Index load failed: {e}")

        dim = self._embed_dim()
        fi = faiss.IndexFlatIP(dim)
        vs = FaissVectorStore(faiss_index=fi)
        index = VectorStoreIndex(nodes=[], storage_context=StorageContext.from_defaults(vector_store=vs), store_nodes_override=True)
        print(f"[OK] New empty index ({dim}d)")
        return index

    def _rebuild_from_docstore(self, docstore) -> VectorStoreIndex:
        from llama_index.core.storage.index_store import SimpleIndexStore
        nodes = list(docstore.docs.values())
        dim = self._embed_dim()
        fi = faiss.IndexFlatIP(dim)
        vs = FaissVectorStore(faiss_index=fi)
        sc = StorageContext.from_defaults(docstore=docstore, index_store=SimpleIndexStore(), vector_store=vs)
        return VectorStoreIndex(nodes=nodes, storage_context=sc, store_nodes_override=True)

    def _persist(self) -> None:
        with self._lock:
            self.persist_dir.mkdir(parents=True, exist_ok=True)
            self.index.docstore.persist(persist_path=str(self.persist_dir / "docstore.json"))
            self.index.storage_context.index_store.persist(persist_path=str(self.persist_dir / "index_store.json"))
            self._faiss_write(
                self.index.storage_context.vector_store._faiss_index,
                self.persist_dir / "faiss.index",
            )

    def save_index(self) -> None:
        self._persist()

    def rebuild_index(self) -> int:
        """Rebuild entire FAISS index from SQLite documents."""
        with self._lock:
            dim = self._embed_dim()
            fi = faiss.IndexFlatIP(dim)
            vs = FaissVectorStore(faiss_index=fi)
            sc = StorageContext.from_defaults(vector_store=vs)
            self.index = VectorStoreIndex(nodes=[], storage_context=sc, store_nodes_override=True)
            # Clear parent map on rebuild
            _set_parent_map({})
            with connect() as db:
                rows = db.execute("SELECT id, stored_name, title, category, source_url FROM documents WHERE status='READY'").fetchall()
                for row in rows:
                    path = settings.upload_dir / row["stored_name"]
                    if path.exists():
                        self.add_document(path, document_id=row["id"], title=row["title"],
                                          category=row["category"] or "", source_url=row["source_url"] or "")
            self._persist()
            self._build_bm25()
            self._save_parent_map()
            # Re-include the checked-in knowledge-base files after rebuilding
            # uploaded documents so the button truly performs a full rebuild.
            self.load_knowledge_base(settings.knowledge_base_dir)
            return len(self.index.docstore.docs)

    # ── BM25 Sparse Index ──────────────────────────────────────
    def _tokenize(self, text: str) -> list[str]:
        return [w for w in jieba.cut(text) if w.strip()]

    def _build_bm25(self) -> None:
        with self._lock:
            nodes = list(self.index.docstore.docs.values())
            self._bm25_chunks = [node.get_content(metadata_mode=MetadataMode.NONE) for node in nodes]
            self._bm25_node_ids = [node.node_id for node in nodes]
            tokenized = [self._tokenize(c) for c in self._bm25_chunks]
            self._bm25_index = BM25Okapi(tokenized) if tokenized else None
            bm25_path = self.persist_dir / "bm25_index.pkl"
            import pickle
            with open(bm25_path, "wb") as f:
                pickle.dump({"chunks": self._bm25_chunks, "node_ids": self._bm25_node_ids}, f)

    def _load_bm25(self) -> None:
        bm25_path = self.persist_dir / "bm25_index.pkl"
        if bm25_path.exists():
            import pickle
            try:
                with open(bm25_path, "rb") as f:
                    data = pickle.load(f)
                self._bm25_chunks = data["chunks"]
                self._bm25_node_ids = data["node_ids"]
                tokenized = [self._tokenize(c) for c in self._bm25_chunks]
                self._bm25_index = BM25Okapi(tokenized) if tokenized else None
                print(f"[OK] BM25 index loaded: {len(self._bm25_chunks)} docs")
            except Exception:
                self._bm25_index = None

    # ── Parent Map Persistence ──────────────────────────────────
    def _save_parent_map(self) -> None:
        parent_path = self.persist_dir / "parent_map.pkl"
        import pickle
        with open(parent_path, "wb") as f:
            pickle.dump(_get_parent_map(), f)

    def _load_parent_map(self) -> None:
        parent_path = self.persist_dir / "parent_map.pkl"
        if parent_path.exists():
            import pickle
            try:
                with open(parent_path, "rb") as f:
                    data = pickle.load(f)
                _set_parent_map(data)
                print(f"[OK] Parent map loaded: {len(data)} parents")
            except Exception:
                _set_parent_map({})

    # ── Parent-Child Chunking ───────────────────────────────────
    def _chunk_parent_child(self, text: str, metadata: dict) -> tuple[list[Any], dict[str, dict]]:
        """Split document into parent (large) and child (small) chunks.

        Returns (child_nodes, parent_entries) where:
        - child_nodes are indexed in FAISS for retrieval
        - parent_entries map parent_id → full parent context for Small-to-Big
        """
        parent_size = settings.parent_chunk_size
        child_size = settings.child_chunk_size
        doc_id = str(metadata.get("document_id", "unknown"))

        # Create parent chunks (large, contextual)
        parent_parser = SentenceSplitter(chunk_size=parent_size, chunk_overlap=200)
        parent_doc = Document(text=text)
        parent_nodes = parent_parser.get_nodes_from_documents([parent_doc])

        # Create child chunks (small, precise) from each parent
        child_parser = SentenceSplitter(chunk_size=child_size, chunk_overlap=50)

        all_children: list[Any] = []
        parent_entries: dict[str, dict] = {}

        for pi, parent in enumerate(parent_nodes):
            parent_id = f"{doc_id}#p{pi}"
            parent_text = parent.get_content(metadata_mode=MetadataMode.NONE).strip()
            if len(parent_text) < 50:
                continue

            parent_entries[parent_id] = {
                "text": parent_text,
                "title": metadata.get("title", ""),
                "source_url": metadata.get("source_url", ""),
                "category": metadata.get("category", ""),
            }

            # Split this parent into children
            child_doc = Document(text=parent_text)
            children = child_parser.get_nodes_from_documents([child_doc])
            for child in children:
                child_text = child.get_content(metadata_mode=MetadataMode.NONE).strip()
                if len(child_text) < 20:
                    continue
                child.metadata = {
                    **metadata,
                    "parent_id": parent_id,
                    "chunk_role": "child",
                    "chunk_size": len(child_text),
                }
                all_children.append(child)

        return all_children, parent_entries

    # ── Small-to-Big Retrieval (§13.1 + §13.2) ──────────────────
    def _small_to_big_retrieve(self, query: str, top_k: int = 5) -> list[Any]:
        """Retrieve using small (child) chunks, return large (parent) context.

        Course §13.1 Small-to-Big: use precise child chunks for vector search,
        then expand to parent chunks for richer LLM context.
        """
        parent_map = _get_parent_map()
        if not parent_map:
            # No parent data — fall back to hybrid retrieval
            return self._hybrid_retrieve(query, top_k=20)

        # 1) Retrieve with child chunks (dense + BM25 hybrid)
        child_nodes = self._hybrid_retrieve(query, top_k=30)

        # 2) Map children to parents (Small-to-Big expansion)
        seen_parents: set[str] = set()
        expanded_nodes: list[Any] = []
        for child in child_nodes:
            meta = getattr(child, "metadata", {}) or {}
            parent_id = meta.get("parent_id", "")
            if not parent_id or parent_id in seen_parents:
                continue
            seen_parents.add(parent_id)
            parent_entry = parent_map.get(parent_id)
            if not parent_entry:
                continue
            # Create a new node from parent text, inheriting child's score
            from llama_index.core.schema import TextNode
            parent_node = TextNode(
                text=parent_entry["text"],
                metadata={
                    "title": parent_entry["title"],
                    "source_url": parent_entry.get("source_url", ""),
                    "category": parent_entry.get("category", ""),
                    "parent_id": parent_id,
                    "chunk_role": "parent",
                },
            )
            expanded_nodes.append(NodeWithScore(
                node=parent_node,
                score=float(getattr(child, "score", 0) or 0),
            ))
            if len(expanded_nodes) >= top_k * 4:
                break

        # 3) Rerank expanded parent nodes
        if len(expanded_nodes) > top_k:
            expanded_nodes = self._rerank(query, expanded_nodes, top_k)
        return expanded_nodes[:top_k * 2]

    # ── Semantic Chunking document processor ────────────────────
    def _create_semantic_chunks(self, text: str, metadata: dict) -> list[Any]:
        """Use SemanticChunker to split text, return llama_index nodes."""
        chunker = SemanticChunker(
            embed_model=Settings.embed_model,
            threshold=settings.semantic_threshold,
            min_chunk_size=100,
            max_chunk_size=settings.chunk_size,
        )
        chunks = chunker.split(text)
        nodes = []
        for i, chunk in enumerate(chunks):
            node = Document(
                text=chunk,
                metadata={
                    **metadata,
                    "chunk_idx": i,
                    "chunk_method": "semantic",
                },
            )
            nodes.append(node)
        return nodes

    def _bm25_search(self, query: str, top_k: int = 20) -> list[tuple[str, float]]:
        if not self._bm25_index:
            return []
        tokens = self._tokenize(query)
        scores = self._bm25_index.get_scores(tokens)
        ranked = sorted(enumerate(scores), key=lambda x: -x[1])[:top_k]
        max_s = ranked[0][1] if ranked else 1.0
        return [(self._bm25_node_ids[i], s / max_s) for i, s in ranked if s > 0]

    # ── Hybrid Retrieval (RRF) ─────────────────────────────────
    def _hybrid_retrieve(self, query: str, top_k: int = 20) -> list[Any]:
        """Fuse FAISS semantic similarity and BM25 lexical relevance.

        Short campus queries often contain one decisive term (for example
        ``校训``).  Weighted RRF previously gave every dense candidate three
        times the weight of an exact BM25 hit, so semantically nearby words
        such as ``军训`` could occupy the complete candidate window.  Score
        fusion keeps the union of both retrievers and explicitly rewards
        lexical coverage before truncating the result set.
        """
        dense = self._dense_retrieve(query, top_k)
        sparse = self._bm25_search(query, top_k)

        if not sparse:
            return dense

        # Pre-filter BM25: drop low-score keyword matches that add noise
        sparse = [(nid, s) for nid, s in sparse if s >= 0.4]

        if not sparse:
            return dense

        node_map: dict[str, Any] = {}
        dense_scores: dict[str, float] = {}
        sparse_scores = dict(sparse)

        for node in dense:
            node_map[node.node_id] = node
            dense_scores[node.node_id] = max(
                0.0, min(1.0, float(getattr(node, "score", 0) or 0)),
            )
        for nid, _ in sparse:
            if nid not in node_map:
                node_map[nid] = NodeWithScore(node=self.index.docstore.get_node(nid), score=0.0)

        query_terms = self._query_terms(query)
        scores: dict[str, float] = {}
        for nid, wrapped in node_map.items():
            dense_score = dense_scores.get(nid, 0.0)
            sparse_score = max(0.0, min(1.0, sparse_scores.get(nid, 0.0)))
            metadata = getattr(wrapped, "metadata", {}) or {}
            haystack = f"{metadata.get('title', '')} {self._node_text(wrapped)}".lower()
            lexical_coverage = (
                sum(max(1, len(term)) for term in query_terms if term in haystack)
                / max(1, sum(max(1, len(term)) for term in query_terms))
            ) if query_terms else 0.0

            if sparse_score > 0 and dense_score > 0:
                fused = 0.55 * dense_score + 0.30 * sparse_score + 0.15 * lexical_coverage
            elif sparse_score > 0:
                fused = 0.70 * sparse_score + 0.20 * lexical_coverage
            else:
                fused = 0.75 * dense_score
            scores[nid] = min(1.0, fused)

        merged = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        results: list[Any] = []
        for nid, retrieval_score in merged[:top_k]:
            if nid not in node_map:
                continue
            results.append(NodeWithScore(node=node_map[nid].node, score=retrieval_score))
        return results

    def _dense_retrieve(self, query: str, top_k: int = 20) -> list[Any]:
        retriever = self.index.as_retriever(similarity_top_k=top_k)
        return retriever.retrieve(query)

    # ── Reranker (CrossEncoder) ────────────────────────────────
    _reranker_model = None

    def _get_reranker(self):
        if self._reranker_model is None:
            from sentence_transformers import CrossEncoder
            try:
                self._reranker_model = CrossEncoder(
                    "BAAI/bge-reranker-base",
                    device="cpu",
                    local_files_only=not settings.allow_model_download,
                )
                print("[OK] Reranker model loaded")
            except Exception as exc:
                print(f"[WARN] Reranker unavailable, using retrieval order: {exc}")
                self._reranker_model = False
        return self._reranker_model or None

    def _rerank(self, query: str, nodes: list[Any], top_k: int = 5) -> list[Any]:
        """CrossEncoder rerank: score (query, chunk) pairs, return top_k."""
        if len(nodes) <= top_k:
            return nodes
        if not settings.enable_reranker:
            return nodes
        model = self._get_reranker()
        if model is None:
            return nodes
        pairs = [(query, n.get_content(metadata_mode=MetadataMode.NONE)) for n in nodes]
        scores = model.predict(pairs)
        ranked = sorted(zip(nodes, scores), key=lambda x: -x[1])
        return [n for n, _ in ranked[:top_k]]

    # ── HyDE (Hypothetical Document Embeddings) ────────────────
    def _hyde_retrieve(self, query: str, top_k: int = 5) -> list[Any]:
        """LLM generates a hypothetical answer → embed → retrieve → return original query results."""
        hyde_prompt = (
            "请根据以下问题，写一段假设性的回答段落（100-200字），"
            "用于检索相关文档。不要直接回答问题，而是生成一段可能出现在相关文档中的文字。\n\n"
            f"问题：{query}\n\n假设性段落："
        )
        try:
            hypo = str(Settings.llm.complete(hyde_prompt)).strip()
            if len(hypo) < 10:
                return self._dense_retrieve(query, top_k)
            return self._dense_retrieve(hypo, top_k)
        except Exception:
            return self._dense_retrieve(query, top_k)

    # ── Multi-Query ────────────────────────────────────────────
    def _multi_query_retrieve(self, query: str, top_k: int = 5) -> list[Any]:
        """Generate 3 query variants → retrieve each → RRF fuse results."""
        mq_prompt = (
            "将以下问题改写为3个不同角度的搜索查询，每个查询一行，不要编号，不要前缀。\n"
            f"原问题：{query}\n\n改写查询："
        )
        try:
            response = str(Settings.llm.complete(mq_prompt)).strip()
            variants = [q.strip() for q in response.split("\n") if q.strip()][:3]
            if len(variants) < 2:
                return self._hybrid_retrieve(query, top_k=20)[:top_k]
        except Exception:
            return self._hybrid_retrieve(query, top_k=20)[:top_k]

        all_nodes = []
        k = 60
        scores: dict[str, float] = {}
        node_map: dict[str, Any] = {}
        for v in variants:
            for rank, node in enumerate(self._dense_retrieve(v, top_k=10)):
                scores[node.node_id] = scores.get(node.node_id, 0) + 1.0 / (k + rank)
                node_map[node.node_id] = node

        merged = sorted(scores.items(), key=lambda x: -x[1])
        return [node_map[nid] for nid, _ in merged[:top_k] if nid in node_map]

    # ── Query Decomposition ──────────────────────────────────────
    def _decompose_retrieve(self, query: str, top_k: int = 5) -> list[Any]:
        """Split complex questions into sub-questions → retrieve each → merge."""
        decomp_prompt = (
            "判断以下问题是否为复合问题（包含多个子问题）。如果是，将其拆分为独立的子问题，"
            "每行一个，不要编号。如果不是复合问题，直接返回原问题。\n\n"
            f"问题：{query}\n\n输出："
        )
        try:
            response = str(Settings.llm.complete(decomp_prompt)).strip()
            sub_questions = [q.strip() for q in response.split("\n") if q.strip()]
            # If only one sub-question or same as original, fall back to multi-query
            if len(sub_questions) <= 1:
                return self._multi_query_retrieve(query, top_k)
            # Limit to 4 sub-questions
            sub_questions = sub_questions[:4]
        except Exception:
            return self._multi_query_retrieve(query, top_k)

        # Retrieve for each sub-question and merge with RRF
        all_nodes: list[Any] = []
        k = 60
        scores: dict[str, float] = {}
        node_map: dict[str, Any] = {}
        for sub_q in sub_questions:
            for rank, node in enumerate(self._hybrid_retrieve(sub_q, top_k=10)):
                scores[node.node_id] = scores.get(node.node_id, 0) + 1.0 / (k + rank)
                node_map[node.node_id] = node

        merged = sorted(scores.items(), key=lambda x: -x[1])
        return [node_map[nid] for nid, _ in merged[:top_k] if nid in node_map]

    # ── Multi-turn Query Rewriting ───────────────────────────────
    _FOLLOWUP_MARKERS = (
        "它", "这个", "那个", "这些", "那些", "上述", "前面", "其中", "该",
        "进去", "那里", "那边", "然后", "另外", "还有", "那么",
    )
    _FOLLOWUP_GENERIC_TERMS = {
        "周末", "开放", "时间", "地点", "位置", "证件", "费用", "多久",
        "进去", "那里", "什么时候", "是否", "可以", "怎么", "如何",
    }

    def _needs_history_rewrite(self, query: str) -> bool:
        """Only rewrite elliptical follow-ups, never a complete topic question."""
        cleaned = re.sub(r"\s+", "", query).strip("，,。！？!?；;")
        if not cleaned:
            return False
        if cleaned.startswith(self._FOLLOWUP_MARKERS):
            return True
        terms = self._query_terms(cleaned)
        return bool(
            len(cleaned) <= 18
            and terms
            and terms.issubset(self._FOLLOWUP_GENERIC_TERMS)
        )

    def _rewrite_query_with_history(self, query: str, history: list[ChatMessage]) -> str:
        """Resolve anaphora and complete context from conversation history."""
        if not settings.enable_query_rewrite or not history or not self._needs_history_rewrite(query):
            return query
        hist_str = "\n".join(
            f"{'用户' if m.role == MessageRole.USER else '助手'}: {m.content}"
            for m in history[-6:]
        )
        rewrite_prompt = (
            "根据对话历史，将用户的追问改写为完整的独立问题（补充指代和省略的信息）。"
            "如果问题已经是完整的，直接返回原问题。\n\n"
            f"对话历史：\n{hist_str}\n\n"
            f"用户追问：{query}\n\n"
            "完整问题："
        )
        try:
            rewritten = str(Settings.llm.complete(rewrite_prompt)).strip()
            if len(rewritten) > 3 and rewritten != query:
                print(f"[OK] Query rewritten: '{query}' → '{rewritten}'")
                return rewritten
        except Exception:
            pass
        return query

    # ── Metadata Pre-filtering ───────────────────────────────────
    def _filter_by_metadata(self, nodes: list[Any], category: str | None = None) -> list[Any]:
        """Filter retrieved nodes by metadata (category, etc.) before ranking."""
        if not category:
            return nodes
        filtered = []
        for node in nodes:
            metadata = getattr(node, "metadata", {}) or {}
            node_category = str(metadata.get("category", "")).strip()
            if node_category.lower() == category.lower():
                filtered.append(node)
        return filtered if filtered else nodes  # Fall back to all if filter is too strict

    # ── Context Compression ──────────────────────────────────────
    def _compress_context(self, query: str, nodes: list[Any]) -> list[Any]:
        """Post-retrieval: extract most relevant sentences from each chunk."""
        if not settings.enable_context_compression or len(nodes) <= 2:
            return nodes
        compressed = []
        for node in nodes:
            text = self._node_text(node)
            # For short chunks, keep as-is
            if len(text) < 200:
                compressed.append(node)
                continue
            # Split into sentences and score by query term overlap
            query_terms = self._query_terms(query)
            sentences = re.split(r"(?<=[。！？!?；;])\s*|\n+", text)
            scored = []
            for sent in sentences:
                sent = sent.strip()
                if len(sent) < 6:
                    continue
                sent_terms = {w for w in self._tokenize(sent) if len(w.strip()) >= 2}
                overlap = len(query_terms & sent_terms)
                scored.append((overlap, sent))
            # Keep top 3 sentences or sentences with overlap
            if scored:
                kept = [s for ov, s in sorted(scored, key=lambda x: -x[0])[:3] if ov > 0 or len(scored) <= 3]
                if kept:
                    new_text = "。".join(kept) + "。"
                    # Never mutate the docstore node: repeated queries must not
                    # progressively destroy the indexed source text.
                    inner = node.node if hasattr(node, "node") else node
                    cloned = copy.deepcopy(inner)
                    if hasattr(cloned, "set_content"):
                        cloned.set_content(new_text)
                    compressed.append(NodeWithScore(
                        node=cloned,
                        score=float(getattr(node, "score", 0) or 0),
                    ))
                    continue
            compressed.append(node)
        return compressed

    # ── Self-RAG Relevance Check ─────────────────────────────────
    def _self_rag_check(self, query: str, nodes: list[Any]) -> tuple[bool, str]:
        """Self-RAG: model evaluates whether retrieved results are actually relevant."""
        if not settings.enable_self_rag or not nodes:
            return True, ""
        # Quick pre-check: our relevance gate
        if not self._has_relevant_context(query, nodes):
            return False, "检索结果与问题无关，尝试重新检索"

        # Build a summary for the LLM to evaluate
        snippets = []
        for i, node in enumerate(nodes[:3], 1):
            text = self._node_text(node)[:300]
            snippets.append(f"[{i}] {text}")
        check_prompt = (
            "判断以下检索结果是否能够回答用户问题。\n"
            "回复格式：先回复[相关]或[不相关]，然后简要说明原因。\n\n"
            f"用户问题：{query}\n\n"
            f"检索结果：\n" + "\n".join(snippets) + "\n\n"
            "判断："
        )
        try:
            verdict = str(Settings.llm.complete(check_prompt)).strip()
            is_relevant = "相关" in verdict and "不相关" not in verdict[:20]
            return is_relevant, verdict
        except Exception:
            return True, ""

    # ── CRAG Corrective Retrieval ────────────────────────────────
    def _crag_corrective_retrieve(self, query: str, top_k: int = 5) -> list[Any]:
        """CRAG: when initial retrieval quality is low, rewrite and re-retrieve."""
        # First attempt with hybrid
        nodes = self._hybrid_retrieve(query, top_k=20)
        is_relevant, verdict = self._self_rag_check(query, nodes[:5])

        if is_relevant:
            return nodes

        # Quality low — rewrite query and try again
        print(f"[CRAG] Low relevance: {verdict[:80]}... Rewriting query...")
        rewrite_prompt = (
            "以下检索查询的结果质量不佳。请用不同的表达方式改写这个查询，"
            "使其更容易检索到相关知识：\n\n"
            f"原查询：{query}\n\n改写查询："
        )
        try:
            rewritten = str(Settings.llm.complete(rewrite_prompt)).strip()
            if len(rewritten) > 5:
                nodes2 = self._hybrid_retrieve(rewritten, top_k=20)
                is_relevant2, verdict2 = self._self_rag_check(rewritten, nodes2[:5])
                if is_relevant2:
                    print(f"[CRAG] Rewritten query successful: '{rewritten}'")
                    return nodes2
                # Both attempts failed — return empty so relevance gate triggers
                print(f"[CRAG] Both attempts failed: '{verdict2[:80]}...'")
                return []
        except Exception:
            pass
        return nodes

    def _rrf_merge(self, node_lists: list[list[Any]], top_k: int = 20) -> list[Any]:
        """Merge multiple ranked node lists with RRF."""
        k = 60
        scores: dict[str, float] = {}
        node_map: dict[str, Any] = {}
        for node_list in node_lists:
            for rank, node in enumerate(node_list):
                nid = getattr(node, "node_id", None)
                if nid is None:
                    nid = getattr(node.node, "node_id", None) if hasattr(node, "node") else None
                if nid is None:
                    continue
                scores[nid] = scores.get(nid, 0) + 1.0 / (k + rank)
                node_map[nid] = node
        merged = sorted(scores.items(), key=lambda x: -x[1])
        return [node_map[nid] for nid, _ in merged[:top_k] if nid in node_map]

    def _retrieve(self, query: str, strategy: str = "hybrid", top_k: int = 5,
                  category: str | None = None, enable_crag: bool = False) -> list[Any]:
        """Strategy dispatcher with advanced options: decomposition, CRAG, metadata filter, threshold."""
        print(f"  🎯 检索策略: {strategy}")
        nodes: list[Any] = []
        if strategy == "hybrid":
            print(f"  ├─ FAISS 向量检索 (dense) + BM25 关键词检索 (sparse)")
            print(f"  ├─ RRF 融合: k=60, dense权重=3.0, bm25权重=1.0")
            nodes = self._hybrid_retrieve(query, top_k=20)
            print(f"  ├─ 粗召回: {len(nodes)} 条")
            if len(nodes) > top_k and settings.enable_reranker:
                print(f"  ├─ CrossEncoder 重排序: {len(nodes)} → {top_k} 条")
                nodes = self._rerank(query, nodes, top_k)
            if settings.enable_context_compression and len(nodes) > 2:
                total_before = sum(len(self._node_text(n)) for n in nodes)
                nodes = self._compress_context(query, nodes)
                total_after = sum(len(self._node_text(n)) for n in nodes)
                print(f"  ├─ 上下文压缩: {total_before}字 → {total_after}字")
            else:
                nodes = self._compress_context(query, nodes) if len(nodes) <= 2 else nodes
        elif strategy == "dense":
            print(f"  ├─ FAISS IndexFlatIP 内积搜索")
            nodes = self._dense_retrieve(query, top_k * 2)
            print(f"  ├─ 粗召回: {len(nodes)} 条")
            if len(nodes) > top_k and settings.enable_reranker:
                print(f"  ├─ CrossEncoder 重排序: {len(nodes)} → {top_k} 条")
                nodes = self._rerank(query, nodes, top_k)
            nodes = self._compress_context(query, nodes)
        elif strategy == "bm25":
            print(f"  ├─ jieba 分词 → BM25Okapi")
            results = self._bm25_search(query, top_k)
            nodes = [NodeWithScore(node=self.index.docstore.get_node(nid), score=score)
                     for nid, score in results if nid]
            print(f"  ├─ 命中: {len(nodes)} 条")
        elif strategy == "hyde":
            print(f"  ├─ HyDE: LLM 生成假设答案 → 向量检索")
            nodes = self._hyde_retrieve(query, top_k=10)
            print(f"  ├─ 检索结果: {len(nodes)} 条")
        elif strategy == "multi":
            print(f"  ├─ Multi-Query: LLM 生成 3 路查询 → 各自检索 → RRF 融合")
            nodes = self._multi_query_retrieve(query, top_k)
            print(f"  ├─ 融合结果: {len(nodes)} 条")
        elif strategy == "decompose":
            print(f"  ├─ Decompose: LLM 拆解为子问题 → 逐个检索 → 合并去重")
            nodes = self._decompose_retrieve(query, top_k)
            print(f"  ├─ 合并结果: {len(nodes)} 条")
        elif strategy == "parent_child":
            print(f"  ├─ Small-to-Big: 子块(300字)检索 → 父块(1000字)返回")
            nodes = self._small_to_big_retrieve(query, top_k)
            print(f"  ├─ 结果: {len(nodes)} 条")
        elif strategy == "full":
            print(f"  ├─ CRAG: Self-RAG自检 → 低质量则改写重检")
            nodes = self._crag_corrective_retrieve(query, top_k) if enable_crag else self._hyde_retrieve(query, top_k=15)
            nodes = self._rerank(query, nodes, top_k)
        else:
            nodes = self._hybrid_retrieve(query, top_k=20)

        # CRAG corrective retrieval for hybrid/dense when enabled
        if enable_crag and strategy in ("hybrid", "dense", "hyde", "multi", "decompose"):
            is_relevant, _ = self._self_rag_check(query, nodes[:5])
            if not is_relevant:
                nodes = self._crag_corrective_retrieve(query, top_k)

        # Metadata pre-filtering
        if category:
            nodes = self._filter_by_metadata(nodes, category)

        # Apply rerank for strategies that haven't already been reranked
        if strategy not in ("bm25", "dense", "hybrid") and len(nodes) > top_k:
            nodes = self._rerank(query, nodes, top_k)

        # Context compression (post-rerank) — skip if already compressed above
        if strategy not in ("dense", "hybrid"):
            nodes = self._compress_context(query, nodes)

        deduped = self._dedupe_nodes(nodes)
        deduped = [node for node in deduped if not self._is_document_tombstoned(node)]
        return self._evidence_rerank(query, deduped, top_k)

    @staticmethod
    def _node_text(node: Any) -> str:
        return node.get_content(metadata_mode=MetadataMode.NONE).strip()

    _QUERY_STOP_TERMS = {
        "河海大学", "河海", "大学", "学校", "校园", "什么", "怎么", "如何",
        "哪些", "是否", "问题", "相关", "有关", "请问", "一下", "了解",
        "介绍", "信息", "内容", "情况", "为什么", "哪里", "怎样",
        "关于", "帮我", "帮忙", "帮助", "整理", "总结", "归纳", "概括",
        "说明", "告诉", "查询", "查找", "搜索", "麻烦", "能否", "可以",
        "想要", "想知道", "资料", "方面", "进行", "给我", "说说",
        "申请", "办理", "流程", "步骤", "条件", "材料", "需要", "要求",
        "参加", "参与", "具体", "整理成", "处理", "满足", "准备",
    }

    # Keep a canonical UTF-8-independent vocabulary as well.  A historical
    # Windows encoding conversion left some persisted source literals as
    # mojibake, which made common intent words such as “怎么样” leak into
    # relevance scoring and caused unrelated questions to pass the gate.
    _QUERY_STOP_TERMS = _QUERY_STOP_TERMS | {
        "\u6cb3\u6d77\u5927\u5b66", "\u6cb3\u6d77", "\u5927\u5b66", "\u5b66\u6821", "\u6821\u56ed",
        "\u4ec0\u4e48", "\u600e\u4e48", "\u600e\u4e48\u6837", "\u5982\u4f55", "\u54ea\u4e9b", "\u662f\u5426", "\u95ee\u9898",
        "\u76f8\u5173", "\u6709\u5173", "\u8bf7\u95ee", "\u4e00\u4e0b", "\u4e86\u89e3", "\u4ecb\u7ecd",
        "\u4fe1\u606f", "\u5185\u5bb9", "\u60c5\u51b5", "\u4e3a\u4ec0\u4e48", "\u54ea\u91cc", "\u600e\u6837",
        "\u5173\u4e8e", "\u5e2e\u6211", "\u5e2e\u5fd9", "\u5e2e\u52a9", "\u6574\u7406", "\u603b\u7ed3",
        "\u5f52\u7eb3", "\u6982\u62ec", "\u8bf4\u660e", "\u544a\u8bc9", "\u67e5\u8be2", "\u67e5\u627e",
        "\u641c\u7d22", "\u9ebb\u70e6", "\u80fd\u5426", "\u53ef\u4ee5", "\u60f3\u8981", "\u60f3\u77e5\u9053",
        "\u8d44\u6599", "\u65b9\u9762", "\u8fdb\u884c", "\u7ed9\u6211", "\u8bf4\u8bf4", "\u7533\u8bf7",
        "\u529e\u7406", "\u6d41\u7a0b", "\u6b65\u9aa4", "\u6761\u4ef6", "\u6750\u6599", "\u9700\u8981",
        "\u8981\u6c42", "\u53c2\u52a0", "\u53c2\u4e0e", "\u5177\u4f53", "\u6574\u7406\u6210", "\u5904\u7406",
        "\u6ee1\u8db3", "\u51c6\u5907",
    }

    def _query_terms(self, query: str) -> set[str]:
        return {
            term.strip().lower()
            for term in self._tokenize(query)
            if len(term.strip()) >= 2 and term.strip().lower() not in self._QUERY_STOP_TERMS
        }

    def _normalize_retrieval_query(self, query: str) -> str:
        """Keep the user's topic while removing conversational task wording.

        The original question is still sent to the LLM. This normalized form is
        only used for retrieval, so phrases such as “帮我整理一下” cannot dilute
        a clear topic such as “足球”.
        """
        terms: list[str] = []
        seen: set[str] = set()
        for raw_term in self._tokenize(query):
            term = raw_term.strip().lower()
            if len(term) < 2 or term in self._QUERY_STOP_TERMS or term in seen:
                continue
            seen.add(term)
            terms.append(term)
        return " ".join(terms) if terms else query.strip()

    def _retrieval_queries(self, question: str) -> list[str]:
        """Create deterministic topic subqueries without another paid LLM call."""
        candidates = [self._normalize_retrieval_query(question)]
        clauses = re.split(
            r"[，,。；;！？!?\n]+|(?:同时|另外|此外|以及|并且|还想知道|再问)",
            question,
        )
        candidates.extend(self._normalize_retrieval_query(part) for part in clauses)

        result: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            normalized = re.sub(r"\s+", " ", candidate).strip()
            if not self._query_terms(normalized) or normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)
        return result[:4] or [question.strip()]

    def _retrieve_question(self, question: str, strategy: str, top_k: int,
                           enable_crag: bool = False) -> tuple[list[Any], str]:
        """Retrieve one or more topic clauses and fuse complex-query results."""
        queries = self._retrieval_queries(question)
        retrieval_question = " ".join(queries)
        if len(queries) == 1:
            return self._retrieve(
                queries[0], strategy, top_k=top_k, enable_crag=enable_crag,
            ), retrieval_question

        per_query = max(top_k, 12)
        node_lists = [
            self._retrieve(q, strategy, top_k=per_query, enable_crag=enable_crag)
            for q in queries
        ]
        merged = self._dedupe_nodes(self._rrf_merge(node_lists, top_k=top_k * 2))
        return self._evidence_rerank(retrieval_question, merged, top_k), retrieval_question

    def _evidence_rerank(self, query: str, nodes: list[Any], top_k: int) -> list[Any]:
        """Filter generic matches and calibrate evidence confidence.

        RRF is a ranking score, not a probability. The old max normalization
        made every first result display as 100%, including weak matches.
        """
        terms = self._query_terms(query)
        if not nodes or not terms:
            return nodes[:top_k]

        ranked: list[tuple[bool, float, Any]] = []
        total_weight = sum(max(1, len(term)) for term in terms)
        for node in nodes:
            metadata = getattr(node, "metadata", {}) or {}
            title = str(metadata.get("title", "")).lower()
            content = self._node_text(node).lower()
            haystack = f"{title} {content}"
            matched = {term for term in terms if term in haystack}
            title_matched = {term for term in terms if term in title}
            lexical = sum(max(1, len(term)) for term in matched) / total_weight
            title_coverage = sum(max(1, len(term)) for term in title_matched) / total_weight
            semantic = max(0.0, min(1.0, float(getattr(node, "score", 0) or 0)))
            occurrences = sum(min(3, haystack.count(term)) for term in matched)
            focus = min(1.0, occurrences / max(2, len(terms) * 2))
            relevance = min(
                0.95,
                0.42 * semantic + 0.28 * lexical + 0.18 * title_coverage + 0.12 * focus,
            )
            ranked.append((bool(matched), relevance, node))

        anchored = [item for item in ranked if item[0]]
        candidates = anchored if anchored else ranked
        candidates.sort(key=lambda item: item[1], reverse=True)
        return [
            NodeWithScore(node=(node.node if hasattr(node, "node") else node), score=relevance)
            for _, relevance, node in candidates[:top_k]
        ]

    def _dedupe_nodes(self, nodes: list[Any]) -> list[Any]:
        """Remove duplicate chunks and repeated documents while preserving rank."""
        seen_chunks: set[str] = set()
        result: list[Any] = []
        for node in nodes:
            metadata = getattr(node, "metadata", {}) or {}
            text = re.sub(r"\s+", " ", self._node_text(node)).strip()
            title = str(metadata.get("title", "")).strip().lower()
            chunk_key = hashlib.sha1(text[:1200].encode("utf-8")).hexdigest()
            if not text or chunk_key in seen_chunks:
                continue
            seen_chunks.add(chunk_key)
            # A document is allowed to contribute several context chunks, but
            # exact duplicate content from another KB path is only shown once.
            result.append(node)
        return result

    def _has_relevant_context(self, question: str, nodes: list[Any]) -> bool:
        """Strict relevance gate — refuses to answer when context is insufficient.

        Prefer lexical evidence in one node over raw retrieval scores because
        RRF and cross-encoder reranking use different score scales.
        """
        query_terms = self._query_terms(question)
        if not query_terms:
            return False
        for node in nodes:
            metadata = getattr(node, "metadata", {}) or {}
            haystack = self._node_text(node) + " " + str(metadata.get("title", ""))
            matched = {term for term in query_terms if term in haystack.lower()}
            matched_weight = sum(max(1, len(term)) for term in matched)
            total_weight = sum(max(1, len(term)) for term in query_terms)
            coverage = matched_weight / max(1, total_weight)
            # An exact topic anchor is sufficient. Generic intent/task words
            # have already been removed by _query_terms.
            if matched and (len(matched) >= 2 or coverage >= 0.28 or len(query_terms) == 1):
                return True
            # A high dense score still requires at least one lexical anchor.
            score = float(getattr(node, "score", 0) or 0)
            if score >= 0.82 and matched:
                return True
        return False

    # ── Document management ────────────────────────────────────
    def add_document(
        self,
        file_path: Path,
        document_id: int,
        title: str = "",
        category: str = "其他",
        source_url: str = "",
        text_override: str | None = None,
        db: sqlite3.Connection | None = None,
        progress_callback: Any | None = None,
    ) -> int:
        file_path = Path(file_path)
        suffix = file_path.suffix.lower()

        if progress_callback:
            progress_callback("EXTRACTING")

        if text_override is not None:
            doc = Document(
                text=text_override,
                metadata={
                    "document_id": str(document_id), "title": title,
                    "category": category, "source_url": source_url,
                    "stored_name": file_path.name,
                },
            )
        elif suffix == ".md":
            from .hhu_reader import HHUMarkdownReader
            docs = HHUMarkdownReader().load_data(file_path)
            doc = docs[0] if docs else Document(text=file_path.read_text(encoding="utf-8", errors="ignore"))
            doc.metadata["document_id"] = str(document_id)
            doc.metadata["title"] = title or file_path.stem
            doc.metadata["category"] = category
            doc.metadata["source_url"] = source_url
        else:
            from .utils import extract_text
            data = file_path.read_bytes()
            text = extract_text(data, file_path.name)
            doc = Document(text=text, metadata={"document_id": str(document_id), "title": title, "category": category, "source_url": source_url, "stored_name": file_path.name})

        if not doc.text.strip():
            raise ValueError("文档未提取到有效文本")

        self.delete_document(document_id, persist=False, stored_name=file_path.name)
        metadata = dict(doc.metadata)

        if progress_callback:
            progress_callback("CHUNKING")

        with self._lock:
            if progress_callback:
                progress_callback("EMBEDDING")
            if settings.parent_child_enabled:
                # Parent-Child mode: index children, store parents for Small-to-Big
                children, parents = self._chunk_parent_child(doc.text, metadata)
                for child in children:
                    self.index.insert(child)
                _update_parent_map(parents)
                self._save_parent_map()
                print(f"[OK] Parent-Child: {len(parents)} parents, {len(children)} children indexed")
            elif settings.semantic_chunking_enabled:
                # Semantic chunking mode
                nodes = self._create_semantic_chunks(doc.text, metadata)
                for node in nodes:
                    self.index.insert(node)
                print(f"[OK] Semantic chunking: {len(nodes)} chunks created")
            else:
                # Standard mode
                self.index.insert(doc)

            # Persist a stable chunk index on every node so FAISS results can
            # always be traced back to document + chunk, as required by Day 4.
            document_nodes = [
                node for node in self.index.docstore.docs.values()
                if node.metadata.get("document_id") == str(document_id)
            ]
            document_nodes.sort(key=lambda node: (
                int(getattr(node, "start_char_idx", 0) or 0), node.node_id
            ))
            for chunk_index, node in enumerate(document_nodes):
                node.metadata["chunk_index"] = chunk_index
                node.metadata["file_name"] = file_path.name

        self._persist()
        self._build_bm25()

        node_count = sum(1 for n in self.index.docstore.docs.values() if n.metadata.get("document_id") == str(document_id))
        if db:
            db.execute("UPDATE documents SET chunk_count=?, status='READY', error=NULL, updated_at=? WHERE id=?", (node_count, utc_now(), document_id))
        return node_count

    def get_document_chunks(
        self,
        document_id: int,
        stored_name: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return persisted chunk metadata in deterministic source order."""
        target = str(document_id)
        identity = (stored_name or "").removeprefix("kb:")
        with self._lock:
            nodes = [
                node for node in self.index.docstore.docs.values()
                if node.metadata.get("document_id") == target
                or (
                    identity
                    and identity in {
                        str(node.metadata.get("stored_name", "")).removeprefix("kb:"),
                        str(node.metadata.get("file_name", "")),
                    }
                )
            ]
            nodes.sort(key=lambda node: (
                int(node.metadata.get("chunk_index", 0) or 0), node.node_id
            ))
            return [
                {
                    "chunk_index": int(node.metadata.get("chunk_index", index) or index),
                    "content": self._node_text(node),
                    "page_number": node.metadata.get("page_number"),
                }
                for index, node in enumerate(nodes)
            ]

    def search_chunks(self, question: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Day 4 vector-search acceptance API with traceable chunk metadata."""
        with self._lock:
            nodes = self._retrieve(
                question,
                strategy=settings.retrieval_strategy,
                top_k=max(1, min(20, top_k)),
            )
        return [
            {
                "docId": node.metadata.get("document_id"),
                "chunkIdx": int(node.metadata.get("chunk_index", index) or index),
                "content": self._node_text(node),
                "score": float(getattr(node, "score", 0) or 0),
                "title": node.metadata.get("title", "未知来源"),
                "category": node.metadata.get("category", ""),
            }
            for index, node in enumerate(nodes)
        ]

    def delete_document(
        self,
        document_id: int,
        persist: bool = True,
        stored_name: str | None = None,
    ) -> bool:
        target = str(document_id)
        identity = (stored_name or "").removeprefix("kb:")
        with self._lock:
            node_ids = [
                nid for nid, node in self.index.docstore.docs.items()
                if node.metadata.get("document_id") == target
                or (
                    identity
                    and identity in {
                        str(node.metadata.get("stored_name", "")).removeprefix("kb:"),
                        str(node.metadata.get("file_name", "")),
                    }
                )
            ]
            if not node_ids:
                self.clear_document_tombstone(document_id, stored_name)
                return False
            for nid in node_ids:
                self.index.docstore.delete_document(nid)
            self.index = self._rebuild_from_docstore(self.index.docstore)
            # Clean up parent map entries for this document
            pm = _get_parent_map()
            stale_parents = [pid for pid, entry in pm.items() if pid.startswith(f"{target}#")]
            if stale_parents:
                with _PARENT_MAP_LOCK:
                    for pid in stale_parents:
                        _parent_map.pop(pid, None)
                self._save_parent_map()
            if persist:
                self._persist()
            self._build_bm25()
            self.clear_document_tombstone(document_id, stored_name)
            return True

    def _load_document_tombstones(self) -> set[str]:
        try:
            values = json.loads(self._tombstone_path.read_text(encoding="utf-8"))
            return {str(value) for value in values if str(value).strip()}
        except (OSError, ValueError, TypeError):
            return set()

    def _persist_document_tombstones(self) -> None:
        temporary = self._tombstone_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(sorted(self._deleted_document_keys), ensure_ascii=False),
            encoding="utf-8",
        )
        temporary.replace(self._tombstone_path)

    @staticmethod
    def _document_identity_keys(document_id: int, stored_name: str | None = None) -> set[str]:
        keys = {f"id:{document_id}"}
        identity = (stored_name or "").removeprefix("kb:").strip()
        if identity:
            keys.add(f"name:{identity}")
        return keys

    def tombstone_document(self, document_id: int, stored_name: str | None = None) -> None:
        """Hide a deleted document immediately while its FAISS cleanup runs in background."""
        with self._lock:
            self._deleted_document_keys.update(
                self._document_identity_keys(document_id, stored_name),
            )
            self._persist_document_tombstones()

    def clear_document_tombstone(self, document_id: int, stored_name: str | None = None) -> None:
        with self._lock:
            self._deleted_document_keys.difference_update(
                self._document_identity_keys(document_id, stored_name),
            )
            self._persist_document_tombstones()

    def _is_document_tombstoned(self, node: Any) -> bool:
        metadata = getattr(node, "metadata", {}) or {}
        document_id = str(metadata.get("document_id", "")).strip()
        names = {
            str(metadata.get("stored_name", "")).removeprefix("kb:").strip(),
            str(metadata.get("file_name", "")).removeprefix("kb:").strip(),
        }
        return (
            bool(document_id and f"id:{document_id}" in self._deleted_document_keys)
            or any(name and f"name:{name}" in self._deleted_document_keys for name in names)
        )

    def load_knowledge_base(self, directory: Path | str | None = None, uploaded_by: int = 1) -> int:
        directory = Path(directory or settings.knowledge_base_dir)
        if not directory.exists():
            print(f"[WARN] KB dir not found: {directory}")
            return 0

        from .hhu_reader import HHUMarkdownReader
        reader = HHUMarkdownReader()
        docs = reader.load_data_from_directory(directory)
        print(f"[OK] Loaded {len(docs)} docs from KB")

        indexed = {n.metadata.get("stored_name", "") for n in self.index.docstore.docs.values()}
        indexed_hashes = {n.metadata.get("content_hash", "") for n in self.index.docstore.docs.values()}
        # Also track DB-inserted files to avoid duplicate INSERTs
        db = connect()
        try:
            existing_documents = {
                row["stored_name"]: int(row["id"])
                for row in db.execute("SELECT id,stored_name FROM documents").fetchall()
            }
        finally:
            db.close()
        added = 0
        db = connect()
        try:
            for doc in docs:
                fname = doc.metadata.get("file_name", "")
                content_hash = hashlib.sha256(doc.text.encode("utf-8", errors="ignore")).hexdigest()
                if fname in indexed or content_hash in indexed_hashes:
                    continue
                doc.metadata["stored_name"] = fname
                doc.metadata["content_hash"] = content_hash
                metadata = dict(doc.metadata)

                # Insert into SQLite so admin panel can list the document
                title = metadata.get("title", fname)
                source_url = metadata.get("source_url", "")
                category = metadata.get("category", "")
                file_path_str = metadata.get("file_path", "")
                now = utc_now()
                # Use a synthetic stored_name for the DB (file is in knowledge-base, not uploads/)
                db_stored_name = f"kb:{fname}"
                db_doc_id = existing_documents.get(db_stored_name)
                if db_doc_id is None:
                    cur = db.execute(
                        "INSERT INTO documents(title, filename, stored_name, mime_type, size, status, chunk_count, source_url, category, original_path, uploaded_by, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (title, fname, db_stored_name, "text/markdown", len(doc.text.encode("utf-8")), "READY", 0, source_url, category, file_path_str, uploaded_by, now, now),
                    )
                    db_doc_id = int(cur.lastrowid)
                    existing_documents[db_stored_name] = db_doc_id
                else:
                    db.execute(
                        "UPDATE documents SET original_path=?,content_hash=?,updated_at=? WHERE id=?",
                        (file_path_str, content_hash, now, db_doc_id),
                    )

                doc.metadata["document_id"] = str(db_doc_id)
                metadata = dict(doc.metadata)

                with self._lock:
                    if settings.parent_child_enabled:
                        children, parents = self._chunk_parent_child(doc.text, metadata)
                        for child in children:
                            self.index.insert(child)
                        _update_parent_map(parents)
                    elif settings.semantic_chunking_enabled:
                        nodes = self._create_semantic_chunks(doc.text, metadata)
                        for node in nodes:
                            self.index.insert(node)
                    else:
                        self.index.insert(doc)
                indexed.add(fname)
                indexed_hashes.add(content_hash)
                added += 1

                # Update chunk count after insertion
                node_count = sum(1 for n in self.index.docstore.docs.values() if n.metadata.get("stored_name") == fname)
                db.execute("UPDATE documents SET chunk_count=? WHERE id=?", (node_count, db_doc_id))
                chunks = self.get_document_chunks(db_doc_id, fname)
                db.execute("DELETE FROM document_chunks WHERE document_id=?", (db_doc_id,))
                db.executemany(
                    """
                    INSERT INTO document_chunks(document_id,chunk_index,content,page_number,created_at)
                    VALUES(?,?,?,?,?)
                    """,
                    [
                        (db_doc_id, item["chunk_index"], item["content"], item["page_number"], now)
                        for item in chunks
                    ],
                )

                if added % 20 == 0:
                    self._persist()
                    db.commit()
        finally:
            db.commit()
            db.close()
        self._persist()
        self._build_bm25()
        self._save_parent_map()
        print(f"[OK] KB load done: {added} new docs")
        return added

    # ── Query ──────────────────────────────────────────────────
    def _format_sources(self, source_nodes: list[Any]) -> list[dict]:
        sources = []
        for idx, node in enumerate(source_nodes, 1):
            m = getattr(node, "metadata", {}) or {}
            title = m.get("title", "未知来源")
            if str(title).strip().lower() in {"readme", "index"}:
                continue
            content = self._node_text(node)
            sources.append({
                "index": idx, "title": title,
                "source_url": m.get("source_url", ""), "category": m.get("category", ""),
                "score": round(float(getattr(node, "score", 0) or 0), 4),
                "content": content,
            })
        return sources

    @staticmethod
    def _sanitize_answer(answer: str, source_count: int) -> str:
        """Redact sensitive output and remove citations outside this response's source range."""
        sanitized = guard_sanitize(answer)

        def replace_citation(match: re.Match[str]) -> str:
            index = int(match.group(1))
            return f"[{index}]" if 1 <= index <= source_count else ""

        return re.sub(r"(?:\[|【)(\d+)(?:\]|】)", replace_citation, sanitized)

    def _load_history(self, conversation_id: int | None) -> list[ChatMessage]:
        if not conversation_id:
            return []
        with connect() as db:
            rows = db.execute(
                "SELECT role, content FROM messages WHERE conversation_id=? ORDER BY id",
                (conversation_id,),
            ).fetchall()
        return [ChatMessage(role=MessageRole.USER if r["role"] == "USER" else MessageRole.ASSISTANT, content=r["content"]) for r in rows]

    def _build_rag_prompt(self, question: str, nodes: list[Any], history: list[ChatMessage] | None = None,
                          retrieval_question: str | None = None) -> str:
        """Build the full RAG prompt: system instruction + context from retrieved nodes + history + question."""
        # Build context from retrieved nodes
        ctx_parts = []
        for i, node in enumerate(nodes, 1):
            content = node.get_content(metadata_mode=MetadataMode.NONE).strip()
            title = node.metadata.get("title", "未知来源")
            ctx_parts.append(f"[资料 {i}] 标题：{title}\n正文：{content}")
        context = "\n\n".join(ctx_parts) if ctx_parts else "暂无相关参考资料"

        # Build history
        hist_str = ""
        if history:
            hist_parts = []
            for msg in history[-6:]:  # Last 3 rounds (6 messages)
                role = "用户" if msg.role == MessageRole.USER else "助手"
                # Old citation numbers belong to old source lists and must not
                # leak into the current answer's numbering.
                history_content = re.sub(r"(?:\[|【)\d+(?:\]|】)", "", msg.content)
                history_content = guard_sanitize(history_content)
                hist_parts.append(f"{role}: {history_content}")
            hist_str = "\n".join(hist_parts)

        if re.search(r"整理|总结|归纳|概括|介绍|情况|有哪些|全面|详细", question):
            answer_plan = (
                "这是概览/整理型问题：先用 1-2 句话给出整体认识，再用 3-6 个有信息量的小标题或要点综合归纳；"
                "合并重复信息，资料未覆盖的方面放在末尾简短说明。"
            )
        elif re.search(r"如何|怎么|流程|步骤|办理|申请|操作", question):
            answer_plan = "这是操作型问题：先说明适用条件，再按实际顺序给出步骤、所需材料和注意事项。"
        elif re.search(r"比较|区别|差异|优缺点|评价|分析|为什么", question):
            answer_plan = "这是分析型问题：先给出判断，再分维度比较或解释，并明确区分资料事实与分析判断。"
        else:
            answer_plan = "这是事实型问题：直接回答核心结论，再补充必要背景；避免为了显得完整而重复原文。"

        resolved_intent = ""
        if retrieval_question and re.sub(r"\s+", "", retrieval_question) != re.sub(r"\s+", "", question):
            resolved_intent = f"【检索主题（仅用于理解指代和主题，不是用户原话）】\n{retrieval_question}\n\n"

        allowed_citations = "、".join(f"[{i}]" for i in range(1, len(nodes) + 1))
        citation_rule = (
            f"本轮共有 {len(nodes)} 个参考来源，只能使用这些编号：{allowed_citations}。"
            "严禁引用不存在的编号；没有对应资料支持的内容必须明确说资料不足。"
        )

        prompt = f"""{HHU_SYSTEM_PROMPT}

【本题回答策略】
{answer_plan}

【引用编号约束】
{citation_rule}

【参考资料】
{context}

{f"【历史对话】\n{hist_str}\n" if hist_str else ""}
{resolved_intent}【用户原始问题】
{question}

【回答】"""
        return prompt

    def _fallback_answer(self, question: str, nodes: list[Any]) -> str:
        """Build a conservative extractive answer when the configured LLM is unavailable.

        Only selects sentences with meaningful overlap (≥2 query terms) and
        explicitly says when no relevant information was found.
        """
        query_terms = self._query_terms(question)
        candidates: list[tuple[int, int, str]] = []
        for index, node in enumerate(nodes, 1):
            text = self._node_text(node)
            for sentence in re.split(r"(?<=[。！？!?；;])\s*|\n+", text):
                sentence = sentence.strip()
                if len(sentence) < 4:
                    continue
                overlap = sum(1 for term in query_terms if term in sentence)
                required_overlap = 1 if len(query_terms) == 1 else 2
                if overlap >= required_overlap:
                    candidates.append((overlap, index, sentence))
        if not candidates:
            return NO_CONTEXT_MESSAGE
        candidates.sort(key=lambda item: (item[0], -len(item[2])), reverse=True)
        selected: list[str] = []
        seen: set[str] = set()
        for overlap, index, sentence in candidates:
            normalized = re.sub(r"\s+", "", sentence)
            if normalized in seen:
                continue
            seen.add(normalized)
            selected.append(f"{sentence} [{index}]")
            if len(selected) == 3:
                break
        if not selected:
            return NO_CONTEXT_MESSAGE
        return "根据知识库资料：" + "；".join(selected)

    @staticmethod
    def _trace_header(icon: str, label: str) -> None:
        """Print a visible pipeline step separator for demo / presentation use."""
        print(f"\n{'─' * 60}")
        print(f"  {icon} {label}")
        print(f"{'─' * 60}")

    # ── Auto Strategy Selection ───────────────────────────────
    # Heuristic rules to pick the best retrieval strategy per question type.
    # Only active when ENABLE_AUTO_STRATEGY=true in .env.
    _COLLOQUIAL_MARKERS = {"咋", "啥", "啊", "老铁", "呗", "嘛", "呢", "吧", "呀", "哇", "哈", "喔"}
    _COMPARISON_MARKERS = {"对比", "区别", "不同", "比较", "哪个更", "哪边", "差异", "优缺点"}
    _PRECISION_MARKERS = {"流程", "步骤", "电话", "编号", "学号", "时间", "几点", "多少钱", "费用", "价格", "地址", "网址", "材料", "条件", "要求"}
    _DECOMPOSE_PATTERNS = [
        re.compile(r"(?:和|与|以及|还有|跟).*(?:有什么|哪个|哪些|什么|怎么|如何).*(?:不同|区别|差异|对比)"),
        re.compile(r"(?:对比|比较|区别|不同).*(?:和|与|以及)"),
    ]
    # Problem-solving: "怎么办/怎么解决/如何处理" — need broader retrieval
    _PROBLEM_SOLVING_MARKERS = {"怎么办", "怎么解决", "如何解决", "如何处理", "如何应对", "怎么处理"}
    # Descriptive questions asking "what is / what are" — semantic retrieval
    _DESCRIPTIVE_PATTERNS = [
        re.compile(r"(?:什么是|什么叫|什么叫作|啥是|啥叫)"),
        re.compile(r"(?:有什么|有哪些|有没有).*(?:方法|途径|渠道|方式|办法|措施|政策)"),
    ]

    @staticmethod
    def _auto_strategy(question: str) -> str:
        """Heuristic strategy selection based on question linguistic features."""
        q = question.strip()
        # 1. Colloquial → HyDE (bridge casual → formal)
        if any(m in q for m in HHURAGEngine._COLLOQUIAL_MARKERS):
            return "hyde"
        # 2. Multi-topic comparison → Decompose
        if any(p.search(q) for p in HHURAGEngine._DECOMPOSE_PATTERNS):
            return "decompose"
        if any(m in q for m in HHURAGEngine._COMPARISON_MARKERS) and len(q) > 15:
            return "multi"
        # 3. Problem-solving questions ("怎么办/怎么解决") → Multi-Query for broad coverage
        if any(m in q for m in HHURAGEngine._PROBLEM_SOLVING_MARKERS):
            return "multi"
        # 4. Descriptive questions ("什么是/有什么方法") → Dense semantic retrieval
        if any(p.search(q) for p in HHURAGEngine._DESCRIPTIVE_PATTERNS):
            return "dense"
        # 5. Precision query → BM25
        if any(m in q for m in HHURAGEngine._PRECISION_MARKERS):
            return "bm25"
        # 6. Short vague question → Multi-Query
        if len(q) <= 8:
            return "multi"
        # 7. Default → Hybrid
        return "hybrid"

    def stream_query(self, question: str, conversation_id: int | None = None, strategy: str = "hybrid", top_k: int | None = None) -> Iterator[str]:
        """RAG streaming: guardrails → hot-cache → rewrite → retrieve → compress → stream LLM."""
        import time as _time
        _t_start = _time.time()
        top_k = top_k or settings.top_k

        # ── Step 1 ──────────────────────────────────────────────
        self._trace_header("📨", "[1/8] 接收用户问题")
        print(f"  📝 问题: {question}")
        # Auto-strategy: override based on question characteristics
        if settings.enable_auto_strategy:
            auto = self._auto_strategy(question)
            if auto != strategy:
                print(f"  🤖 自动策略: {strategy} → {auto}")
                strategy = auto
            else:
                print(f"  🤖 自动策略: {strategy} (已是最优)")
        else:
            print(f"  🎯 策略: {strategy}")
        print(f"  📊 TopK: {top_k}")
        if conversation_id:
            print(f"  🔗 会话ID: {conversation_id}")

        # ── Step 2: Guardrails ──────────────────────────────────
        self._trace_header("🛡️", "[2/8] 安全护栏检查")
        safe, err_msg = is_question_safe(question)
        if not safe:
            print(f"  ⛔ 拦截! 原因: {err_msg[:80]}")
            yield f"event: meta\ndata: {json.dumps({'sources': [], 'generation_mode': 'guardrail'}, ensure_ascii=False)}\n\n"
            yield f"event: token\ndata: {json.dumps({'text': err_msg}, ensure_ascii=False)}\n\n"
            yield "event: done\ndata: {}\n\n"
            return
        print(f"  ✅ 通过")

        # ── Step 3: Hot FAQ Cache ───────────────────────────────
        self._trace_header("⚡", "[3/8] 热FAQ缓存查询")
        history = self._load_history(conversation_id)
        hot_answer = hot_cache_retrieve(question)
        if hot_answer:
            print(f"  🔥 缓存命中! 直接返回 (跳过检索+LLM，耗时~0ms)")
            sanitized = self._sanitize_answer(hot_answer, 0)
            yield f"event: meta\ndata: {json.dumps({'sources': [], 'hot_hit': True, 'generation_mode': 'cache'}, ensure_ascii=False)}\n\n"
            yield f"event: token\ndata: {json.dumps({'text': sanitized}, ensure_ascii=False)}\n\n"
            yield "event: done\ndata: {}\n\n"
            return
        print(f"  ❄️ 未命中 → 进入检索流程")

        # ── Step 3b: LRU Exact-Match Cache ───────────────────────
        lru_cached = _cache_get(question, strategy)
        if lru_cached:
            answer = self._sanitize_answer(
                str(lru_cached.get("answer", "")), len(lru_cached.get("sources", [])),
            )
            print(f"  💾 LRU精确缓存命中! '{question[:40]}...' (跳过检索+LLM)")
            yield f"event: meta\ndata: {json.dumps({'sources': lru_cached.get('sources', []), 'generation_mode': 'cache'}, ensure_ascii=False)}\n\n"
            for start in range(0, len(answer), 48):
                text = answer[start:start + 48]
                yield f"event: token\ndata: {json.dumps({'text': text}, ensure_ascii=False)}\n\n"
            yield "event: done\ndata: {}\n\n"
            return

        # ── Step 4: Query Rewrite ───────────────────────────────
        self._trace_header("🔄", "[4/8] 多轮查询改写")
        rewritten = self._rewrite_query_with_history(question, history)
        effective_question = rewritten if rewritten != question else question
        if rewritten != question:
            print(f"  📝 原始追问: \"{question}\"")
            print(f"  🔄 改写结果: \"{rewritten}\"")
            print(f"  🏷️ 改写方式: LLM指代消解")
        else:
            if history and len(history) >= 2:
                print(f"  ➡️ 有对话历史但无需改写 (问题已完整)")
            else:
                print(f"  ➡️ 首轮问题, 无需改写")

        # ── Step 5: Retrieval ───────────────────────────────────
        _t_ret = _time.time()

        # FAISS/BM25 and docstore access are protected, but the DeepSeek stream
        # below must not block document management or other users' questions.
        with self._lock:
            nodes, retrieval_question = self._retrieve_question(
                effective_question,
                strategy,
                top_k=max(20, top_k * 3),
                enable_crag=settings.enable_self_rag,
            )
            nodes = nodes[:top_k]
            _ret_ms = (_time.time() - _t_ret) * 1000
            relevant = self._has_relevant_context(retrieval_question, nodes)
            citation_nodes = self._group_citation_nodes(nodes) if relevant else []
            sources = self._format_sources(citation_nodes)
            prompt = self._build_rag_prompt(
                question,
                citation_nodes,
                history,
                retrieval_question=effective_question if effective_question != question else retrieval_question,
            ) if relevant else ""

        # Print retrieval details (after lock release so we don't hold it for IO)
        self._trace_header("🔍", f"[5/8] 检索阶段 — 策略: {strategy}")
        print(f"  ⏱️ 检索耗时: {_ret_ms:.0f}ms")
        print(f"  📊 最终保留: {len(nodes)} 条节点")
        if nodes:
            for i, n in enumerate(nodes[:3]):
                meta = getattr(n, "metadata", {}) or {}
                title = str(meta.get("title", "未知来源")).strip() or "未知来源"
                score = float(getattr(n, "score", 0) or 0)
                content_preview = self._node_text(n)[:60].replace("\n", " ")
                print(f"  [{i+1}] {title} (置信度: {score:.0%}) | {content_preview}...")

        # ── Step 6: Relevance Gate ──────────────────────────────
        self._trace_header("🚦", "[6/8] 相关性门控")
        q_terms = self._query_terms(retrieval_question)
        print(f"  🔑 检索词: {q_terms if q_terms else '(空)'}")
        if relevant:
            print(f"  ✅ 判定: 相关 → 进入 LLM 生成")
        else:
            print(f"  ❌ 判定: 不相关 → 拒答 (知识库无覆盖)")

        if not relevant:
            yield f"event: meta\ndata: {json.dumps({'sources': [], 'generation_mode': 'no_context'}, ensure_ascii=False)}\n\n"
            yield f"event: token\ndata: {json.dumps({'text': NO_CONTEXT_MESSAGE}, ensure_ascii=False)}\n\n"
            yield "event: done\ndata: {}\n\n"
            return

        # ── Step 7: Prompt ──────────────────────────────────────
        self._trace_header("📝", "[7/8] Prompt 构建")
        ctx_chars = sum(len(self._node_text(n)) for n in citation_nodes)
        src_titles = [str((getattr(n, "metadata", {}) or {}).get("title", "?")) for n in citation_nodes]
        print(f"  📋 系统指令: {len(HHU_SYSTEM_PROMPT)} 字")
        print(f"  📚 上下文: {len(citation_nodes)} 个来源, ~{ctx_chars} 字")
        print(f"  💬 对话历史: {len(history) // 2} 轮")
        print(f"  🧮 估算 Token: ~{len(prompt) // 2}")
        print(f"  📖 来源标题: {src_titles[:5]}")

        # ── Step 8: LLM ─────────────────────────────────────────
        self._trace_header("🤖", f"[8/8] LLM 生成 — {settings.llm_model} (t=0.1)")
        yield f"event: meta\ndata: {json.dumps({'sources': sources, 'generation_mode': 'llm'}, ensure_ascii=False)}\n\n"
        try:
            llm_response = Settings.llm.stream_complete(prompt)
            raw_answer = ""
            for chunk in llm_response:
                delta = chunk.delta if hasattr(chunk, "delta") else str(chunk)
                if delta:
                    raw_answer += delta
            answer = self._sanitize_answer(raw_answer, len(sources))
            for start in range(0, len(answer), 48):
                text = answer[start:start + 48]
                yield f"event: token\ndata: {json.dumps({'text': text}, ensure_ascii=False)}\n\n"
            _total_ms = (_time.time() - _t_start) * 1000
            print(f"  ✅ 流式生成完成")
            print(f"  ⏱️ LLM耗时: {_total_ms - _ret_ms:.0f}ms  |  总耗时: {_total_ms:.0f}ms")
            print(f"  📤 回答长度: {len(answer)} 字")
            # Save to LRU cache for exact-match reuse
            _cache_set(question, strategy, {"answer": answer, "sources": sources})
        except Exception as stream_error:
            # Some OpenAI-compatible gateways occasionally reject or interrupt
            # streaming while still accepting a normal completion request.
            # Retry once in non-streaming mode before degrading to extraction.
            print(f"  ⚠️ 流式失败 ({type(stream_error).__name__}): {stream_error}")
            print(f"  🔄 降级到非流式重试...")
            try:
                answer = self._sanitize_answer(
                    str(Settings.llm.complete(prompt)), len(sources),
                )
                for start in range(0, len(answer), 48):
                    text = answer[start:start + 48]
                    yield f"event: token\ndata: {json.dumps({'text': text}, ensure_ascii=False)}\n\n"
                _total_ms = (_time.time() - _t_start) * 1000
                print(f"  ✅ 非流式重试成功  |  总耗时: {_total_ms:.0f}ms")
                _cache_set(question, strategy, {"answer": answer, "sources": sources})
            except Exception as completion_error:
                print(f"  ❌ LLM 全部失败 ({type(completion_error).__name__}): {completion_error}")
                print(f"  🆘 降级到 fallback 关键词摘取...")
                fallback = self._sanitize_answer(
                    self._fallback_answer(retrieval_question, citation_nodes), len(sources),
                )
                yield f"event: meta\ndata: {json.dumps({'sources': sources, 'generation_mode': 'fallback'}, ensure_ascii=False)}\n\n"
                yield f"event: token\ndata: {json.dumps({'text': fallback}, ensure_ascii=False)}\n\n"
                _total_ms = (_time.time() - _t_start) * 1000
                print(f"  ⚠️ Fallback 完成  |  总耗时: {_total_ms:.0f}ms")
        print(f"{'═' * 60}\n")
        yield "event: done\ndata: {}\n\n"

    def query(self, question: str, conversation_id: int | None = None, strategy: str = "hybrid") -> dict:
        """Sync RAG query with guardrails, hot-cache, query-rewrite, compression, and Self-RAG/CRAG."""
        safe, err_msg = is_question_safe(question)
        if not safe:
            return {"answer": err_msg, "sources": [], "generation_mode": "guardrail"}

        history = self._load_history(conversation_id)
        hot_answer = hot_cache_retrieve(question)
        if hot_answer:
            return {
                "answer": self._sanitize_answer(hot_answer, 0), "sources": [],
                "hot_hit": True, "generation_mode": "cache",
            }

        cached = _cache_get(question, strategy)
        if cached:
            print(f"[CACHE HIT] '{question[:40]}...'")
            cached["answer"] = self._sanitize_answer(
                str(cached.get("answer", "")), len(cached.get("sources", [])),
            )
            return cached

        rewritten = self._rewrite_query_with_history(question, history)
        effective_question = rewritten if rewritten != question else question
        with self._lock:
            nodes, retrieval_question = self._retrieve_question(
                effective_question,
                strategy,
                top_k=max(20, settings.top_k * 3),
                enable_crag=settings.enable_self_rag,
            )
            nodes = nodes[:settings.top_k]
            relevant = self._has_relevant_context(retrieval_question, nodes)
            citation_nodes = self._group_citation_nodes(nodes) if relevant else []
            sources = self._format_sources(citation_nodes)
            prompt = self._build_rag_prompt(
                question,
                citation_nodes,
                history,
                retrieval_question=effective_question if effective_question != question else retrieval_question,
            ) if relevant else ""

        if not relevant:
            result = {"answer": NO_CONTEXT_MESSAGE, "sources": [], "generation_mode": "no_context"}
            _cache_set(question, strategy, result)
            return result

        generation_mode = "llm"
        try:
            answer = self._sanitize_answer(str(Settings.llm.complete(prompt)), len(sources))
        except Exception as exc:
            print(f"[ERROR] LLM completion failed ({type(exc).__name__}): {exc}")
            answer = self._sanitize_answer(
                self._fallback_answer(retrieval_question, citation_nodes), len(sources),
            )
            generation_mode = "fallback"

        result = {"answer": answer, "sources": sources, "generation_mode": generation_mode}
        _cache_set(question, strategy, result)
        return result

    def _group_citation_nodes(self, nodes: list[Any]) -> list[Any]:
        """Group chunks by document so prompt citations match displayed sources."""
        groups: OrderedDict[str, dict[str, Any]] = OrderedDict()
        seen_chunks: set[str] = set()
        for position, node in enumerate(nodes):
            metadata = dict(getattr(node, "metadata", {}) or {})
            title = str(metadata.get("title", "未知来源")).strip() or "未知来源"
            if title.lower() in {"readme", "index"}:
                continue
            source_key = str(
                metadata.get("document_id")
                or metadata.get("source_url")
                or title
                or f"source-{position}"
            ).strip().lower()
            content = self._node_text(node)
            chunk_key = hashlib.sha1(re.sub(r"\s+", " ", content).encode("utf-8")).hexdigest()
            if not content or chunk_key in seen_chunks:
                continue
            seen_chunks.add(chunk_key)
            if source_key not in groups:
                groups[source_key] = {
                    "metadata": metadata,
                    "parts": [],
                    "score": float(getattr(node, "score", 0) or 0),
                }
            group = groups[source_key]
            group["parts"].append(content)
            group["score"] = max(group["score"], float(getattr(node, "score", 0) or 0))

        return [
            NodeWithScore(
                node=TextNode(text="\n\n".join(group["parts"]), metadata=group["metadata"]),
                score=group["score"],
            )
            for group in groups.values()
        ]


    # ── Self-RAG Corrective Loop ──────────────────────────────────
    def self_rag_correct(self, question: str, original_answer: str,
                         original_sources: list[dict] | None = None,
                         max_retry: int = 2) -> dict:
        """Self-RAG corrective loop triggered by user dislike.
        Ported from Design's self_rag_correct() — diagnoses root cause,
        rewrites query, re-retrieves, and re-generates.

        Returns dict with: status, new_answer, new_sources, retries, diagnosis
        """
        if not original_sources:
            # Fallback: retrieve fresh
            original_nodes = self._retrieve(question, "hybrid", top_k=20)[:settings.top_k]
            original_sources = self._format_sources(self._group_citation_nodes(original_nodes))

        chunks_text = "\n".join(
            [s.get("content", "")[:200] for s in (original_sources or [])[:5]]
        )
        best_answer = original_answer
        best_sources = original_sources
        diagnosis = ""

        for attempt in range(1, max_retry + 1):
            print(f"  [Self-RAG] 第 {attempt}/{max_retry} 次自检...")

            # Step A1: Diagnose
            diagnosis_prompt = (
                "请分析以下AI回答是否存在问题，并判断根因是「检索不足」还是「逻辑错误」。\n\n"
                f"【用户问题】{question}\n\n"
                f"【参考资料】{chunks_text}\n\n"
                f"【AI回答】{original_answer}\n\n"
                "请用一句话回复，格式为: 根因=检索不足|逻辑错误|无问题, 说明=..."
            )
            try:
                diagnosis = str(Settings.llm.complete(diagnosis_prompt)).strip()
            except Exception as e:
                print(f"  [Self-RAG] 诊断失败: {e}")
                break

            print(f"  [Self-RAG] 诊断: {diagnosis[:100]}...")

            # Step A2: Branch by root cause
            if "检索不足" in diagnosis:
                # Rewrite query → re-retrieve → re-generate
                rewrite_prompt = (
                    "根据以下诊断，从一个不同的角度改写用户问题，给出一个更好的检索查询。\n"
                    f"原始问题: {question}\n诊断: {diagnosis}\n新查询:"
                )
                try:
                    new_query = str(Settings.llm.complete(rewrite_prompt)).strip()
                except Exception:
                    new_query = question

                print(f"  [Self-RAG] 改写查询: {new_query[:50]}...")
                new_nodes = self._retrieve(new_query, "hybrid", top_k=20,
                                          enable_crag=True)[:settings.top_k]
                if not new_nodes:
                    new_nodes = self._retrieve(question, "hybrid", top_k=20)[:settings.top_k]

                new_nodes = self._group_citation_nodes(new_nodes)
                new_sources = self._format_sources(new_nodes)
                prompt = self._build_rag_prompt(question, new_nodes)
                prompt += "\n\n【重要提醒】上一轮回答被用户指出存在问题，请务必只依据参考资料回答，不要编造任何信息。"

            elif "逻辑错误" in diagnosis:
                # Self-critique → regenerate
                critique_prompt = (
                    f"你之前的回答被用户指出存在逻辑错误。\n\n"
                    f"【用户问题】{question}\n【你的回答】{original_answer}\n"
                    f"【诊断】{diagnosis}\n\n"
                    "请先指出自己回答中的问题，然后给出修正后的答案。\n修正后的答案:"
                )
                try:
                    new_answer = str(Settings.llm.complete(critique_prompt)).strip()
                except Exception:
                    continue
                new_answer = self._sanitize_answer(new_answer, len(original_sources))
                return {
                    "status": "corrected",
                    "new_answer": new_answer,
                    "new_sources": original_sources,
                    "retries": attempt,
                    "diagnosis": diagnosis,
                }
            else:
                # Unclear issue — mild retry
                new_nodes = self._retrieve(question, "hybrid", top_k=20,
                                          enable_crag=True)[:settings.top_k]
                new_nodes = self._group_citation_nodes(new_nodes)
                new_sources = self._format_sources(new_nodes)
                prompt = self._build_rag_prompt(question, new_nodes)
                prompt += "\n\n请更加准确、详细地回答。"

            try:
                new_answer = str(Settings.llm.complete(prompt)).strip()
            except Exception:
                continue
            new_answer = self._sanitize_answer(new_answer, len(new_sources))

            # Step A3: Quality check
            if new_answer and new_answer != original_answer:
                best_answer = new_answer
                best_sources = new_sources
                print(f"  [Self-RAG] 第{attempt}次修正成功")
                return {
                    "status": "corrected",
                    "new_answer": best_answer,
                    "new_sources": best_sources,
                    "retries": attempt,
                    "diagnosis": diagnosis,
                }
            else:
                print(f"  [Self-RAG] 第{attempt}次修正无变化，继续...")

        if best_answer != original_answer:
            return {
                "status": "corrected",
                "new_answer": best_answer,
                "new_sources": best_sources,
                "retries": max_retry,
                "diagnosis": diagnosis,
            }
        return {
            "status": "no_improvement",
            "new_answer": original_answer,
            "new_sources": original_sources,
            "retries": max_retry,
            "diagnosis": diagnosis,
        }


rag_engine = HHURAGEngine()
