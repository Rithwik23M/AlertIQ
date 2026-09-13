"""
alertiq.serving.metrics
=======================

In-process, thread-safe metrics store for the AlertIQ scoring service.

Design choices
--------------
* No external dependencies (no Prometheus client, no StatsD).
  The /metrics endpoint exposes plain JSON so Cloud Run, a sidecar scraper,
  or a simple Cloud Monitoring custom metric shipper can consume it without
  requiring a Prometheus server.
* All state lives in module-level objects.  The WSGI/ASGI process is single-
  threaded (uvicorn with one worker), but threading.Lock guards are included
  for correctness should a multi-threaded deployment arise.
* The store is intentionally simple: counters and a latency histogram.
  Add gauges or more histogram buckets only when a concrete monitoring need
  justifies the complexity.

Public API
----------
    record_request(path, status_code, duration_ms)
    record_audit_failure()
    get_snapshot() -> dict

"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Dict, List

# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------

_lock = threading.Lock()

# request_counts[(path, status_code)] = int
_request_counts: Dict[tuple, int] = defaultdict(int)

# request_duration_ms[path] = [ms, ...]  (kept bounded; see _MAX_SAMPLES)
_MAX_SAMPLES = 2000
_request_durations_ms: Dict[str, List[float]] = defaultdict(list)

# Total requests that resulted in an audit-log write failure.
_audit_failure_count: int = 0

# Process start time (Unix timestamp).  Used to compute uptime.
_start_time: float = time.time()

# Histogram bucket upper bounds in milliseconds.
_LATENCY_BUCKETS_MS = [10, 25, 50, 100, 250, 500, 1000, 2500, float("inf")]


# ---------------------------------------------------------------------------
# Public write API
# ---------------------------------------------------------------------------


def record_request(path: str, status_code: int, duration_ms: float) -> None:
    """Record one completed HTTP request.

    Parameters
    ----------
    path:
        The request path (e.g. ``/score``, ``/score/batch``).
    status_code:
        HTTP response status code.
    duration_ms:
        End-to-end response time in milliseconds.
    """
    with _lock:
        _request_counts[(path, status_code)] += 1
        samples = _request_durations_ms[path]
        samples.append(duration_ms)
        # Cap memory: drop oldest samples when the buffer is full.
        if len(samples) > _MAX_SAMPLES:
            _request_durations_ms[path] = samples[-_MAX_SAMPLES:]


def record_audit_failure() -> None:
    """Increment the audit-log failure counter.

    Called by the audit logger when a write fails.  The failure is counted
    here so it appears in the /metrics snapshot; it must never block or raise
    inside the scoring hot-path.
    """
    global _audit_failure_count
    with _lock:
        _audit_failure_count += 1


# ---------------------------------------------------------------------------
# Public read API
# ---------------------------------------------------------------------------


def get_snapshot() -> dict:
    """Return a JSON-serialisable metrics snapshot.

    The snapshot includes:

    * ``uptime_seconds`` — seconds since process start.
    * ``requests`` — per-(path, status_code) counts.
    * ``latency_ms`` — per-path percentile summary and histogram.
    * ``audit_failures`` — number of audit-log write failures.
    """
    with _lock:
        counts_copy = dict(_request_counts)
        durations_copy = {k: list(v) for k, v in _request_durations_ms.items()}
        audit_failures = _audit_failure_count

    uptime = time.time() - _start_time

    # Flatten request counts into a list of dicts for easy JSON rendering.
    requests = [
        {"path": path, "status_code": status, "count": count}
        for (path, status), count in sorted(counts_copy.items())
    ]

    # Compute per-path latency summary.
    latency: Dict[str, dict] = {}
    for path, samples in durations_copy.items():
        if not samples:
            continue
        sorted_samples = sorted(samples)
        n = len(sorted_samples)
        latency[path] = {
            "count": n,
            "min_ms": round(sorted_samples[0], 2),
            "p50_ms": round(_percentile(sorted_samples, 50), 2),
            "p95_ms": round(_percentile(sorted_samples, 95), 2),
            "p99_ms": round(_percentile(sorted_samples, 99), 2),
            "max_ms": round(sorted_samples[-1], 2),
            "histogram": _histogram(sorted_samples),
        }

    return {
        "uptime_seconds": round(uptime, 1),
        "requests": requests,
        "latency_ms": latency,
        "audit_failures": audit_failures,
    }


def reset() -> None:
    """Reset all counters and samples.

    Intended for use in tests only.  Do not call in production code.
    """
    global _audit_failure_count, _start_time
    with _lock:
        _request_counts.clear()
        _request_durations_ms.clear()
        _audit_failure_count = 0
        _start_time = time.time()


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _percentile(sorted_values: list, p: float) -> float:
    """Return the p-th percentile of a pre-sorted list."""
    if not sorted_values:
        return 0.0
    n = len(sorted_values)
    idx = (p / 100.0) * (n - 1)
    lo = int(idx)
    hi = lo + 1
    if hi >= n:
        return float(sorted_values[-1])
    frac = idx - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


def _histogram(sorted_values: list) -> list:
    """Return bucket counts for each _LATENCY_BUCKETS_MS bound."""
    buckets = []
    prev = 0
    prev_count = 0
    for bound in _LATENCY_BUCKETS_MS:
        # Count of samples <= bound.
        count = sum(1 for v in sorted_values if v <= bound)
        label = f"le_{bound}" if bound != float("inf") else "le_inf"
        buckets.append(
            {
                "le_ms": None if bound == float("inf") else bound,
                "label": label,
                "count": count,
                "bucket_count": count - prev_count,
            }
        )
        prev_count = count
    return buckets
