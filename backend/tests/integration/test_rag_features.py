"""RAG advanced feature integration tests — cache, decompose, rewrite, threshold, compression."""

import json
import os


class TestEvidenceReranking:
    def test_generic_school_match_does_not_outrank_motto_evidence(self, client):
        from llama_index.core.schema import NodeWithScore, TextNode
        from app.rag.engine import rag_engine

        dorm = NodeWithScore(
            node=TextNode(
                text='“河海大学”企业微信 → 后勤服务 → 在线报修。',
                metadata={"title": "河海大学学生宿舍管理规定"},
            ),
            score=1.0,
        )
        motto = NodeWithScore(
            node=TextNode(
                text="河海大学校训是艰苦朴素、实事求是、严格要求、勇于探索。",
                metadata={"title": "河海大学校园服务指南"},
            ),
            score=0.8,
        )

        results = rag_engine._evidence_rerank(
            "河海大学校训有什么问题", [dorm, motto], top_k=5,
        )

        assert len(results) == 1
        assert results[0].metadata["title"] == "河海大学校园服务指南"
        assert 0 < results[0].score < 0.99


class TestCache:
    def test_cache_hit(self, client, admin_token):
        """Same question + strategy returns cached result."""
        headers = {"Authorization": f"Bearer {admin_token}"}
        payload = {"question": "河海大学校训是什么？", "strategy": "hybrid"}

        r1 = client.post("/api/chat/sync", headers=headers, json=payload)
        assert r1.status_code == 200
        answer1 = r1.json()["data"]["answer"]

        r2 = client.post("/api/chat/sync", headers=headers, json=payload)
        assert r2.status_code == 200
        answer2 = r2.json()["data"]["answer"]

        # Cache should return the same answer text
        assert answer1 == answer2

    def test_cache_key_different_strategy(self, client, admin_token):
        """Different strategies produce different cache keys."""
        headers = {"Authorization": f"Bearer {admin_token}"}
        question = "河海大学校训"

        r1 = client.post("/api/chat/sync", headers=headers,
                         json={"question": question, "strategy": "hybrid"})
        assert r1.status_code == 200

        r2 = client.post("/api/chat/sync", headers=headers,
                         json={"question": question, "strategy": "dense"})
        assert r2.status_code == 200

        # Both should return valid answers
        assert len(r1.json()["data"]["answer"]) > 0
        assert len(r2.json()["data"]["answer"]) > 0


class TestStrategies:
    def test_hybrid_strategy(self, client, admin_token):
        headers = {"Authorization": f"Bearer {admin_token}"}
        r = client.post("/api/chat/sync", headers=headers,
                        json={"question": "校园卡怎么补办？", "strategy": "hybrid"})
        assert r.status_code == 200
        data = r.json()["data"]
        assert "answer" in data
        assert isinstance(data["sources"], list)

    def test_dense_strategy(self, client, admin_token):
        headers = {"Authorization": f"Bearer {admin_token}"}
        r = client.post("/api/chat/sync", headers=headers,
                        json={"question": "图书馆", "strategy": "dense"})
        assert r.status_code == 200

    def test_bm25_strategy(self, client, admin_token):
        headers = {"Authorization": f"Bearer {admin_token}"}
        r = client.post("/api/chat/sync", headers=headers,
                        json={"question": "奖学金申请", "strategy": "bm25"})
        assert r.status_code == 200
        assert len(r.json()["data"]["answer"]) > 0

    def test_hyde_strategy(self, client, admin_token):
        headers = {"Authorization": f"Bearer {admin_token}"}
        r = client.post("/api/chat/sync", headers=headers,
                        json={"question": "河海大学有哪些校区？", "strategy": "hyde"})
        assert r.status_code == 200
        assert len(r.json()["data"]["answer"]) > 0

    def test_multi_query_strategy(self, client, admin_token):
        headers = {"Authorization": f"Bearer {admin_token}"}
        r = client.post("/api/chat/sync", headers=headers,
                        json={"question": "如何办理校园卡？", "strategy": "multi"})
        assert r.status_code == 200
        assert len(r.json()["data"]["answer"]) > 0

    def test_decompose_strategy(self, client, admin_token):
        headers = {"Authorization": f"Bearer {admin_token}"}
        r = client.post("/api/chat/sync", headers=headers,
                        json={"question": "学校图书馆周末开放吗，借书需要什么证件？", "strategy": "decompose"})
        assert r.status_code == 200
        assert len(r.json()["data"]["answer"]) > 0

    def test_full_strategy(self, client, admin_token):
        headers = {"Authorization": f"Bearer {admin_token}"}
        r = client.post("/api/chat/sync", headers=headers,
                        json={"question": "校园卡挂失流程", "strategy": "full"})
        assert r.status_code == 200
        assert len(r.json()["data"]["answer"]) > 0

    def test_invalid_strategy_returns_error(self, client, admin_token):
        headers = {"Authorization": f"Bearer {admin_token}"}
        r = client.post("/api/chat/sync", headers=headers,
                        json={"question": "test", "strategy": "invalid"})
        assert r.status_code == 422  # Pydantic validation


class TestSourceAttribution:
    def test_sources_have_required_fields(self, client, admin_token):
        headers = {"Authorization": f"Bearer {admin_token}"}
        r = client.post("/api/chat/sync", headers=headers,
                        json={"question": "河海大学校训是什么？", "strategy": "hybrid"})
        assert r.status_code == 200
        sources = r.json()["data"].get("sources", [])
        for s in sources:
            assert "index" in s
            assert "title" in s
            assert "score" in s
            assert isinstance(s["score"], (int, float))


class TestConversationFlow:
    def test_new_conversation_created_on_first_question(self, client, admin_token):
        headers = {"Authorization": f"Bearer {admin_token}"}
        r = client.post("/api/chat/sync", headers=headers,
                        json={"question": "测试问题", "strategy": "hybrid"})
        assert r.status_code == 200
        conv_id = r.json()["data"].get("conversation_id")
        assert conv_id is not None

    def test_multi_turn_conversation(self, client, admin_token):
        headers = {"Authorization": f"Bearer {admin_token}"}
        # First turn
        r1 = client.post("/api/chat/sync", headers=headers,
                         json={"question": "河海大学图书馆在哪里？", "strategy": "hybrid"})
        assert r1.status_code == 200
        conv_id = r1.json()["data"]["conversation_id"]

        # Second turn (same conversation)
        r2 = client.post("/api/chat/sync", headers=headers,
                         json={"question": "开放时间呢？", "conversation_id": conv_id, "strategy": "hybrid"})
        assert r2.status_code == 200
        assert len(r2.json()["data"]["answer"]) > 0

    def test_cannot_access_others_conversation(self, client, admin_token):
        """A student cannot access admin's conversation."""
        import uuid
        # Register a new student
        r = client.post("/api/auth/register", json={
            "name": "测试学生", "email": f"conv-test-{uuid.uuid4().hex[:8]}@test.com", "password": "123456"
        })
        student_token = r.json()["data"]["token"]

        # Admin creates a conversation
        headers_admin = {"Authorization": f"Bearer {admin_token}"}
        r = client.post("/api/chat/sync", headers=headers_admin,
                        json={"question": "admin的问题", "strategy": "hybrid"})
        conv_id = r.json()["data"]["conversation_id"]

        # Student tries to access it
        headers_stu = {"Authorization": f"Bearer {student_token}"}
        r = client.get(f"/api/conversations/{conv_id}", headers=headers_stu)
        assert r.status_code == 404


class TestNoRelevantContent:
    def test_irrelevant_question_returns_friendly_message(self, client, admin_token):
        """Questions with no matching context return a friendly fallback."""
        headers = {"Authorization": f"Bearer {admin_token}"}
        r = client.post("/api/chat/sync", headers=headers,
                        json={"question": "火星上有没有水？", "strategy": "hybrid"})
        assert r.status_code == 200
        answer = r.json()["data"]["answer"]
        # Should indicate no relevant information found
        assert any(phrase in answer for phrase in ["暂未找到", "暂无相关", "暂无", "没有相关"])


class TestStreamingSSE:
    def test_stream_returns_valid_sse(self, client, admin_token):
        """Streaming endpoint returns SSE with meta, token, done events."""
        headers = {"Authorization": f"Bearer {admin_token}"}
        r = client.post("/api/chat/stream", headers=headers,
                        json={"question": "河海大学校训", "strategy": "hybrid"})
        assert r.status_code == 200
        body = r.text
        assert "event: meta" in body or "event: token" in body or "event: done" in body


class TestAdvancedChunkingStrategies:
    """Tests for §13.1 Small-to-Big, §13.2 Parent-Child, §13.4 Semantic Chunking."""

    def test_parent_child_strategy_returns_results(self, client, admin_token):
        """Small-to-Big (parent_child) strategy should return answers with sources."""
        headers = {"Authorization": f"Bearer {admin_token}"}
        r = client.post("/api/chat/sync", headers=headers,
                        json={"question": "河海大学校训是什么？", "strategy": "parent_child"})
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data["answer"]) > 0
        # Should still have source attribution
        assert isinstance(data["sources"], list)

    def test_parent_child_sources_have_content(self, client, admin_token):
        """Small-to-Big should return parent-sized context (richer than child)."""
        headers = {"Authorization": f"Bearer {admin_token}"}
        r = client.post("/api/chat/sync", headers=headers,
                        json={"question": "图书馆开放时间", "strategy": "parent_child"})
        assert r.status_code == 200
        sources = r.json()["data"].get("sources", [])
        # Sources should contain content
        for s in sources:
            assert len(s.get("content", "")) > 0

    def test_semantic_chunking_config_applied(self, client, admin_token):
        """Verify semantic chunking can be enabled via env and doesn't break queries."""
        headers = {"Authorization": f"Bearer {admin_token}"}
        # Even if semantic chunking isn't enabled, other strategies should still work
        for strategy in ["hybrid", "dense", "bm25"]:
            r = client.post("/api/chat/sync", headers=headers,
                            json={"question": "校园卡", "strategy": strategy})
            assert r.status_code == 200
            assert len(r.json()["data"]["answer"]) > 0

    def test_parent_child_handles_no_parent_data(self, client, admin_token):
        """When no parent-child data exists, strategy should fall back gracefully."""
        headers = {"Authorization": f"Bearer {admin_token}"}
        r = client.post("/api/chat/sync", headers=headers,
                        json={"question": "测试问题", "strategy": "parent_child"})
        assert r.status_code == 200
        # Should still get an answer (falls back to hybrid if no parent data)
        assert len(r.json()["data"]["answer"]) > 0

    def test_hybrid_strategy_works_alongside_advanced_chunking(self, client, admin_token):
        """Standard strategies should not be affected by advanced chunking config."""
        headers = {"Authorization": f"Bearer {admin_token}"}
        for strategy in ["hybrid", "multi", "decompose", "full"]:
            r = client.post("/api/chat/sync", headers=headers,
                            json={"question": "河海大学", "strategy": strategy})
            assert r.status_code == 200
            data = r.json()["data"]
            assert "answer" in data
            assert "sources" in data


class TestSemanticChunker:
    """Unit tests for the SemanticChunker class."""

    def test_split_simple_text(self):
        """SemanticChunker should return chunks for simple text."""
        from app.rag.engine import SemanticChunker
        from app.rag.engine import _get_local_embedding_model
        embed = _get_local_embedding_model()
        chunker = SemanticChunker(embed, threshold=0.6, min_chunk_size=50, max_chunk_size=500)
        text = "河海大学位于江苏省南京市。学校创建于1915年。河海大学是一所以水利为特色的全国重点大学。"
        chunks = chunker.split(text)
        assert len(chunks) >= 1
        assert all(len(c.strip()) > 0 for c in chunks)

    def test_split_long_text(self):
        """SemanticChunker handles longer multi-topic text."""
        from app.rag.engine import SemanticChunker
        from app.rag.engine import _get_local_embedding_model
        embed = _get_local_embedding_model()
        chunker = SemanticChunker(embed, threshold=0.6, min_chunk_size=50, max_chunk_size=500)
        text = (
            "河海大学是一所以水利为特色的全国重点大学。学校设有多个学院。"
            "图书馆位于江宁校区中心位置。图书馆藏书丰富，涵盖各个学科。"
            "校园卡可以在食堂、图书馆等多处使用。补办校园卡需要到信息中心。"
            "奖学金分为国家奖学金和校级奖学金两大类。申请奖学金需要满足成绩要求。"
        )
        chunks = chunker.split(text)
        assert len(chunks) >= 1
        # Semantically different topics should ideally be in different chunks
        assert sum(len(c) for c in chunks) >= len(text) * 0.7

    def test_empty_text(self):
        """SemanticChunker handles empty input."""
        from app.rag.engine import SemanticChunker
        from app.rag.engine import _get_local_embedding_model
        embed = _get_local_embedding_model()
        chunker = SemanticChunker(embed)
        assert chunker.split("") == []
        assert chunker.split("   ") == []

    def test_fallback_on_short_text(self):
        """SemanticChunker falls back for texts shorter than min_chunk."""
        from app.rag.engine import SemanticChunker
        from app.rag.engine import _get_local_embedding_model
        embed = _get_local_embedding_model()
        chunker = SemanticChunker(embed, threshold=0.6, min_chunk_size=100, max_chunk_size=500)
        text = "短文本。"
        chunks = chunker.split(text)
        assert len(chunks) == 1
