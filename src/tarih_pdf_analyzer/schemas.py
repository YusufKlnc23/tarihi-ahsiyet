from __future__ import annotations

from typing import Literal

try:
    from pydantic import BaseModel, Field  # type: ignore[import]
except ImportError:
    raise ImportError("pydantic is required. Install it with: pip install pydantic")


class BookMetadataGuess(BaseModel):
    title: str = Field(min_length=1)
    author: str = Field(min_length=1)
    year: int | None = Field(default=None, ge=0, le=2200)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)


class ManualChunkSpec(BaseModel):
    file: str = Field(min_length=1)
    start_page: int | None = Field(default=None, ge=1)
    end_page: int | None = Field(default=None, ge=1)
    pages: str | int | list[int] | None = None


class ManualBookManifest(BaseModel):
    title: str = Field(min_length=1)
    author: str = Field(min_length=1)
    year: int | None = Field(default=None, ge=0, le=2200)
    chunks: list[ManualChunkSpec] = Field(default_factory=list)


class FigureSeed(BaseModel):
    name: str = Field(min_length=1)
    slug: str | None = None
    aliases: list[str] = Field(default_factory=list)
    period: str | None = None
    short_bio: str = ""


class FigureManifest(BaseModel):
    figures: list[FigureSeed] = Field(default_factory=list)


class Citation(BaseModel):
    book_title: str
    author: str
    chunk_id: int
    chunk_index: int
    pages: str


class RetrievedChunk(BaseModel):
    chunk_id: int
    book_id: int
    book_title: str
    author: str
    chunk_index: int
    start_page: int
    end_page: int
    text: str
    score: float = 0.0
    chunk_type: str = "source"


class ChatAnswer(BaseModel):
    answer: str
    citations: list[Citation] = Field(default_factory=list)


class TopicMention(BaseModel):
    name: str = Field(min_length=1)
    importance: float = Field(ge=0.0, le=1.0)
    pages: list[int] = Field(default_factory=list)
    rationale: str = ""


class ChunkAnalysis(BaseModel):
    summary: str = Field(min_length=1)
    arguments: list[str] = Field(default_factory=list)
    people: list[str] = Field(default_factory=list)
    events: list[str] = Field(default_factory=list)
    periods: list[str] = Field(default_factory=list)
    concepts: list[str] = Field(default_factory=list)
    topics: list[TopicMention] = Field(default_factory=list)


class BookTopic(BaseModel):
    name: str = Field(min_length=1)
    weight: float = Field(ge=0.0, le=100.0)
    rationale: str = Field(min_length=1)
    representative_pages: list[int] = Field(default_factory=list)


class BookReport(BaseModel):
    detailed_summary: str = Field(min_length=1)
    main_theses: list[str] = Field(default_factory=list)
    debate_map: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    topics: list[BookTopic] = Field(default_factory=list)


JudgeAction = Literal["keep", "merge", "revise", "reject", "review"]


class DebateTopicCandidate(BaseModel):
    topic_title: str = Field(min_length=1)
    claim: str = Field(min_length=1)
    people: list[str] = Field(default_factory=list)
    events: list[str] = Field(default_factory=list)
    periods: list[str] = Field(default_factory=list)
    evidence: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)


class DebateTopicJudgement(BaseModel):
    approved: bool = False
    relevance_score: float = Field(ge=0.0, le=100.0)
    evidence_score: float = Field(ge=0.0, le=100.0)
    hallucination_risk: float = Field(ge=0.0, le=100.0)
    debate_value: float = Field(ge=0.0, le=100.0)
    action: JudgeAction = "review"
    reason: str = ""


class JudgedDebateTopic(BaseModel):
    candidate: DebateTopicCandidate
    judgement: DebateTopicJudgement


class DebateJudgeResponse(BaseModel):
    topics: list[JudgedDebateTopic] = Field(default_factory=list)
