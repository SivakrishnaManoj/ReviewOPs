"""Shared API contracts. Change these with both application owners' review."""

from datetime import date
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class InvestigationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(min_length=1, max_length=2000)
    product_ids: list[str] = Field(min_length=1, max_length=10)
    date_from: date
    date_to: date

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        if self.date_from > self.date_to:
            raise ValueError("date_from must be on or before date_to")
        if any(not item.strip() or len(item) > 64 for item in self.product_ids):
            raise ValueError("product_ids must be non-empty and at most 64 characters")
        if len(set(self.product_ids)) != len(self.product_ids):
            raise ValueError("product_ids must be unique")
        return self


class ReviewSource(BaseModel):
    review_id: str
    product_id: str
    excerpt: str
    dataset_version: str


class Finding(BaseModel):
    statement: str
    source_ids: list[str] = Field(min_length=1)


class InvestigationResponse(BaseModel):
    investigation_id: str
    findings: list[Finding]
    sources: list[ReviewSource]
    limitations: list[str]
