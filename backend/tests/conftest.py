"""Shared test fixtures — each test gets isolated temp storage."""

import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

# Settings are instantiated during test collection. Isolate all application
# storage before any test module can import app.config; never point tests at the
# developer database from backend/.env.
_TEST_ROOT = Path(tempfile.mkdtemp(prefix="campus-qa-tests-"))
os.environ.update({
    "DATABASE_PATH": str(_TEST_ROOT / "campus_qa.db"),
    "UPLOAD_DIR": str(_TEST_ROOT / "uploads"),
    "DATA_DIR": str(_TEST_ROOT / "data"),
    "KNOWLEDGE_BASE_DIR": str(_TEST_ROOT / "kb"),
    "APP_SECRET": "test-secret",
    "LLM_API_KEY": "sk-test",
    "DASHSCOPE_API_KEY": "",
    "RATE_LIMIT_ENABLED": "false",
    "CAPTCHA_REQUIRED": "false",
})

# ── Mock sentence-transformers (no model download) ────────
_cache: dict[str, np.ndarray] = {}

class FakeST:
    def __init__(self, model_name=None, **kw): pass
    def encode(self, texts, normalize_embeddings=True, show_progress_bar=False):
        single = isinstance(texts, str)
        if single: texts = [texts]
        dim = 512
        vecs = np.zeros((len(texts), dim), dtype=np.float32)
        for i, text in enumerate(texts):
            if text not in _cache:
                v = np.zeros(dim, dtype=np.float32)
                for j, ch in enumerate(text): v[hash(ch) % dim] += 1.0
                norm = np.linalg.norm(v)
                _cache[text] = (v / norm) if norm > 0 else v
            vecs[i] = _cache[text].copy()
        return vecs[0] if single else vecs
    def get_embedding_dimension(self): return 512

# Patch sentence_transformers if installed, otherwise mock the whole module
try:
    import sentence_transformers
    _st_patch = patch("sentence_transformers.SentenceTransformer", FakeST)
    _st_patch.start()
except (ImportError, ModuleNotFoundError):
    import sys
    from types import ModuleType
    _fake_st = ModuleType("sentence_transformers")
    _fake_st.SentenceTransformer = FakeST
    sys.modules["sentence_transformers"] = _fake_st


@pytest.fixture
def client(tmp_path: Path):
    """Test client with isolated temp storage per test."""
    os.environ.update({
        "DATABASE_PATH": str(tmp_path / "campus_qa.db"),
        "UPLOAD_DIR": str(tmp_path / "uploads"),
        "DATA_DIR": str(tmp_path / "data"),
        "KNOWLEDGE_BASE_DIR": str(tmp_path / "kb"),
        "APP_SECRET": "test-secret",
        "LLM_API_KEY": "sk-test",
        "DASHSCOPE_API_KEY": "",
        "RATE_LIMIT_ENABLED": "false",
    })
    _cache.clear()

    from app.rag.engine import HHURAGEngine
    HHURAGEngine._instance = None

    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin_token(client):
    r = client.post("/api/auth/login", json={"email": "admin@campus.example", "password": "admin123"})
    return r.json()["data"]["token"]


# Lazy import to happen after env setup
from fastapi.testclient import TestClient
