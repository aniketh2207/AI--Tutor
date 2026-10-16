"""SQLModel database models for Curriculum Problems, Textbooks, and RAG Chunks."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from sqlalchemy import Column, JSON, Text
from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    """Return timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class ProblemItem(SQLModel, table=True):
    """Seeded curriculum problem containing ground-truth symbolic verification rules."""

    __tablename__ = "problem_items"

    id: Optional[int] = Field(default=None, primary_key=True)
    slug: str = Field(index=True, unique=True, max_length=128)
    track: str = Field(index=True, max_length=16)  # "MATH", "CODE", or "RAG"
    title: str = Field(max_length=255)
    prompt: str = Field(sa_column=Column(Text, nullable=False))
    difficulty: str = Field(default="INTERMEDIATE", max_length=32)
    symbolic_rules_json: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    created_at: datetime = Field(default_factory=utc_now)


class TextbookChapter(SQLModel, table=True):
    """Uploaded custom PDF textbook chapter for Track 3 (Grounded RAG)."""

    __tablename__ = "textbook_chapters"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    title: str = Field(max_length=255)
    filename: str = Field(max_length=255)
    page_count: int = Field(default=1)
    target_concept: Optional[str] = Field(default=None, max_length=512)
    created_at: datetime = Field(default_factory=utc_now)


class DocumentChunk(SQLModel, table=True):
    """600-char text chunk extracted from a PDF with its 768-dim Gemini embedding."""

    __tablename__ = "document_chunks"

    id: Optional[int] = Field(default=None, primary_key=True)
    chapter_id: int = Field(foreign_key="textbook_chapters.id", index=True)
    chunk_index: int = Field(default=0)
    page_number: int = Field(default=1)
    content: str = Field(sa_column=Column(Text, nullable=False))
    embedding_json: list[float] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    created_at: datetime = Field(default_factory=utc_now)
