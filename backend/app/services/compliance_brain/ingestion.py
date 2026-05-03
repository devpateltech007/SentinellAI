"""Document ingestion pipeline for the Compliance Brain.

Accepts plaintext regulatory documents, splits them into overlapping
chunks, generates vector embeddings via the OpenAI API, and stores the
results in pgvector for RAG retrieval.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from openai import AsyncOpenAI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536


@dataclass
class DocumentChunk:
    text: str
    source_section: str
    chunk_index: int
    embedding: list[float] | None = None


async def ingest_document(
    file_path: str,
    framework_name: str,
    db: AsyncSession,
    chunk_size: int = 512,
    chunk_overlap: int = 50,
) -> list[DocumentChunk]:
    """Read a regulatory document, chunk it, embed it, and store in pgvector."""
    with open(file_path) as f:
        content = f.read()

    doc_hash = hashlib.sha256(content.encode()).hexdigest()

    existing = await db.execute(
        text(
            "SELECT COUNT(*) FROM regulatory_chunks "
            "WHERE framework_name = :name AND doc_hash = :hash"
        ),
        {"name": framework_name, "hash": doc_hash},
    )
    val = existing.scalar()
    if val and val > 0:
        logger.info("Document already ingested for %s (hash=%s)", framework_name, doc_hash[:12])
        return []

    sections = _split_by_sections(content)
    chunks: list[DocumentChunk] = []
    idx = 0
    for section_title, section_text in sections:
        words = section_text.split()
        start = 0
        while start < len(words):
            end = start + chunk_size
            chunk_text = " ".join(words[start:end])
            if chunk_text.strip():
                chunks.append(
                    DocumentChunk(
                        text=chunk_text,
                        source_section=section_title,
                        chunk_index=idx,
                    )
                )
                idx += 1
            start += chunk_size - chunk_overlap

    if not chunks:
        return chunks

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    batch_size = 20
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        texts = [c.text for c in batch]
        resp = await client.embeddings.create(input=texts, model=EMBEDDING_MODEL)
        for j, item in enumerate(resp.data):
            batch[j].embedding = item.embedding

    for chunk in chunks:
        chunk_id = uuid.uuid4()
        if chunk.embedding is None:
            logger.error(
                "Missing embedding for framework=%s chunk_index=%d; refusing to insert chunk",
                framework_name,
                chunk.chunk_index,
            )
            raise ValueError(
                f"Missing embedding for framework={framework_name} chunk_index={chunk.chunk_index}"
            )
        if len(chunk.embedding) != EMBEDDING_DIM:
            logger.error(
                "Invalid embedding dimension for framework=%s chunk_index=%d: expected %d, got %d",
                framework_name,
                chunk.chunk_index,
                EMBEDDING_DIM,
                len(chunk.embedding),
            )
            raise ValueError(
                f"Invalid embedding dimension for framework={framework_name} "
                f"chunk_index={chunk.chunk_index}: expected {EMBEDDING_DIM}, got {len(chunk.embedding)}"
            )
        embedding_str = "[" + ",".join(str(v) for v in chunk.embedding) + "]"
        await db.execute(
            text(
                "INSERT INTO regulatory_chunks "
                "(id, framework_name, chunk_text, source_section, chunk_index, doc_hash, created_at, embedding) "
                "VALUES (:id, :name, :text, :section, :idx, :hash, :created, CAST(:emb AS vector))"
            ),
            {
                "id": chunk_id,
                "name": framework_name,
                "text": chunk.text,
                "section": chunk.source_section,
                "idx": chunk.chunk_index,
                "hash": doc_hash,
                "created": datetime.now(timezone.utc),
                "emb": embedding_str,
            },
        )

    await db.flush()
    logger.info("Ingested %d chunks for %s", len(chunks), framework_name)
    return chunks


def _split_by_sections(text: str) -> list[tuple[str, str]]:
    """Split document text into (section_title, section_body) pairs."""
    sections: list[tuple[str, str]] = []
    current_title = "Preamble"
    current_lines: list[str] = []

    for line in text.split("\n"):
        if line.startswith("## "):
            if current_lines:
                sections.append((current_title, "\n".join(current_lines)))
            current_title = line.lstrip("# ").strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        sections.append((current_title, "\n".join(current_lines)))

    return sections


def compute_doc_hash(file_path: str) -> str:
    with open(file_path) as f:
        return hashlib.sha256(f.read().encode()).hexdigest()
