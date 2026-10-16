"""Pydantic v2 schemas for Custom Textbook PDF RAG ingestion and retrieval."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict


class DocumentChunkSchema(BaseModel):
    """Public metadata and text for a retrieved textbook document chunk."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    chapter_id: int
    chunk_index: int
    page_number: int
    content: str
    similarity: Optional[float] = None


class TextbookChapterResponse(BaseModel):
    """Uploaded textbook chapter metadata."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    filename: str
    page_count: int
    target_concept: Optional[str] = None
    chunk_count: int = 0
    created_at: datetime


class RagUploadResponse(BaseModel):
    """Response returned after parsing, chunking, and embedding a textbook PDF."""

    chapter: TextbookChapterResponse
    chunks_created: int
    embedding_model: str
    embedding_dimensions: int
    preview_chunks: List[DocumentChunkSchema]
