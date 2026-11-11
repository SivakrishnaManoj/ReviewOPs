"""Strict model output, distinct from server-calculated metrics."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Citation(StrictModel):
    review_id: str = Field(min_length=1, max_length=128)
    quote: str = Field(min_length=8, max_length=300)


class Complaint(StrictModel):
    complaint_id: str = Field(pattern=r"^c[1-5]$")
    statement: str = Field(min_length=1, max_length=600)
    citations: list[Citation] = Field(min_length=1, max_length=5)


class Explanation(StrictModel):
    statement: str = Field(min_length=1, max_length=600)
    complaint_ids: list[str] = Field(min_length=1, max_length=5)


class Action(Explanation):
    rationale: str = Field(min_length=1, max_length=600)


class Draft(StrictModel):
    reported_complaints: list[Complaint] = Field(max_length=5)
    suggested_explanations: list[Explanation] = Field(max_length=5)
    recommended_actions: list[Action] = Field(max_length=5)


class ModelUsage(StrictModel):
    prompt_tokens: Annotated[int, Field(strict=True, ge=0)] | None = None
    completion_tokens: Annotated[int, Field(strict=True, ge=0)] | None = None
    total_tokens: Annotated[int, Field(strict=True, ge=0)] | None = None


class ModelRun(BaseModel):
    provider: Literal["moonshot"] = "moonshot"
    model: str
    prompt_version: str
    latency_ms: int
    usage: ModelUsage
    calls: Literal[1] = 1
