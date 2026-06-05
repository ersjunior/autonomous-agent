"""Pydantic schemas for knowledge base documents."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

KBSourceTypeLiteral = Literal["UPLOAD", "MANUAL"]
KBDocumentStatusLiteral = Literal["PROCESSING", "READY", "ERROR"]


class KBManualCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)


class KBDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    title: str
    source_type: str
    filename: str | None
    mime_type: str | None
    status: str
    error_message: str | None
    is_system: bool
    chunk_count: int
    total_chunks_estimated: int = 0
    chunks_processed: int = 0
    created_at: datetime
