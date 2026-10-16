"""Track 3 Textbook PDF Ingestion, Chunking, Embedding, and Vector Retrieval Service."""

from __future__ import annotations

import asyncio
import math
from typing import Any
from fastapi import HTTPException, status
import pymupdf as fitz
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.config import get_settings
from backend.app.models.curriculum import DocumentChunk, TextbookChapter
from backend.app.services.gemini_router import GeminiRouter, get_gemini_router


def extract_pages_from_pdf(
    pdf_bytes: bytes,
    max_pages: int | None = None,
    max_bytes: int | None = None,
) -> list[tuple[int, str]]:
    """Validate PDF size/page limits and extract text per page via PyMuPDF."""
    settings = get_settings()
    allowed_bytes = max_bytes or settings.rag_max_pdf_bytes
    allowed_pages = max_pages or settings.rag_max_pdf_pages

    if not pdf_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded PDF file is empty.",
        )

    if len(pdf_bytes) > allowed_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"PDF file exceeds maximum size of {allowed_bytes} bytes (5MB).",
        )

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to parse PDF document: {exc}",
        ) from exc

    try:
        if doc.page_count < 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="PDF document contains zero pages.",
            )
        if doc.page_count > allowed_pages:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"PDF has {doc.page_count} pages, exceeding the limit of "
                    f"{allowed_pages} pages."
                ),
            )

        extracted: list[tuple[int, str]] = []
        for idx in range(doc.page_count):
            page = doc[idx]
            text = " ".join(page.get_text("text").split())
            if text:
                extracted.append((idx + 1, text))
    finally:
        doc.close()

    if not extracted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No extractable text found in the uploaded PDF.",
        )

    return extracted


def chunk_page_texts(
    pages: list[tuple[int, str]],
    chunk_size: int = 600,
    overlap: int = 100,
) -> list[dict[str, Any]]:
    """Split page text into 600-character chunks with 100-character overlap."""
    step = max(1, chunk_size - overlap)
    chunks: list[dict[str, Any]] = []
    chunk_idx = 0

    for page_num, text in pages:
        cleaned = text.strip()
        if not cleaned:
            continue

        if len(cleaned) <= chunk_size:
            chunks.append(
                {
                    "chunk_index": chunk_idx,
                    "page_number": page_num,
                    "content": cleaned,
                }
            )
            chunk_idx += 1
            continue

        start = 0
        while start < len(cleaned):
            segment = cleaned[start : start + chunk_size].strip()
            if segment:
                chunks.append(
                    {
                        "chunk_index": chunk_idx,
                        "page_number": page_num,
                        "content": segment,
                    }
                )
                chunk_idx += 1
            if start + chunk_size >= len(cleaned):
                break
            start += step

    return chunks


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two equal-dimension vectors."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot_prod = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(dot_prod / (norm_a * norm_b))


async def ingest_pdf_chapter(
    session: AsyncSession,
    pdf_bytes: bytes,
    filename: str,
    title: str,
    user_id: int | None = None,
    target_concept: str | None = None,
    router: GeminiRouter | None = None,
) -> tuple[TextbookChapter, list[DocumentChunk]]:
    """Parse PDF, chunk into 600-char segments, embed via gemini-embedding-001, and persist."""
    active_router = router or get_gemini_router()
    pages = await asyncio.to_thread(extract_pages_from_pdf, pdf_bytes)
    raw_chunks = chunk_page_texts(pages, chunk_size=600, overlap=100)

    texts_to_embed = [c["content"] for c in raw_chunks]
    embeddings = await asyncio.to_thread(active_router.embed_texts, texts_to_embed)

    chapter = TextbookChapter(
        user_id=user_id,
        title=title.strip() or filename,
        filename=filename,
        page_count=len(pages),
        target_concept=target_concept,
    )
    session.add(chapter)
    await session.commit()
    await session.refresh(chapter)
    assert chapter.id is not None

    persisted_chunks: list[DocumentChunk] = []
    for idx, chunk_meta in enumerate(raw_chunks):
        vector = (
            embeddings[idx]
            if idx < len(embeddings)
            else [0.0] * active_router.embedding_dim
        )
        chunk_row = DocumentChunk(
            chapter_id=chapter.id,
            chunk_index=chunk_meta["chunk_index"],
            page_number=chunk_meta["page_number"],
            content=chunk_meta["content"],
            embedding_json=vector,
        )
        session.add(chunk_row)
        persisted_chunks.append(chunk_row)

    await session.commit()
    for row in persisted_chunks:
        await session.refresh(row)

    return chapter, persisted_chunks


async def retrieve_top_k_chunks(
    session: AsyncSession,
    chapter_id: int,
    query_text: str,
    top_k: int = 3,
    router: GeminiRouter | None = None,
) -> list[dict[str, Any]]:
    """Retrieve Top-K chunks ranked by 768-dim cosine similarity."""
    active_router = router or get_gemini_router()
    result = await session.exec(
        select(DocumentChunk).where(DocumentChunk.chapter_id == chapter_id)
    )
    chunks = list(result.all())
    if not chunks:
        return []

    query_vecs = await asyncio.to_thread(active_router.embed_texts, [query_text])
    query_vec = query_vecs[0] if query_vecs else []

    scored: list[dict[str, Any]] = []
    for chunk in chunks:
        sim = cosine_similarity(query_vec, chunk.embedding_json)
        scored.append(
            {
                "id": chunk.id,
                "chapter_id": chunk.chapter_id,
                "chunk_index": chunk.chunk_index,
                "page_number": chunk.page_number,
                "content": chunk.content,
                "similarity": round(sim, 4),
            }
        )

    scored.sort(key=lambda item: item["similarity"], reverse=True)
    return scored[:top_k]
