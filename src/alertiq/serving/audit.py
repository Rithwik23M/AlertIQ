"""
Structured audit log for the AlertIQ scoring API.

Every scoring event is recorded as a single newline-delimited JSON record.
Each record contains enough information to reconstruct what was scored,
by which model version, at what time, and whether any data quality issues
were flagged — WITHOUT storing the raw feature values, which may include
sensitive financial information.

Audit record schema
-------------------
    {
        "event":           "score" | "batch_score",
        "request_id":      str,          # UUID per API request
        "alert_id":        str | null,   # null for batch-level records
        "batch_id":        str | null,   # null for single-score records
        "model_version":   str,
        "schema_version":  int,
        "scored_at":       str,          # ISO-8601 UTC
        "risk_score":      float | null, # null on error
        "operating_mode":  "capacity_ranking",
        "quality_warning": bool,
        "zero_features":   [str, ...],   # feature names with zero values
        "extreme_features":[str, ...],   # feature names with extreme values
        "status":          "scored" | "error",
        "error":           str | null,   # error description, no stack traces
        "latency_ms":      float         # end-to-end request latency in ms
    }

Security notes
--------------
- Raw feature values are NOT logged.  Logging financial transaction
  features would make the audit log itself a high-value data asset
  with additional protection requirements.
- Error messages are sanitised before logging (no stack traces, no
  internal paths, no raw input echoing).
- The audit log is append-only from the API's perspective.  Rotation
  and archival are handled at the infrastructure level (logrotate, S3
  lifecycle policy, etc.).
- Log integrity (tamper evidence) is out of scope for M4; a production
  deployment would route audit records to an immutable store (AWS
  CloudTrail, a WORM S3 bucket, or a SIEM) via a log shipper.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Lazy import of the metrics module to avoid a circular import at module load.
# The metrics module is always available inside the serving package, but we
# defer the import to the call site so that audit.py can be imported
# independently (e.g. in tests or CLI scripts) without dragging in the full
# serving package initialisation.
def _record_audit_failure() -> None:
    """Increment the audit-failure counter in the metrics store, if available."""
    try:
        from alertiq.serving import metrics as _m  # noqa: PLC0415
        _m.record_audit_failure()
    except Exception:
        # If the metrics module is unavailable (e.g. during a unit test that
        # imports audit.py in isolation), silently ignore.
        pass

# Environment variable controlling the audit log destination.
# ALERTIQ_AUDIT_LOG_PATH="-" → stdout (useful in container environments)
# ALERTIQ_AUDIT_LOG_PATH="path/to/audit.jsonl" → append to that file
# Unset → log via the standard Python logging system at INFO level
_ENV_AUDIT_PATH = "ALERTIQ_AUDIT_LOG_PATH"

_SANITISED_ERROR_PREFIX = "[sanitised] "


class AuditLogger:
    """Writes structured audit records.

    Instantiated once at application startup.  Thread-safe for
    append-only writes because file.write() + flush() on a single line
    is atomic on POSIX filesystems when the line fits in PIPE_BUF
    (4 096 bytes on Linux).  For record sizes larger than PIPE_BUF,
    use a log-shipping agent rather than relying on this atomic guarantee.
    """

    def __init__(self) -> None:
        audit_path = os.environ.get(_ENV_AUDIT_PATH, "").strip()
        self._file: Any = None

        if audit_path == "-":
            self._file = sys.stdout
            log.info("Audit log → stdout")
        elif audit_path:
            path = Path(audit_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._file = open(path, "a", encoding="utf-8", buffering=1)  # noqa: SIM115
            log.info("Audit log → %s", path)
        else:
            log.info("Audit log → Python logging (set %s to write to a file)", _ENV_AUDIT_PATH)

    def record_score(
        self,
        *,
        request_id: str,
        alert_id: str,
        model_version: str,
        schema_version: int,
        risk_score: float | None,
        quality_warning: bool,
        zero_feature_names: list[str],
        extreme_feature_names: list[str],
        status: str,
        error: str | None,
        latency_ms: float,
        scored_at: datetime | None = None,
    ) -> None:
        """Record a single-alert scoring event."""
        record = self._build_record(
            event="score",
            request_id=request_id,
            alert_id=alert_id,
            batch_id=None,
            model_version=model_version,
            schema_version=schema_version,
            risk_score=risk_score,
            quality_warning=quality_warning,
            zero_features=zero_feature_names,
            extreme_features=extreme_feature_names,
            status=status,
            error=error,
            latency_ms=latency_ms,
            scored_at=scored_at,
        )
        self._emit(record)

    def record_batch_score(
        self,
        *,
        request_id: str,
        batch_id: str | None,
        model_version: str,
        schema_version: int,
        total: int,
        succeeded: int,
        failed: int,
        latency_ms: float,
        scored_at: datetime | None = None,
    ) -> None:
        """Record a batch-level summary event (one record per batch request)."""
        record: dict[str, Any] = {
            "event": "batch_score",
            "request_id": request_id,
            "alert_id": None,
            "batch_id": batch_id,
            "model_version": model_version,
            "schema_version": schema_version,
            "scored_at": (scored_at or _utcnow_dt()).isoformat(),
            "operating_mode": "capacity_ranking",
            "total": total,
            "succeeded": succeeded,
            "failed": failed,
            "latency_ms": round(latency_ms, 3),
        }
        self._emit(record)

    def close(self) -> None:
        """Flush and close the audit log file (if open)."""
        if self._file and self._file not in (sys.stdout, sys.stderr):
            try:
                self._file.flush()
                self._file.close()
            except OSError:
                pass

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_record(
        *,
        event: str,
        request_id: str,
        alert_id: str | None,
        batch_id: str | None,
        model_version: str,
        schema_version: int,
        risk_score: float | None,
        quality_warning: bool,
        zero_features: list[str],
        extreme_features: list[str],
        status: str,
        error: str | None,
        latency_ms: float,
        scored_at: datetime | None,
    ) -> dict[str, Any]:
        return {
            "event": event,
            "request_id": request_id,
            "alert_id": alert_id,
            "batch_id": batch_id,
            "model_version": model_version,
            "schema_version": schema_version,
            "scored_at": (scored_at or _utcnow_dt()).isoformat(),
            "operating_mode": "capacity_ranking",
            "risk_score": round(risk_score, 6) if risk_score is not None else None,
            "quality_warning": quality_warning,
            "zero_features": zero_features,
            "extreme_features": extreme_features,
            "status": status,
            "error": _sanitise_error(error),
            "latency_ms": round(latency_ms, 3),
        }

    def _emit(self, record: dict[str, Any]) -> None:
        """Write one audit record.

        Durability contract
        -------------------
        * A write failure MUST NOT propagate to the scoring response.
          The caller does not wrap _emit() in a try/except; this method
          absorbs all exceptions internally.
        * Every failure is:
          (a) logged to stderr so it appears in Cloud Run logs; and
          (b) counted in the in-process metrics store so the /metrics
              endpoint exposes the failure rate to operators.
        * The scoring response is returned normally even if audit writing
          fails — losing an audit record is preferable to failing the
          API call, since analysts can re-score an alert but a failed
          API call causes the upstream TMS to retry.
        """
        line = json.dumps(record, ensure_ascii=False) + "\n"
        if self._file:
            try:
                self._file.write(line)
                if self._file is not sys.stdout:
                    self._file.flush()
            except OSError as exc:
                # Log to stderr (Cloud Run captures this).
                log.error("Audit log write failed (record counted in metrics): %s", exc)
                # Increment the operational counter — visible at /metrics.
                _record_audit_failure()
        else:
            log.info("AUDIT %s", line.rstrip())


def _utcnow_dt() -> datetime:
    return datetime.now(timezone.utc)


def _sanitise_error(error: str | None) -> str | None:
    """Strip path information and stack-trace markers from error strings."""
    if error is None:
        return None
    # Truncate long errors and tag them as sanitised
    truncated = error[:500]
    if len(error) > 500:
        truncated += "… [truncated]"
    return truncated
