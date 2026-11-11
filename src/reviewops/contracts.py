"""HTTP boundary for bounded, evidence-grounded complaint investigations."""

from typing import Literal

from pydantic import BaseModel, Field

from reviewops.ai.models import Action, Citation, Explanation, ModelRun
from reviewops.analytics_contracts import EvidenceResults, Scope, Summary


class InvestigationRequest(Scope):
    question: str = Field(min_length=1, max_length=2000)


class ReviewSource(BaseModel):
    review_id: str
    product_id: str
    excerpt: str
    dataset_version: str


class Finding(BaseModel):
    complaint_id: str
    statement: str
    source_ids: list[str] = Field(min_length=1)
    citations: list[Citation] = Field(min_length=1)


class EvidenceCoverage(BaseModel):
    eligible_negative_text_reviews: int
    selected_reviews: int
    selection_limit: int = 20
    all_eligible_reviews_selected: bool
    truncated_excerpts: int


class InvestigationPreview(BaseModel):
    request: InvestigationRequest
    metrics: Summary
    evidence: EvidenceResults
    coverage: EvidenceCoverage


class InvestigationResponse(BaseModel):
    investigation_id: str
    status: Literal["completed", "insufficient_evidence"]
    findings: list[Finding]
    suggested_explanations: list[Explanation]
    recommended_actions: list[Action]
    sources: list[ReviewSource]
    metrics: Summary
    coverage: EvidenceCoverage
    model_run: ModelRun | None
    limitations: list[str]
