import asyncio
import json
import logging
import secrets
import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from reviewops.ai.investigate import investigate as run_investigation
from reviewops.ai.kimi import InvestigationError
from reviewops.analytics_routes import router as analytics_router
from reviewops.config import get_settings
from reviewops.contracts import InvestigationRequest, InvestigationResponse
from reviewops.db import check_database

logger = logging.getLogger("reviewops.requests")
logging.basicConfig(level=get_settings().log_level, format="%(message)s")

app = FastAPI(title="ReviewOPs", version="0.1.0")
app.include_router(analytics_router)


@app.middleware("http")
async def request_boundary(request: Request, call_next):
    request_id = uuid.uuid4().hex
    start = time.monotonic()
    status = 500
    try:
        api_key = get_settings().demo_api_key
        if request.url.path.startswith("/api/") and api_key and api_key.get_secret_value():
            supplied = request.headers.get("x-api-key", "")
            if not secrets.compare_digest(supplied.encode(), api_key.get_secret_value().encode()):
                response = JSONResponse({"detail": "Unauthorized"}, status_code=401)
            else:
                response = await call_next(request)
        else:
            response = await call_next(request)
        status = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        # Do not log prompts, request bodies, query strings, keys, or database credentials.
        logger.info(
            json.dumps(
                {
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status": status,
                    "duration_ms": round((time.monotonic() - start) * 1000, 2),
                }
            )
        )


@app.get("/healthz", tags=["operations"])
def liveness():
    """Process health only: does not imply database or AI readiness."""
    return {"status": "ok", "build_sha": get_settings().build_sha}


@app.get("/readyz", tags=["operations"])
async def readiness():
    dsn = get_settings().database_url
    if not dsn or not dsn.get_secret_value():
        return JSONResponse({"status": "not_ready", "database": "not_configured"}, status_code=503)
    try:
        await asyncio.to_thread(check_database, dsn.get_secret_value())
    except Exception:
        return JSONResponse({"status": "not_ready", "database": "unavailable"}, status_code=503)
    return {"status": "ready", "database": "connected"}


@app.post(
    "/api/v1/investigations",
    response_model=InvestigationResponse,
    responses={
        502: {"description": "Invalid or failed model response"},
        503: {"description": "Database or model unavailable"},
        504: {"description": "Model timeout"},
    },
    tags=["investigations"],
)
def investigate(payload: InvestigationRequest):
    settings = get_settings()
    if settings.app_env != "local" and not (
        settings.demo_api_key and settings.demo_api_key.get_secret_value()
    ):
        raise HTTPException(status_code=503, detail="Configure DEMO_API_KEY for hosted AI requests")
    try:
        return run_investigation(payload, settings)
    except InvestigationError as exc:
        raise HTTPException(
            status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)}
        ) from None


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index():
    return """<!doctype html><html lang="en"><meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>ReviewOPs backbone</title>
    <style>body{font:18px system-ui;max-width:46rem;margin:10vh auto;padding:1.5rem;
    line-height:1.6;background:#f6f8fb;color:#14243b}a{color:#1463c0}</style>
    <h1>ReviewOPs</h1><p>The application backbone is running.</p>
    <p>Review ingestion and SQL analysis are available.
    Complaint investigations require a configured Kimi API key.</p>
    <p><a href="/docs">API contracts</a> · <a href="/healthz">Process health</a> ·
    <a href="/readyz">Database readiness</a></p></html>"""
