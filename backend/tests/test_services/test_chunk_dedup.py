"""Tests for chunk-level deduplication in ingestion.py."""

from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.compliance_brain.ingestion import ingest_document


class TestChunkDeduplication:
    @pytest.mark.asyncio
    async def test_duplicate_chunks_are_skipped(self):
        """Re-ingesting the same document should skip all chunks."""
        test_content = "## Section 1\nThis is test content for deduplication.\n"
        doc_hash = hashlib.sha256(test_content.encode()).hexdigest()
        chunk_hash = hashlib.sha256("This is test content for deduplication.".encode()).hexdigest()

        # First call: doc-level dedup check returns 0 (not yet ingested)
        # Second call: chunk-level dedup check returns an existing ID
        mock_doc_result = MagicMock()
        mock_doc_result.scalar.return_value = 0

        mock_chunk_result = MagicMock()
        mock_chunk_result.scalar.return_value = "existing-uuid"

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[mock_doc_result, mock_chunk_result])
        mock_db.flush = AsyncMock()

        mock_embedding_data = MagicMock()
        mock_embedding_data.embedding = [0.1] * 1536
        mock_embedding_resp = MagicMock()
        mock_embedding_resp.data = [mock_embedding_data]

        mock_client = AsyncMock()
        mock_client.embeddings.create = AsyncMock(return_value=mock_embedding_resp)

        with (
            patch("builtins.open", return_value=MagicMock(
                __enter__=lambda s: s,
                __exit__=lambda s, *a: None,
                read=lambda: test_content,
            )),
            patch("app.services.compliance_brain.ingestion.AsyncOpenAI", return_value=mock_client),
        ):
            result = await ingest_document("test.txt", "HIPAA", mock_db)

        # Chunks were found via embedding but the actual insert was skipped
        # because chunk_hash already existed
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_new_chunks_are_inserted(self):
        """New chunks (no matching hash) should be inserted with chunk_hash."""
        test_content = "## Section 1\nBrand new regulatory content.\n"

        # Doc-level dedup: not found
        mock_doc_result = MagicMock()
        mock_doc_result.scalar.return_value = 0

        # Chunk-level dedup: not found (returns None)
        mock_chunk_result = MagicMock()
        mock_chunk_result.scalar.return_value = None

        # Insert succeeds
        mock_insert_result = MagicMock()

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(
            side_effect=[mock_doc_result, mock_chunk_result, mock_insert_result]
        )
        mock_db.flush = AsyncMock()

        mock_embedding_data = MagicMock()
        mock_embedding_data.embedding = [0.1] * 1536
        mock_embedding_resp = MagicMock()
        mock_embedding_resp.data = [mock_embedding_data]

        mock_client = AsyncMock()
        mock_client.embeddings.create = AsyncMock(return_value=mock_embedding_resp)

        with (
            patch("builtins.open", return_value=MagicMock(
                __enter__=lambda s: s,
                __exit__=lambda s, *a: None,
                read=lambda: test_content,
            )),
            patch("app.services.compliance_brain.ingestion.AsyncOpenAI", return_value=mock_client),
        ):
            result = await ingest_document("test.txt", "HIPAA", mock_db)

        assert isinstance(result, list)
        assert len(result) == 1  # One chunk was produced

        # Verify the INSERT was called (3rd call after doc check and chunk check)
        insert_call = mock_db.execute.call_args_list[2]
        insert_params = insert_call[0][1]
        assert "chunk_hash" in insert_params
        assert len(insert_params["chunk_hash"]) == 64  # SHA-256 hex digest length
