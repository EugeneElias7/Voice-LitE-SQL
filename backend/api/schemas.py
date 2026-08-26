"""Voice-LitE-SQL -- Level 11: API request/response models."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, description="Natural-language question")
    category: Optional[str] = Field("", description="Optional intent category hint")


class HealthResponse(BaseModel):
    status: str
    service: str
    database: str


class StatusComponent(BaseModel):
    state: str  # ready | offline | not_built
    detail: Optional[str] = None


class StatusResponse(BaseModel):
    backend: StatusComponent
    database: StatusComponent
    ollama: StatusComponent
    model: StatusComponent
    whisper: StatusComponent
    chroma: StatusComponent
    schema: StatusComponent