"""HTTP boundaries for the same bounded SQL tools used by the CLI."""

from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException

from reviewops.analytics import Analytics, analytics_session
from reviewops.analytics_contracts import (
    Comparison,
    ComparisonRequest,
    EvidenceResults,
    MonthlyReport,
    ReviewSearch,
    Scope,
    Summary,
)
from reviewops.config import get_settings

router = APIRouter(prefix="/api/v1", tags=["review analysis"])


def get_analytics():
    configured = get_settings().database_url
    if not configured or not configured.get_secret_value():
        raise HTTPException(status_code=503, detail="Analytics database is not configured")
    try:
        with analytics_session(configured.get_secret_value()) as service:
            yield service
    except psycopg.Error:
        raise HTTPException(status_code=503, detail="Analytics database is unavailable") from None


Service = Annotated[Analytics, Depends(get_analytics)]


@router.post("/analytics/summary", response_model=Summary)
def summary(request: Scope, service: Service):
    return service.summary(request)


@router.post("/analytics/compare", response_model=Comparison)
def compare(request: ComparisonRequest, service: Service):
    return service.compare(request)


@router.post("/analytics/monthly", response_model=MonthlyReport)
def monthly(request: Scope, service: Service):
    return service.monthly(request)


@router.post("/reviews/search", response_model=EvidenceResults)
def search(request: ReviewSearch, service: Service):
    return service.search(request)
