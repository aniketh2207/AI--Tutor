"""Custom Textbook RAG Router: PDF Upload (`POST /api/rag/upload`) & Chapters (`GET /api/rag/chapters`)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.config import get_settings
from backend.app.database import get_session
from backend.app.models.curriculum import DocumentChunk, TextbookChapter
from backend.app.models.user import User
from backend.app.schemas.rag import (
    DocumentChunkSchema,
    RagUploadResponse,
    TextbookChapterResponse,
)
from backend.app.services.auth_service import get_current_user
from backend.app.services.gemini_router import GeminiRouter, get_gemini_router
from backend.app.services.rag_ingestion import ingest_pdf_chapter
from backend.app.services.rate_limit_service import enforce_upload_budget

router = APIRouter(prefix="/api/rag", tags=["Custom Textbook RAG"])


@router.post(
    "/upload",
    response_model=RagUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_textbook_pdf(
    file: UploadFile = File(...),
    title: str = Form(default="Custom Textbook Chapter"),
    target_concept: str | None = Form(default=None),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    gemini_router: GeminiRouter = Depends(get_gemini_router),
) -> RagUploadResponse:
    """Upload a PDF (<=15 pages / <=5MB), extract & chunk via PyMuPDF, and embed into 768-dim vectors."""
    assert current_user.id is not None
    await enforce_upload_budget(session, current_user.id)

    settings = get_settings()
    filename = file.filename or "chapter.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files (.pdf) are supported for textbook ingestion.",
        )

    pdf_bytes = await file.read()
    chapter, chunks = await ingest_pdf_chapter(
        session=session,
        pdf_bytes=pdf_bytes,
        filename=filename,
        title=title,
        user_id=current_user.id,
        target_concept=target_concept,
        router=gemini_router,
    )

    chapter_resp = TextbookChapterResponse(
        id=chapter.id or 0,
        title=chapter.title,
        filename=chapter.filename,
        page_count=chapter.page_count,
        target_concept=chapter.target_concept,
        chunk_count=len(chunks),
        created_at=chapter.created_at,
    )
    preview = [DocumentChunkSchema.model_validate(c) for c in chunks[:3]]

    return RagUploadResponse(
        chapter=chapter_resp,
        chunks_created=len(chunks),
        embedding_model=settings.gemini_embedding_model,
        embedding_dimensions=settings.gemini_embedding_dim,
        preview_chunks=preview,
    )


async def _require_owned_chapter(
    session: AsyncSession,
    current_user: User,
    chapter_id: int,
) -> TextbookChapter:
    """Return a chapter owned by the current user, or raise 404."""
    assert current_user.id is not None
    chapter = (
        await session.exec(
            select(TextbookChapter).where(
                TextbookChapter.id == chapter_id,
                TextbookChapter.user_id == current_user.id,
            )
        )
    ).first()
    if chapter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Textbook chapter not found.",
        )
    return chapter


@router.get("/chapters", response_model=list[TextbookChapterResponse])
async def list_textbook_chapters(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[TextbookChapterResponse]:
    """List textbook chapters owned by the authenticated student only."""
    assert current_user.id is not None
    stmt = select(TextbookChapter).where(TextbookChapter.user_id == current_user.id)
    result = await session.exec(stmt)
    chapters = list(result.all())

    responses: list[TextbookChapterResponse] = []
    for ch in chapters:
        chunk_stmt = select(DocumentChunk).where(DocumentChunk.chapter_id == ch.id)
        chunk_rows = list((await session.exec(chunk_stmt)).all())
        responses.append(
            TextbookChapterResponse(
                id=ch.id or 0,
                title=ch.title,
                filename=ch.filename,
                page_count=ch.page_count,
                target_concept=ch.target_concept,
                chunk_count=len(chunk_rows),
                created_at=ch.created_at,
            )
        )
    return responses


@router.get(
    "/chapters/{chapter_id}/chunks",
    response_model=list[DocumentChunkSchema],
)
async def get_chapter_chunks(
    chapter_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[DocumentChunkSchema]:
    """Retrieve chunks for a chapter owned by the authenticated student."""
    await _require_owned_chapter(session, current_user, chapter_id)
    stmt = (
        select(DocumentChunk)
        .where(DocumentChunk.chapter_id == chapter_id)
        .order_by(DocumentChunk.chunk_index)  # type: ignore[arg-type]
    )
    rows = list((await session.exec(stmt)).all())
    return [DocumentChunkSchema.model_validate(r) for r in rows]
