"""Deterministic orchestration: SQL snapshot -> one model call -> citation validation."""

import uuid

import psycopg

from reviewops.ai.kimi import InvestigationError, KimiClient
from reviewops.analytics import analytics_session
from reviewops.analytics_contracts import ReviewSearch, Scope
from reviewops.contracts import (
    EvidenceCoverage,
    Finding,
    InvestigationPreview,
    InvestigationResponse,
    ReviewSource,
)


def prepare(request, settings):
    configured = settings.database_url
    if not configured or not configured.get_secret_value():
        raise InvestigationError("database_not_configured", "Set DATABASE_URL locally.", 503)
    scope = Scope(**request.model_dump(exclude={"question"}))
    try:
        with analytics_session(configured.get_secret_value()) as service:
            metrics = service.summary(scope)
            evidence = service.search(ReviewSearch(**scope.model_dump(), limit=20))
    except psycopg.Error:
        raise InvestigationError(
            "database_unavailable", "Review database is unavailable.", 503
        ) from None
    # The SQL connection closes before waiting on the model.
    coverage = EvidenceCoverage(
        eligible_negative_text_reviews=evidence.matched_reviews,
        selected_reviews=len(evidence.reviews),
        all_eligible_reviews_selected=len(evidence.reviews) == evidence.matched_reviews,
        truncated_excerpts=sum(review.excerpt_truncated for review in evidence.reviews),
    )
    return InvestigationPreview(
        request=request, metrics=metrics, evidence=evidence, coverage=coverage
    )


def model_input(preview):
    return {
        "question": preview.request.question,
        "scope": preview.metrics.scope.model_dump(mode="json"),
        "coverage": preview.coverage.model_dump(),
        "evidence": [review.model_dump(mode="json") for review in preview.evidence.reviews],
    }


def validate_evidence(draft, evidence):
    excerpts = {review.review_id: review.excerpt for review in evidence.reviews}
    ids = [item.complaint_id for item in draft.reported_complaints]
    if len(ids) != len(set(ids)):
        raise InvestigationError("invalid_citations", "Kimi returned duplicate complaint IDs.")
    for complaint in draft.reported_complaints:
        for citation in complaint.citations:
            if (
                citation.review_id not in excerpts
                or citation.quote not in excerpts[citation.review_id]
            ):
                raise InvestigationError(
                    "invalid_citations", "Kimi cited an unknown review or a non-verbatim quote."
                )
    for item in [*draft.suggested_explanations, *draft.recommended_actions]:
        if not set(item.complaint_ids).issubset(ids):
            raise InvestigationError("invalid_citations", "Kimi referenced an unknown complaint.")


def investigate(request, settings, model=None, preview=None):
    preview = preview if preview is not None else prepare(request, settings)
    limitations = [
        *preview.metrics.limitations,
        *preview.evidence.limitations,
        "Findings describe selected negative-review excerpts, not all customers or all complaints.",
        "Suggested explanations are unproven hypotheses; actions have not been executed.",
        "Citation checks verify IDs and quotes, not whether the interpretation is true.",
        "No complaint prevalence, causal attribution or change in complaint themes is established.",
        "Numeric metrics are calculated by SQL; narrative findings still require human review.",
    ]
    if not preview.coverage.all_eligible_reviews_selected:
        limitations.append(
            "Only the newest eligible reviews were selected; older complaints may differ."
        )
    if preview.coverage.truncated_excerpts:
        limitations.append(
            "Some excerpts were truncated; omitted context can change their meaning."
        )
    findings, explanations, actions = [], [], []
    model_run = None
    if preview.evidence.reviews:
        completion = (model or KimiClient(settings)).analyse(model_input(preview))
        validate_evidence(completion.draft, preview.evidence)
        model_run = completion.run
        findings = [
            Finding(
                complaint_id=item.complaint_id,
                statement=item.statement,
                source_ids=list(dict.fromkeys(c.review_id for c in item.citations)),
                citations=item.citations,
            )
            for item in completion.draft.reported_complaints
        ]
        explanations = completion.draft.suggested_explanations
        actions = completion.draft.recommended_actions
    if not findings:
        limitations.append(
            "Insufficient supported complaint evidence; no investigation priority established."
        )
    return InvestigationResponse(
        investigation_id=uuid.uuid4().hex,
        status="completed" if findings else "insufficient_evidence",
        findings=findings,
        suggested_explanations=explanations,
        recommended_actions=actions,
        sources=[ReviewSource(**review.model_dump()) for review in preview.evidence.reviews],
        metrics=preview.metrics,
        coverage=preview.coverage,
        model_run=model_run,
        limitations=limitations,
    )
