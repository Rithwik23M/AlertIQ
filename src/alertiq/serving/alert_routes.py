"""
AlertIQ Investigation API — analyst-facing routes for Milestone 6.

These routes are mounted onto the existing Starlette application and provide
the backend for the React investigation workspace.

Endpoints
---------
GET  /queue/stats                    — capacity/queue statistics
GET  /alerts                         — paginated, filtered alert queue
GET  /alerts/{id}                    — full alert detail with explainability
GET  /alerts/{id}/transactions       — transaction timeline
GET  /alerts/{id}/history            — audit event log
GET  /alerts/{id}/notes              — investigation notes
GET  /alerts/{id}/decisions          — decision history
POST /alerts/{id}/open               — record alert opened (status transition)
POST /alerts/{id}/notes              — add investigation note
POST /alerts/{id}/decision           — record investigation decision

Security notes
--------------
- True SAR labels from simulation ground truth are NEVER returned.
- Note content is stored as-is; it is NOT sent to any external service.
- Analyst IDs are pseudonymous placeholders in the portfolio deployment.
- Input strings are length-limited to prevent excessively large writes.
"""

from __future__ import annotations

import json
import logging

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from alertiq.serving import alert_store as _store

log = logging.getLogger(__name__)

_MAX_NOTE_LENGTH = 4_000
_MAX_RATIONALE_LENGTH = 2_000

# Default analyst ID for portfolio demo (no auth layer implemented)
_DEFAULT_ANALYST_ID = "ANL-01"


# ------------------------------------------------------------------ #
# Queue / capacity                                                     #
# ------------------------------------------------------------------ #

async def queue_stats(request: Request) -> JSONResponse:
    """GET /queue/stats — queue summary for the capacity banner."""
    try:
        stats = _store.get_queue_stats()
        return JSONResponse(stats)
    except Exception as exc:
        log.exception("Failed to retrieve queue stats: %s", exc)
        return JSONResponse({"error": "Failed to retrieve queue statistics"}, status_code=500)


# ------------------------------------------------------------------ #
# Alert list                                                           #
# ------------------------------------------------------------------ #

async def list_alerts(request: Request) -> JSONResponse:
    """GET /alerts — paginated, filtered alert queue.

    Query parameters
    ----------------
    status      : filter by investigation status
    rule_id     : filter by rule ID
    min_score   : minimum risk_score (float, 0.0–1.0)
    search      : substring match on alert_id or account_id
    sort_by     : risk_score | alert_date | severity | queue_position
    sort_dir    : desc | asc
    page        : 1-indexed page number
    page_size   : results per page (max 100)
    """
    params = request.query_params
    try:
        page = max(1, int(params.get("page", 1)))
        page_size = min(100, max(1, int(params.get("page_size", 50))))
        min_score_raw = params.get("min_score")
        min_score = float(min_score_raw) if min_score_raw else None

        result = _store.list_alerts(
            status=params.get("status") or None,
            rule_id=params.get("rule_id") or None,
            min_score=min_score,
            search=params.get("search") or None,
            sort_by=params.get("sort_by", "risk_score"),
            sort_dir=params.get("sort_dir", "desc"),
            page=page,
            page_size=page_size,
        )
        return JSONResponse(result)
    except (ValueError, TypeError) as exc:
        return JSONResponse({"error": f"Invalid query parameter: {exc}"}, status_code=400)
    except Exception as exc:
        log.exception("Failed to list alerts: %s", exc)
        return JSONResponse({"error": "Failed to retrieve alert list"}, status_code=500)


# ------------------------------------------------------------------ #
# Alert detail                                                         #
# ------------------------------------------------------------------ #

async def get_alert(request: Request) -> JSONResponse:
    """GET /alerts/{id} — full alert detail including features and explainability."""
    alert_id = request.path_params["id"]
    try:
        detail = _store.get_alert(alert_id)
        if detail is None:
            return JSONResponse({"error": f"Alert not found: {alert_id}"}, status_code=404)
        return JSONResponse(detail)
    except Exception as exc:
        log.exception("Failed to retrieve alert %s: %s", alert_id, exc)
        return JSONResponse({"error": "Failed to retrieve alert"}, status_code=500)


async def get_alert_transactions(request: Request) -> JSONResponse:
    """GET /alerts/{id}/transactions — transaction timeline for the alert's account."""
    alert_id = request.path_params["id"]
    try:
        limit = min(200, max(1, int(request.query_params.get("limit", 100))))
        txns = _store.get_alert_transactions(alert_id, limit=limit)
        return JSONResponse({"alert_id": alert_id, "transactions": txns, "count": len(txns)})
    except (ValueError, TypeError) as exc:
        return JSONResponse({"error": f"Invalid query parameter: {exc}"}, status_code=400)
    except Exception as exc:
        log.exception("Failed to retrieve transactions for alert %s: %s", alert_id, exc)
        return JSONResponse({"error": "Failed to retrieve transactions"}, status_code=500)


async def get_alert_history(request: Request) -> JSONResponse:
    """GET /alerts/{id}/history — audit event log, oldest first."""
    alert_id = request.path_params["id"]
    try:
        events = _store.get_alert_history(alert_id)
        return JSONResponse({"alert_id": alert_id, "events": events, "count": len(events)})
    except Exception as exc:
        log.exception("Failed to retrieve history for alert %s: %s", alert_id, exc)
        return JSONResponse({"error": "Failed to retrieve audit history"}, status_code=500)


async def get_alert_notes(request: Request) -> JSONResponse:
    """GET /alerts/{id}/notes — investigation notes."""
    alert_id = request.path_params["id"]
    try:
        notes = _store.get_alert_notes(alert_id)
        return JSONResponse({"alert_id": alert_id, "notes": notes, "count": len(notes)})
    except Exception as exc:
        log.exception("Failed to retrieve notes for alert %s: %s", alert_id, exc)
        return JSONResponse({"error": "Failed to retrieve notes"}, status_code=500)


async def get_alert_decisions(request: Request) -> JSONResponse:
    """GET /alerts/{id}/decisions — decision history."""
    alert_id = request.path_params["id"]
    try:
        decisions = _store.get_alert_decisions(alert_id)
        return JSONResponse({"alert_id": alert_id, "decisions": decisions, "count": len(decisions)})
    except Exception as exc:
        log.exception("Failed to retrieve decisions for alert %s: %s", alert_id, exc)
        return JSONResponse({"error": "Failed to retrieve decisions"}, status_code=500)


# ------------------------------------------------------------------ #
# Analyst write operations                                             #
# ------------------------------------------------------------------ #

async def open_alert(request: Request) -> JSONResponse:
    """POST /alerts/{id}/open — record that an analyst opened this alert.

    Body (optional JSON)
    --------------------
    analyst_id : str  — pseudonymous analyst identifier
    """
    alert_id = request.path_params["id"]
    try:
        body = await _parse_optional_body(request)
        analyst_id = _safe_str(body.get("analyst_id", _DEFAULT_ANALYST_ID), 64)

        success = _store.open_alert(alert_id, analyst_id)
        if not success:
            return JSONResponse({"error": f"Alert not found: {alert_id}"}, status_code=404)
        return JSONResponse({"alert_id": alert_id, "analyst_id": analyst_id, "status": "ok"})
    except Exception as exc:
        log.exception("Failed to open alert %s: %s", alert_id, exc)
        return JSONResponse({"error": "Failed to record alert open"}, status_code=500)


async def add_note(request: Request) -> JSONResponse:
    """POST /alerts/{id}/notes — add an investigation note.

    Body (JSON, required)
    ---------------------
    content    : str  — note text (1–4000 characters)
    analyst_id : str  — pseudonymous analyst identifier
    """
    alert_id = request.path_params["id"]
    try:
        body = await _parse_required_body(request)
    except _BadRequestError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    content = _safe_str(body.get("content", ""), _MAX_NOTE_LENGTH)
    analyst_id = _safe_str(body.get("analyst_id", _DEFAULT_ANALYST_ID), 64)

    if not content.strip():
        return JSONResponse({"error": "Note content must not be empty"}, status_code=400)

    try:
        note = _store.add_note(alert_id, analyst_id, content)
        if note is None:
            return JSONResponse({"error": f"Alert not found: {alert_id}"}, status_code=404)
        return JSONResponse(note, status_code=201)
    except Exception as exc:
        log.exception("Failed to add note to alert %s: %s", alert_id, exc)
        return JSONResponse({"error": "Failed to add note"}, status_code=500)


async def record_decision(request: Request) -> JSONResponse:
    """POST /alerts/{id}/decision — record an investigation decision.

    Body (JSON, required)
    ---------------------
    outcome    : str  — 'escalate' | 'close' | 'needs_further_review'
    rationale  : str  — optional free-text rationale
    analyst_id : str  — pseudonymous analyst identifier

    Important: This endpoint records the analyst's decision. It does NOT
    modify historical model scores or override AlertIQ's risk assessment.
    Model evidence and human decision are stored separately and immutably.
    """
    alert_id = request.path_params["id"]
    try:
        body = await _parse_required_body(request)
    except _BadRequestError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    outcome = _safe_str(body.get("outcome", ""), 64)
    rationale = _safe_str(body.get("rationale", ""), _MAX_RATIONALE_LENGTH) or None
    analyst_id = _safe_str(body.get("analyst_id", _DEFAULT_ANALYST_ID), 64)

    if not outcome:
        return JSONResponse({"error": "outcome is required"}, status_code=400)

    if outcome not in _store.VALID_OUTCOMES:
        return JSONResponse({
            "error": f"Invalid outcome: '{outcome}'. Must be one of: {sorted(_store.VALID_OUTCOMES)}"
        }, status_code=422)

    try:
        decision = _store.record_decision(alert_id, analyst_id, outcome, rationale)
        if decision is None:
            return JSONResponse({"error": f"Alert not found: {alert_id}"}, status_code=404)
        return JSONResponse(decision, status_code=201)
    except Exception as exc:
        log.exception("Failed to record decision for alert %s: %s", alert_id, exc)
        return JSONResponse({"error": "Failed to record decision"}, status_code=500)


# ------------------------------------------------------------------ #
# Route table                                                          #
# ------------------------------------------------------------------ #

ALERT_ROUTES = [
    Route("/queue/stats", queue_stats, methods=["GET"]),
    Route("/alerts", list_alerts, methods=["GET"]),
    Route("/alerts/{id}", get_alert, methods=["GET"]),
    Route("/alerts/{id}/transactions", get_alert_transactions, methods=["GET"]),
    Route("/alerts/{id}/history", get_alert_history, methods=["GET"]),
    Route("/alerts/{id}/notes", get_alert_notes, methods=["GET"]),
    Route("/alerts/{id}/decisions", get_alert_decisions, methods=["GET"]),
    Route("/alerts/{id}/open", open_alert, methods=["POST"]),
    Route("/alerts/{id}/notes", add_note, methods=["POST"]),
    Route("/alerts/{id}/decision", record_decision, methods=["POST"]),
]


# ------------------------------------------------------------------ #
# Internal helpers                                                     #
# ------------------------------------------------------------------ #

class _BadRequestError(Exception):
    pass


async def _parse_required_body(request: Request) -> dict:
    try:
        raw = await request.body()
        if not raw:
            raise _BadRequestError("Request body is required")
        return json.loads(raw)
    except json.JSONDecodeError:
        raise _BadRequestError("Invalid JSON in request body")


async def _parse_optional_body(request: Request) -> dict:
    try:
        raw = await request.body()
        if not raw:
            return {}
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _safe_str(value: object, max_len: int) -> str:
    """Cast to string and truncate to max_len."""
    if value is None:
        return ""
    return str(value)[:max_len]
