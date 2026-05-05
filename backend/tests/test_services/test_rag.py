"""Tests for the RAG pipeline: keyword search, hybrid search, and reranking.

All external dependencies (OpenAI API, database) are mocked.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.compliance_brain.rag import (
    RetrievedChunk,
    hybrid_retrieve,
    keyword_search,
    rerank_by_score,
    rerank_with_llm,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_chunk(text: str, section: str = "Test Section", score: float = 0.5) -> RetrievedChunk:
    return RetrievedChunk(text=text, source_section=section, similarity_score=score)


# ---------------------------------------------------------------------------
# rerank_by_score (fallback reranker)
# ---------------------------------------------------------------------------

class TestRerankByScore:
    def test_returns_top_n_by_score(self):
        chunks = [
            _make_chunk("low", score=0.1),
            _make_chunk("high", score=0.9),
            _make_chunk("mid", score=0.5),
        ]
        result = rerank_by_score("query", chunks, top_n=2)
        assert len(result) == 2
        assert result[0].text == "high"
        assert result[1].text == "mid"

    def test_returns_all_when_fewer_than_top_n(self):
        chunks = [_make_chunk("only", score=0.8)]
        result = rerank_by_score("query", chunks, top_n=5)
        assert len(result) == 1

    def test_preserves_chunk_data(self):
        chunk = _make_chunk("text", section="§164.312", score=0.7)
        result = rerank_by_score("query", [chunk], top_n=1)
        assert result[0].source_section == "§164.312"
        assert result[0].similarity_score == 0.7


# ---------------------------------------------------------------------------
# keyword_search
# ---------------------------------------------------------------------------

class TestKeywordSearch:
    @pytest.mark.asyncio
    async def test_returns_chunks_from_db(self):
        mock_row = MagicMock()
        mock_row.chunk_text = "encryption at rest requirement"
        mock_row.source_section = "§164.312(a)"
        mock_row.score = 0.85

        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([mock_row])

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await keyword_search("encryption ePHI", "HIPAA", mock_db, top_k=5)
        assert len(result) == 1
        assert result[0].text == "encryption at rest requirement"
        assert result[0].source_section == "§164.312(a)"
        assert result[0].similarity_score == 0.85

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_match(self):
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([])

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await keyword_search("nonexistent term xyz", "HIPAA", mock_db, top_k=5)
        assert result == []


# ---------------------------------------------------------------------------
# hybrid_retrieve (RRF fusion)
# ---------------------------------------------------------------------------

class TestHybridRetrieve:
    @pytest.mark.asyncio
    async def test_chunks_in_both_methods_rank_highest(self):
        shared_chunk = _make_chunk("shared chunk about encryption", score=0.8)
        semantic_only = _make_chunk("semantic only chunk", score=0.9)
        keyword_only = _make_chunk("keyword only chunk", score=0.7)

        with patch(
            "app.services.compliance_brain.rag.retrieve_context",
            new_callable=AsyncMock,
            return_value=[shared_chunk, semantic_only],
        ), patch(
            "app.services.compliance_brain.rag.keyword_search",
            new_callable=AsyncMock,
            return_value=[shared_chunk, keyword_only],
        ):
            mock_db = AsyncMock()
            result = await hybrid_retrieve("encryption", "HIPAA", mock_db, top_k=3)

            assert len(result) == 3
            # Shared chunk should be ranked first (gets RRF score from both sources)
            assert result[0].text == "shared chunk about encryption"

    @pytest.mark.asyncio
    async def test_respects_top_k_limit(self):
        chunks = [_make_chunk(f"chunk_{i}", score=0.5) for i in range(10)]

        with patch(
            "app.services.compliance_brain.rag.retrieve_context",
            new_callable=AsyncMock,
            return_value=chunks[:5],
        ), patch(
            "app.services.compliance_brain.rag.keyword_search",
            new_callable=AsyncMock,
            return_value=chunks[5:],
        ):
            mock_db = AsyncMock()
            result = await hybrid_retrieve("test", "HIPAA", mock_db, top_k=3)
            assert len(result) == 3

    @pytest.mark.asyncio
    async def test_handles_empty_keyword_results(self):
        semantic_chunks = [_make_chunk("semantic result", score=0.8)]

        with patch(
            "app.services.compliance_brain.rag.retrieve_context",
            new_callable=AsyncMock,
            return_value=semantic_chunks,
        ), patch(
            "app.services.compliance_brain.rag.keyword_search",
            new_callable=AsyncMock,
            return_value=[],
        ):
            mock_db = AsyncMock()
            result = await hybrid_retrieve("test", "HIPAA", mock_db, top_k=5)
            assert len(result) == 1
            assert result[0].text == "semantic result"


# ---------------------------------------------------------------------------
# rerank_with_llm (cross-encoder)
# ---------------------------------------------------------------------------

class TestRerankWithLLM:
    @pytest.mark.asyncio
    async def test_returns_chunks_sorted_by_llm_score(self):
        chunks = [
            _make_chunk("irrelevant preamble", score=0.3),
            _make_chunk("highly relevant access control", score=0.5),
            _make_chunk("somewhat relevant encryption", score=0.4),
        ]

        # Mock OpenAI to return scores: 2, 9, 6
        mock_responses = []
        for score in [2, 9, 6]:
            mock_choice = MagicMock()
            mock_choice.message.content = str(score)
            mock_resp = MagicMock()
            mock_resp.choices = [mock_choice]
            mock_responses.append(mock_resp)

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=mock_responses)

        with patch("app.services.compliance_brain.rag.AsyncOpenAI", return_value=mock_client):
            result = await rerank_with_llm("access control", chunks, top_n=2)

        assert len(result) == 2
        assert result[0].text == "highly relevant access control"
        assert result[1].text == "somewhat relevant encryption"

    @pytest.mark.asyncio
    async def test_returns_all_when_fewer_than_top_n(self):
        chunks = [_make_chunk("only chunk", score=0.5)]
        result = await rerank_with_llm("test", chunks, top_n=5)
        assert len(result) == 1
        assert result[0].text == "only chunk"

    @pytest.mark.asyncio
    async def test_handles_api_failure_gracefully(self):
        chunks = [
            _make_chunk("chunk_a", score=0.5),
            _make_chunk("chunk_b", score=0.5),
            _make_chunk("chunk_c", score=0.5),
        ]

        # Mock OpenAI to raise an exception for all calls
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=Exception("API rate limit exceeded")
        )

        with patch("app.services.compliance_brain.rag.AsyncOpenAI", return_value=mock_client):
            result = await rerank_with_llm("test", chunks, top_n=2)

        # Should not crash — all chunks get default score 5
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_clamps_scores_to_1_10_range(self):
        chunks = [
            _make_chunk("chunk_a", score=0.5),
            _make_chunk("chunk_b", score=0.5),
        ]

        # Mock OpenAI to return out-of-range scores
        mock_responses = []
        for score_str in ["15", "0"]:
            mock_choice = MagicMock()
            mock_choice.message.content = score_str
            mock_resp = MagicMock()
            mock_resp.choices = [mock_choice]
            mock_responses.append(mock_resp)

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=mock_responses)

        with patch("app.services.compliance_brain.rag.AsyncOpenAI", return_value=mock_client):
            result = await rerank_with_llm("test", chunks, top_n=2)

        # Score 15 clamped to 10, score 0 clamped to 1 — chunk_a (10) ranks first
        assert result[0].text == "chunk_a"
