"""Regression tests for natural-language RAG retrieval and prompt synthesis."""

from llama_index.core.schema import NodeWithScore, TextNode


def _node(text: str, title: str = "校园足球资料", score: float = 0.7) -> NodeWithScore:
    return NodeWithScore(node=TextNode(text=text, metadata={"title": title}), score=score)


class TestNaturalLanguageQueryUnderstanding:
    def test_conversational_request_keeps_the_same_topic_as_keyword(self, client):
        from app.rag.engine import rag_engine

        assert rag_engine._normalize_retrieval_query("足球") == "足球"
        assert rag_engine._normalize_retrieval_query("关于足球的信息，帮我整理一下") == "足球"
        assert rag_engine._retrieval_queries("关于足球的信息，帮我整理一下") == ["足球"]

    def test_common_question_words_do_not_become_relevance_evidence(self, client):
        from app.rag.engine import rag_engine

        terms = rag_engine._query_terms("今天天气怎么样？")

        assert "怎么样" not in terms
        assert "今天天气" in terms
        assert not rag_engine._has_relevant_context(
            "今天天气怎么样？",
            [_node("校园活动安排与天气无关。", title="校园活动通知", score=0.9)],
        )

    def test_single_distinct_topic_is_enough_for_relevance(self, client):
        from app.rag.engine import rag_engine

        nodes = [_node("学校足球队定期开展训练，并参加校园足球赛事。")]

        assert rag_engine._has_relevant_context("足球", nodes)
        assert rag_engine._has_relevant_context("关于足球的信息，帮我整理一下", nodes)

    def test_complex_question_creates_multiple_local_subqueries(self, client):
        from app.rag.engine import rag_engine

        queries = rag_engine._retrieval_queries("图书馆周末开放吗？另外，借书需要什么证件？")

        assert any("图书馆" in query and "开放" in query for query in queries)
        assert any("借书" in query and "证件" in query for query in queries)

    def test_only_elliptical_followups_are_rewritten(self, client):
        from app.rag.engine import rag_engine

        assert not rag_engine._needs_history_rewrite("足球")
        assert not rag_engine._needs_history_rewrite("关于足球的信息，帮我整理一下")
        assert not rag_engine._needs_history_rewrite("河海大学图书馆在哪里？")
        assert rag_engine._needs_history_rewrite("周末开放吗？")
        assert rag_engine._needs_history_rewrite("进去需要带什么证件？")


class TestSourceRelevanceCalibration:
    def test_hybrid_retrieval_keeps_exact_bm25_hit_ahead_of_semantic_near_match(self, client, monkeypatch):
        from app.rag.engine import rag_engine

        military_training = _node(
            "2017级学生参加军训成果汇报。", title="学生军训新闻", score=0.58,
        )
        school_motto = _node(
            "河海大学校训是艰苦朴素、实事求是、严格要求、勇于探索。",
            title="学校简介",
            score=0.20,
        )
        monkeypatch.setattr(
            rag_engine, "_dense_retrieve", lambda query, top_k: [military_training, school_motto],
        )
        monkeypatch.setattr(
            rag_engine, "_bm25_search", lambda query, top_k: [(school_motto.node_id, 1.0)],
        )

        results = rag_engine._hybrid_retrieve("校训", top_k=5)

        assert results[0].metadata["title"] == "学校简介"
        assert "艰苦朴素" in results[0].get_content()

    def test_generic_procedure_document_is_not_a_scholarship_source(self, client):
        from app.rag.engine import rag_engine

        scholarship = _node(
            "奖学金评定需要经过学院审核和学校公示。",
            title="河海大学奖学金申请指南",
            score=0.72,
        )
        copyright_process = _node(
            "软件著作权申请流程包括填写材料、提交申请和等待审核。",
            title="软著申请流程",
            score=0.85,
        )

        results = rag_engine._evidence_rerank(
            "申请奖学金需要什么条件、材料和办理流程？",
            [copyright_process, scholarship],
            top_k=5,
        )

        assert [result.metadata["title"] for result in results] == ["河海大学奖学金申请指南"]

    def test_single_keyword_match_is_not_forced_to_98_percent(self, client):
        from app.rag.engine import rag_engine

        result = rag_engine._evidence_rerank(
            "足球",
            [_node("足球队开展足球训练并参加足球比赛。", title="校园足球资料", score=0.8)],
            top_k=1,
        )[0]

        assert 0.6 < result.score < 0.95

    def test_prompt_and_source_indices_use_the_same_grouped_documents(self, client):
        from app.rag.engine import rag_engine

        nodes = [
            _node("足球队开展日常训练。", title="足球发展报告", score=0.81),
            _node("足球队参加大学生联赛。", title="足球发展报告", score=0.76),
            _node("学校举办校友足球赛。", title="校友足球活动", score=0.68),
        ]

        grouped = rag_engine._group_citation_nodes(nodes)
        sources = rag_engine._format_sources(grouped)
        prompt = rag_engine._build_rag_prompt("介绍足球情况", grouped)

        assert len(grouped) == 2
        assert [source["index"] for source in sources] == [1, 2]
        assert [source["title"] for source in sources] == ["足球发展报告", "校友足球活动"]
        assert "[资料 1] 标题：足球发展报告" in prompt
        assert "[资料 2] 标题：校友足球活动" in prompt
        assert "日常训练" in sources[0]["content"]
        assert "大学生联赛" in sources[0]["content"]


class TestAnswerSynthesisPrompt:
    def test_overview_request_uses_original_question_and_structured_plan(self, client):
        from app.rag.engine import rag_engine

        question = "关于足球的信息，帮我整理一下"
        prompt = rag_engine._build_rag_prompt(
            question,
            [_node("河海大学开展校园足球活动，并组织相关赛事。")],
            retrieval_question="足球",
        )

        assert question in prompt
        assert "概览/整理型问题" in prompt
        assert "综合归纳" in prompt
        assert "检索主题" in prompt
        assert "标题：校园足球资料" in prompt

    def test_prompt_removes_old_citations_and_limits_current_range(self, client):
        from llama_index.core.llms import ChatMessage, MessageRole
        from app.rag.engine import rag_engine

        prompt = rag_engine._build_rag_prompt(
            "继续介绍足球",
            [_node("足球队参加联赛。", title="足球资料")],
            history=[ChatMessage(role=MessageRole.ASSISTANT, content="旧回答引用了 [4][5]")],
        )

        assert "旧回答引用了 " in prompt
        assert "旧回答引用了 [4]" not in prompt
        assert "只能使用这些编号：[1]" in prompt

    def test_invalid_answer_citations_are_removed(self, client):
        from app.rag.engine import rag_engine

        sanitized = rag_engine._sanitize_answer(
            "有效事实 [1]，另一事实【2】，越界内容 [4][5]。",
            source_count=2,
        )

        assert "[1]" in sanitized
        assert "[2]" in sanitized
        assert "[4]" not in sanitized
        assert "[5]" not in sanitized


class TestContextCompressionSafety:
    def test_compression_does_not_mutate_index_nodes(self, client):
        from app.config import settings
        from app.rag.engine import rag_engine

        previous = settings.enable_context_compression
        object.__setattr__(settings, "enable_context_compression", True)
        original = (
            "校园足球课程面向学生开放。足球队每周开展训练。学校组织校园足球比赛。"
            "报名方式以当学期通知为准。训练安排会根据场地情况调整。"
        ) * 4
        nodes = [
            _node(original, title="足球资料"),
            _node(original.replace("足球", "篮球"), title="篮球资料"),
            _node(original.replace("足球", "排球"), title="排球资料"),
        ]

        try:
            compressed = rag_engine._compress_context("足球训练", nodes)
            assert nodes[0].get_content() == original
            assert compressed[0].get_content()
            assert compressed[0].node is not nodes[0].node
        finally:
            object.__setattr__(settings, "enable_context_compression", previous)
