"""Export all SQLModel tables for metadata registration and migrations."""

from backend.app.models.curriculum import DocumentChunk, ProblemItem, TextbookChapter
from backend.app.models.rate_limit import RateLimitBucket
from backend.app.models.session import SocraticTurnLog, TutorSession
from backend.app.models.user import SubjectEnrollment, User

__all__ = [
    "User",
    "SubjectEnrollment",
    "ProblemItem",
    "TextbookChapter",
    "DocumentChunk",
    "TutorSession",
    "SocraticTurnLog",
    "RateLimitBucket",
]
