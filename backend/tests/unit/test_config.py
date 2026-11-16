"""Unit tests for config module."""

import os
from app.config import Settings


class TestSettings:
    def test_defaults(self):
        s = Settings()
        assert s.llm_model == "deepseek-chat"
        assert s.top_k == 5
        assert s.chunk_size == 500

    def test_local_embedding_detection(self):
        os.environ["DASHSCOPE_API_KEY"] = ""
        s = Settings()
        assert s.use_local_embedding is True

    def test_defaults_are_sane(self):
        s = Settings()
        assert s.top_k > 0
        assert s.chunk_size > 0
        assert isinstance(s.llm_model, str)
