"""
AlertIQ Scoring API — Starlette ASGI application.

FastAPI is a thin wrapper over Starlette; this module uses Starlette
directly because the execution environment does not have FastAPI
installed.  The API contract is identical to what a FastAPI application
would expose: JSON request / response, structured error bodies, and
OpenAPI-compatible route design.

Endpoints
---------
GET  /health          — liveness / model readiness check
GET  /metrics         — in-process operational metrics (JSON)
GET  /model/info      — model metadata, feature schema, policy statement
POST /score           — score a single alert
POST /score/batch     — score up to 500 alerts in one request

Environment variables
---------------------
ALERTIQ_MODEL_PATH
    Path to a specific .joblib artifact to load.  Takes precedence over
    ALERTIQ_REGISTRY_PATH + champion selection.

ALERTIQ_REGISTRY_PATH
    Path to the model registry directory.  The champion model is loaded
    automatically.  Defaults to ``models/`` relative to the working directory.

ALERTIQ_AUDIT_LOG_PATH
    Destination for audit records (see audit.py).  "-" → stdout.
    Unset → Python logging.

ALERTIQ_MAX_PAYLOAD_BYTES
    Maximum request body size in bytes.  Default: 10 485 760 (10 MB).

ALERTIQ_GIT_SHA
    40-character Git commit SHA injected by the CD workflow at deploy time.
    Exposed via GET /health for deployment traceability.  Absent in local
    development — the field is ``None`` in that case.

ALERTIQ_IMAGE_DIGEST
    Container image content digest (sha256:...) injected by the CD workflow.
    Exposed via GET /health.  Absent in local development.

Human-in-the-loop
-----------------
Every response includes a ``disclaimer`` field confirming that AlertIQ is
a prioritisation tool, not a compliance decision engine.  Human analysts
review all flagged alerts and make all SAR filing decisions.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator

from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from alertiq.serving.artifact import load_artifact, ModelArtifact
from alertiq.serving.audit import AuditLogger
from alertiq.serving import metrics as _metrics
from alertiq.serving import alert_store as _alert_store
from alertiq.serving.alert_routes import ALERT_ROUTES
from alertiq.serving.schema import (
    BatchAlertResult,
    BatchScoreRequest,
    BatchScoreResponse,
    DataQualityFlags,
    HealthResponse,
    ModelInfoResponse,
    ScoreRequest,
    ScoreResponse,
    SUPPORTED_SCHEMA_VERSIONS,
)
from alertiq.serving.scorer import InferenceScorer, SchemaVersionMismatchError

log = logging.getLogger(__name__)

_DEFAULT_REGISTRY_PATH = "models"
_DEFAULT_MAX_PAYLOAD_BYTES = 10 * 1024 * 1024  # 10 MB

# Module-level singletons populated at startup.
_scorer: InferenceScorer | None = None
_audit: AuditLogger | None = None


# ------------------------------------------------------------------ #
# Startup / shutdown helpers                                           #
# ------------------------------------------------------------------ #

@asynccontextmanager
async def _lifespan(application: Starlette) -> AsyncGenerator[None, None]:
    """Starlette 1.0 lifespan context manager.

    Runs startup on entry, shutdown on exit.
    """
    global _scorer, _audit  # noqa: PLW0603

    # --- Startup ---
    _audit = AuditLogger()

    # Initialise the investigation store (creates tables if they don't exist).
    _alert_store.init_db()

    model_path_env = os.environ.get("ALERTIQ_MODEL_PATH", "").strip()
    registry_path_env = os.environ.get(
        "ALERTIQ_REGISTRY_PATH", _DEFAULT_REGISTRY_PATH
    ).strip()

    artifact: ModelArtifact | None = None

    if model_path_env:
        log.info("Loading model from ALERTIQ_MODEL_PATH=%s", model_path_env)
        try:
            artifact = load_artifact(Path(model_path_env))
        except Exception as exc:
            log.error("Failed to load model from path %s: %s", model_path_env, exc)
    else:
        log.info("Loading champion from ALERTIQ_REGISTRY_PATH=%s", registry_path_env)
        try:
            from alertiq.serving.registry import ModelRegistry
            registry = ModelRegistry(Path(registry_path_env))
            artifact = registry.get_champion()
        except LookupError:
            log.warning(
                "No champion model found in registry at %s. "
                "API will start in degraded mode. "
                "Run train_and_serialize.py --promote to register a champion.",
                registry_path_env,
            )
        except Exception as exc:
            log.error("Failed to load champion from registry: %s", exc)

    if artifact is not None:
        _scorer = InferenceScorer(artifact)
        log.info(
            "API ready: model_version=%s schema_version=%d",
            artifact.model_version,
            artifact.schema_version,
        )
    else:
        log.warning("API starting in DEGRADED mode — no model loaded")

    yield  # Application serves requests here

    # --- Shutdown ---
    if _audit:
        _audit.close()
    log.info("AlertIQ Scoring API shut down")


# ------------------------------------------------------------------ #
# Route handlers                                                       #
# ------------------------------------------------------------------ #

async def metrics_endpoint(request: Request) -> JSONResponse:
    """GET /metrics — in-process operational metrics snapshot.

    Returns a JSON object with:
    - uptime_seconds
    - request counts per (path, status_code)
    - latency percentiles and histogram per path
    - audit_failures — count of audit-log write errors

    This endpoint is unauthenticated because AlertIQ has no authentication
    layer.  In production, restrict access via Cloud Run ingress rules or
    a VPC-internal endpoint.
    """
    return JSONResponse(_metrics.get_snapshot())


async def health(request: Request) -> JSONResponse:
    """GET /health — liveness and readiness check.

    Traceability fields (git_sha, image_digest) are populated from environment
    variables injected by the CD workflow at deploy time.  In local development
    these variables are absent and the fields are ``None``.
    """
    git_sha = os.environ.get("ALERTIQ_GIT_SHA") or None
    image_digest = os.environ.get("ALERTIQ_IMAGE_DIGEST") or None

    if _scorer is not None:
        body = HealthResponse(
            status="ok",
            model_loaded=True,
            model_version=_scorer.artifact.model_version,
            schema_version=_scorer.artifact.schema_version,
            checked_at=datetime.now(timezone.utc),
            git_sha=git_sha,
            image_digest=image_digest,
        )
        return JSONResponse(body.model_dump(mode="json"))

    body = HealthResponse(
        status="degraded",
        model_loaded=False,
        model_version=None,
        schema_version=None,
        checked_at=datetime.now(timezone.utc),
        git_sha=git_sha,
        image_digest=image_digest,
    )
    return JSONResponse(body.model_dump(mode="json"))


async def model_info(request: Request) -> JSONResponse:
    """GET /model/info — model metadata and feature schema."""
    if _scorer is None:
        return _model_not_loaded()
    artifact = _scorer.artifact
    body = ModelInfoResponse(
        model_version=artifact.model_version,
        schema_version=artifact.schema_version,
        operating_mode="capacity_ranking",
        feature_count=len(artifact.feature_columns),
        feature_columns=list(artifact.feature_columns),
        trained_at=artifact.trained_at,
        training_rows=artifact.training_rows,
        best_iter=artifact.best_iter,
        classification_threshold=artifact.threshold,
    )
    return JSONResponse(body.model_dump(mode="json"))


async def score_single(request: Request) -> JSONResponse:
    """POST /score — score a single alert."""
    if _scorer is None:
        return _model_not_loaded()

    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    scored_at = datetime.now(timezone.utc)

    # Parse and validate request body.
    try:
        raw = await _read_body(request)
        body = ScoreRequest.model_validate(raw)
    except ValidationError as exc:
        return JSONResponse(
            {"error": "Request validation failed", "detail": exc.errors()},
            status_code=422,
        )
    except _BodyTooLargeError as exc:
        return JSONResponse(
            {"error": "Request payload too large", "max_bytes": exc.max_bytes},
            status_code=413,
        )
    except Exception:
        return JSONResponse(
            {"error": "Invalid JSON in request body"},
            status_code=400,
        )

    try:
        risk_score, quality_flags, latency_ms = _scorer.score_single(
            schema_version=body.schema_version,
            features=body.features,
        )
        _emit_single_audit(
            request_id=request_id,
            alert_id=body.alert_id,
            model_version=_scorer.artifact.model_version,
            schema_version=body.schema_version,
            risk_score=risk_score,
            quality_flags=quality_flags,
            status="scored",
            error=None,
            latency_ms=latency_ms,
            scored_at=scored_at,
        )
        resp = ScoreResponse(
            alert_id=body.alert_id,
            risk_score=risk_score,
            model_version=_scorer.artifact.model_version,
            schema_version=body.schema_version,
            scored_at=scored_at,
            data_quality_flags=quality_flags,
        )
        response = JSONResponse(resp.model_dump(mode="json"))
        response.headers["X-AlertIQ-Request-ID"] = request_id
        return response

    except SchemaVersionMismatchError as exc:
        _emit_single_audit(
            request_id=request_id,
            alert_id=body.alert_id,
            model_version=_scorer.artifact.model_version,
            schema_version=body.schema_version,
            risk_score=None,
            quality_flags=_empty_quality_flags(),
            status="error",
            error=str(exc),
            latency_ms=0.0,
            scored_at=scored_at,
        )
        return JSONResponse({"error": str(exc)}, status_code=422)

    except Exception as exc:
        log.exception("Unexpected scoring error for alert_id=%s", body.alert_id)
        _emit_single_audit(
            request_id=request_id,
            alert_id=body.alert_id,
            model_version=_scorer.artifact.model_version,
            schema_version=body.schema_version,
            risk_score=None,
            quality_flags=_empty_quality_flags(),
            status="error",
            error="Internal scoring error",
            latency_ms=0.0,
            scored_at=scored_at,
        )
        return JSONResponse({"error": "Internal scoring error"}, status_code=500)


async def score_batch(request: Request) -> JSONResponse:
    """POST /score/batch — score up to 500 alerts in a single request."""
    if _scorer is None:
        return _model_not_loaded()

    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    scored_at = datetime.now(timezone.utc)

    try:
        raw = await _read_body(request)
        body = BatchScoreRequest.model_validate(raw)
    except ValidationError as exc:
        return JSONResponse(
            {"error": "Request validation failed", "detail": exc.errors()},
            status_code=422,
        )
    except _BodyTooLargeError as exc:
        return JSONResponse(
            {"error": "Request payload too large", "max_bytes": exc.max_bytes},
            status_code=413,
        )
    except Exception:
        return JSONResponse(
            {"error": "Invalid JSON in request body"},
            status_code=400,
        )

    # All alerts must use the same schema_version.
    schema_versions = {alert.schema_version for alert in body.alerts}
    if len(schema_versions) > 1:
        return JSONResponse(
            {
                "error": (
                    "All alerts in a batch must use the same schema_version. "
                    f"Found: {sorted(schema_versions)}"
                )
            },
            status_code=422,
        )

    batch_schema_version = next(iter(schema_versions))
    import time
    t_batch_start = time.perf_counter()

    results: list[BatchAlertResult] = []
    succeeded = 0
    failed = 0

    for alert in body.alerts:
        try:
            risk_score, quality_flags, latency_alert = _scorer.score_single(
                schema_version=alert.schema_version,
                features=alert.features,
            )
            results.append(BatchAlertResult(
                alert_id=alert.alert_id,
                risk_score=risk_score,
                status="scored",
                data_quality_flags=quality_flags,
            ))
            succeeded += 1
            # Emit a per-alert audit record so every scored alert is
            # individually traceable (required for AML compliance review).
            _emit_single_audit(
                request_id=request_id,
                alert_id=alert.alert_id,
                model_version=_scorer.artifact.model_version,
                schema_version=alert.schema_version,
                risk_score=risk_score,
                quality_flags=quality_flags,
                status="scored",
                error=None,
                latency_ms=latency_alert,
                scored_at=scored_at,
            )
        except SchemaVersionMismatchError as exc:
            results.append(BatchAlertResult(
                alert_id=alert.alert_id,
                risk_score=None,
                status="error",
                error=str(exc),
            ))
            failed += 1
            _emit_single_audit(
                request_id=request_id,
                alert_id=alert.alert_id,
                model_version=_scorer.artifact.model_version,
                schema_version=alert.schema_version,
                risk_score=None,
                quality_flags=_empty_quality_flags(),
                status="error",
                error=str(exc),
                latency_ms=0.0,
                scored_at=scored_at,
            )
        except Exception:
            log.exception("Batch scoring error for alert_id=%s", alert.alert_id)
            results.append(BatchAlertResult(
                alert_id=alert.alert_id,
                risk_score=None,
                status="error",
                error="Internal scoring error — see server logs",
            ))
            failed += 1
            _emit_single_audit(
                request_id=request_id,
                alert_id=alert.alert_id,
                model_version=_scorer.artifact.model_version,
                schema_version=alert.schema_version,
                risk_score=None,
                quality_flags=_empty_quality_flags(),
                status="error",
                error="Internal scoring error",
                latency_ms=0.0,
                scored_at=scored_at,
            )

    batch_latency_ms = (time.perf_counter() - t_batch_start) * 1000.0

    if _audit:
        try:
            _audit.record_batch_score(
                request_id=request_id,
                batch_id=body.batch_id,
                model_version=_scorer.artifact.model_version,
                schema_version=batch_schema_version,
                total=len(body.alerts),
                succeeded=succeeded,
                failed=failed,
                latency_ms=batch_latency_ms,
                scored_at=scored_at,
            )
        except Exception as exc:  # noqa: BLE001
            log.error(
                "Audit record_batch_score raised unexpectedly "
                "(batch_id=%s, counted in /metrics audit_failures): %s",
                body.batch_id, exc,
            )
            _metrics.record_audit_failure()

    resp = BatchScoreResponse(
        batch_id=body.batch_id,
        model_version=_scorer.artifact.model_version,
        schema_version=batch_schema_version,
        scored_at=scored_at,
        total=len(body.alerts),
        succeeded=succeeded,
        failed=failed,
        results=results,
    )
    response = JSONResponse(resp.model_dump(mode="json"))
    response.headers["X-AlertIQ-Request-ID"] = request_id
    return response


# ------------------------------------------------------------------ #
# Middleware                                                            #
# ------------------------------------------------------------------ #

class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach a UUID request ID to every request and response.

    Also records per-request metrics (path, status code, duration) into the
    in-process metrics store so the /metrics endpoint can surface them.
    """

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        import time as _time

        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        t0 = _time.perf_counter()
        response = await call_next(request)
        duration_ms = (_time.perf_counter() - t0) * 1000.0
        response.headers["X-AlertIQ-Request-ID"] = request_id
        _metrics.record_request(
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response


class PayloadSizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests larger than ALERTIQ_MAX_PAYLOAD_BYTES."""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        max_bytes = int(
            os.environ.get("ALERTIQ_MAX_PAYLOAD_BYTES", _DEFAULT_MAX_PAYLOAD_BYTES)
        )
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > max_bytes:
            return JSONResponse(
                {"error": "Request payload too large", "max_bytes": max_bytes},
                status_code=413,
            )
        return await call_next(request)


# ------------------------------------------------------------------ #
# Application factory                                                  #
# ------------------------------------------------------------------ #

def create_app() -> Starlette:
    """Create and return the Starlette ASGI application."""
    routes = [
        Route("/health", health, methods=["GET"]),
        Route("/metrics", metrics_endpoint, methods=["GET"]),
        Route("/model/info", model_info, methods=["GET"]),
        Route("/score", score_single, methods=["POST"]),
        Route("/score/batch", score_batch, methods=["POST"]),
        *ALERT_ROUTES,
    ]
    # CORS is enabled for the local frontend dev server (localhost:3000).
    # In production, Cloud Run ingress rules restrict traffic to internal
    # callers; the CORS header allows the browser to reach the API from
    # the co-deployed Next.js frontend.
    _cors_origins = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    middleware = [
        Middleware(
            CORSMiddleware,
            allow_origins=_cors_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type", "X-AlertIQ-Request-ID"],
            expose_headers=["X-AlertIQ-Request-ID"],
        ),
        Middleware(RequestIDMiddleware),
        Middleware(PayloadSizeLimitMiddleware),
    ]
    return Starlette(
        routes=routes,
        middleware=middleware,
        lifespan=_lifespan,
    )


# Singleton application instance (used by uvicorn and tests).
app = create_app()


# ------------------------------------------------------------------ #
# Internal helpers                                                     #
# ------------------------------------------------------------------ #

class _BodyTooLargeError(Exception):
    """Raised when the request body exceeds the configured size limit.

    Distinct from the Content-Length pre-check in PayloadSizeLimitMiddleware,
    which only fires when the client sends a truthful Content-Length header.
    This exception is raised during actual body streaming, so it catches
    chunked-transfer or header-lying clients that bypass the middleware check.
    """

    def __init__(self, max_bytes: int) -> None:
        super().__init__(f"Request body exceeds the {max_bytes:,}-byte limit")
        self.max_bytes = max_bytes


async def _read_body(request: Request) -> Any:
    """Read and JSON-decode the request body, enforcing the payload size limit.

    Reads the body in streaming chunks so that the size limit is enforced
    against the actual bytes received, regardless of the Content-Length header
    (which is absent for chunked-transfer-encoded requests and trivially forged
    by a client sending a lying header after the middleware pre-check).
    """
    max_bytes = int(os.environ.get("ALERTIQ_MAX_PAYLOAD_BYTES", _DEFAULT_MAX_PAYLOAD_BYTES))
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > max_bytes:
            raise _BodyTooLargeError(max_bytes)
    return json.loads(bytes(body))


def _model_not_loaded() -> JSONResponse:
    return JSONResponse(
        {
            "error": (
                "No model is currently loaded. "
                "Train and register a model with train_and_serialize.py, "
                "then restart the API."
            )
        },
        status_code=503,
    )


def _emit_single_audit(
    *,
    request_id: str,
    alert_id: str,
    model_version: str,
    schema_version: int,
    risk_score: float | None,
    quality_flags: DataQualityFlags,
    status: str,
    error: str | None,
    latency_ms: float,
    scored_at: datetime,
) -> None:
    """Write one scoring audit record.

    This function MUST NOT raise.  Any exception from the audit subsystem
    is caught here, logged to stderr, and counted in the metrics store.
    Scoring responses are always returned to the caller regardless of
    whether the audit write succeeded.
    """
    if _audit is None:
        return
    try:
        _audit.record_score(
            request_id=request_id,
            alert_id=alert_id,
            model_version=model_version,
            schema_version=schema_version,
            risk_score=risk_score,
            quality_warning=quality_flags.quality_warning,
            zero_feature_names=quality_flags.zero_feature_names,
            extreme_feature_names=quality_flags.extreme_feature_names,
            status=status,
            error=error,
            latency_ms=latency_ms,
            scored_at=scored_at,
        )
    except Exception as exc:  # noqa: BLE001
        log.error(
            "Audit record_score raised unexpectedly "
            "(alert_id=%s, counted in /metrics audit_failures): %s",
            alert_id, exc,
        )
        _metrics.record_audit_failure()


def _empty_quality_flags() -> DataQualityFlags:
    return DataQualityFlags(
        has_zeroed_features=False,
        zero_feature_names=[],
        has_extreme_values=False,
        extreme_feature_names=[],
        quality_warning=False,
    )
