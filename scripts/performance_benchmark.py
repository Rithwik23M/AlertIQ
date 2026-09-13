#!/usr/bin/env python3
"""
AlertIQ Performance Benchmark
==============================

Measures the latency and throughput of the AlertIQ scoring API under
representative load.  Designed to run against a live instance (local Docker
or Cloud Run staging) and produce a reproducible latency report.

This is NOT a load/stress test.  It runs sequentially (no concurrency) to
measure baseline single-client latency without contention.  Use a tool such
as k6, locust, or hey for concurrent load testing.

Usage
-----
    # Against a local Docker container:
    python scripts/performance_benchmark.py --base-url http://localhost:8080

    # Against Cloud Run staging, 100 iterations per endpoint:
    python scripts/performance_benchmark.py \\
        --base-url https://alertiq-api-staging.run.app \\
        --iterations 100

    # Warm up the model cache, then benchmark:
    python scripts/performance_benchmark.py \\
        --base-url http://localhost:8080 \\
        --warmup 10 \\
        --iterations 200

Exit codes
----------
    0   Benchmark completed (even if SLO thresholds are exceeded — see output).
    1   Could not connect to the API.

Dependencies
------------
    pip install httpx
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from typing import Any

try:
    import httpx
except ImportError:
    print("ERROR: httpx is required.  Install it with: pip install httpx")
    sys.exit(1)

# ---------------------------------------------------------------------------
# SLO targets (informational only — benchmark does not hard-fail on these)
# ---------------------------------------------------------------------------

_SLO_SINGLE_P95_MS = 200.0   # 95th-percentile single-alert latency
_SLO_BATCH_P95_MS = 1000.0   # 95th-percentile 100-alert batch latency

# ---------------------------------------------------------------------------
# Sample payloads
# ---------------------------------------------------------------------------

_BASE_FEATURES: dict[str, Any] = {
    "txn_count_7d": 12,
    "txn_amount_7d": 15000.0,
    "txn_count_30d": 45,
    "txn_amount_30d": 62000.0,
    "txn_count_90d": 120,
    "txn_amount_90d": 180000.0,
    "avg_txn_amount_7d": 1250.0,
    "max_txn_amount_7d": 8000.0,
    "std_txn_amount_7d": 2100.0,
    "cross_border_ratio_30d": 0.4,
    "cash_ratio_30d": 0.15,
    "unique_counterparties_30d": 18,
    "structuring_score": 0.12,
    "velocity_score": 0.35,
    "network_risk_score": 0.28,
    "rule_trigger_count": 2,
    "alert_history_90d": 1,
    "account_age_days": 730,
    "is_high_risk_jurisdiction": 0,
    "product_risk_score": 0.4,
}


def _single_payload(i: int) -> dict:
    return {
        "alert_id": f"bench-single-{i:06d}",
        "schema_version": 1,
        "features": _BASE_FEATURES,
    }


def _batch_payload(batch_size: int, i: int) -> dict:
    return {
        "batch_id": f"bench-batch-{i:06d}",
        "alerts": [
            {
                "alert_id": f"bench-batch-{i:06d}-alert-{j:04d}",
                "schema_version": 1,
                "features": _BASE_FEATURES,
            }
            for j in range(batch_size)
        ],
    }


# ---------------------------------------------------------------------------
# Benchmark runner
# ---------------------------------------------------------------------------

def _measure_latencies(
    client: httpx.Client,
    method: str,
    path: str,
    payload: dict | None,
    n: int,
    label: str,
) -> list[float]:
    """Run n sequential requests and return wall-clock latencies in ms."""
    latencies: list[float] = []
    for i in range(n):
        payload_i = payload(i) if callable(payload) else payload  # type: ignore[operator]
        t0 = time.perf_counter()
        try:
            if method == "GET":
                resp = client.get(path)
            else:
                resp = client.post(path, json=payload_i)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            if resp.status_code not in (200, 503):
                print(
                    f"  [WARNING] {label} iteration {i}: "
                    f"HTTP {resp.status_code} — {resp.text[:120]}"
                )
            latencies.append(elapsed_ms)
        except httpx.RequestError as exc:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            print(f"  [ERROR] {label} iteration {i}: {exc}")
            latencies.append(elapsed_ms)
    return latencies


def _pct(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    n = len(sorted_values)
    idx = (p / 100.0) * (n - 1)
    lo = int(idx)
    hi = lo + 1
    if hi >= n:
        return sorted_values[-1]
    return sorted_values[lo] * (1 - (idx - lo)) + sorted_values[hi] * (idx - lo)


def _print_latency_report(
    label: str,
    latencies_ms: list[float],
    slo_p95_ms: float | None = None,
) -> None:
    if not latencies_ms:
        print(f"  {label}: no data")
        return

    n = len(latencies_ms)
    s = sorted(latencies_ms)
    mean = statistics.mean(latencies_ms)
    p50 = _pct(s, 50)
    p95 = _pct(s, 95)
    p99 = _pct(s, 99)
    rps = 1000.0 / mean if mean > 0 else 0.0

    slo_note = ""
    if slo_p95_ms is not None:
        met = "✅" if p95 <= slo_p95_ms else "⚠️ "
        slo_note = f"  {met} SLO p95 ≤ {slo_p95_ms:.0f} ms — actual {p95:.1f} ms"

    print(f"\n  {label}  (n={n})")
    print(f"    min     {s[0]:.1f} ms")
    print(f"    mean    {mean:.1f} ms")
    print(f"    p50     {p50:.1f} ms")
    print(f"    p95     {p95:.1f} ms")
    print(f"    p99     {p99:.1f} ms")
    print(f"    max     {s[-1]:.1f} ms")
    print(f"    ~RPS    {rps:.1f} req/s  (sequential, single client)")
    if slo_note:
        print(slo_note)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="AlertIQ API performance benchmark")
    parser.add_argument(
        "--base-url",
        required=True,
        help="Base URL of the deployed API (e.g. http://localhost:8080)",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=50,
        help="Number of requests per endpoint (default: 50)",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=5,
        help="Number of warm-up requests (excluded from results) per endpoint (default: 5)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Number of alerts per batch request (default: 100)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="HTTP request timeout in seconds (default: 60)",
    )
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    print(f"\nAlertIQ Performance Benchmark")
    print(f"  Target : {base_url}")
    print(f"  Warmup : {args.warmup} requests per endpoint")
    print(f"  N      : {args.iterations} requests per endpoint")
    print(f"  Batch  : {args.batch_size} alerts per batch request")
    print(f"{'─' * 60}")

    try:
        with httpx.Client(base_url=base_url, timeout=args.timeout) as client:

            # Verify connectivity.
            try:
                resp = client.get("/health")
                data = resp.json()
                model_loaded = data.get("model_loaded", False)
                print(f"\n  /health → {resp.status_code}  model_loaded={model_loaded}")
                if not model_loaded:
                    print(
                        "  [WARNING] Model is not loaded.  Scoring endpoints "
                        "will return 503.  Latency reflects error-path only."
                    )
            except httpx.RequestError as exc:
                print(f"\n  ERROR: Cannot reach {base_url}: {exc}")
                sys.exit(1)

            # ── Warm up /score ─────────────────────────────────────── #
            if args.warmup > 0:
                print(f"\n  Warming up /score ({args.warmup} requests)…")
                _measure_latencies(
                    client, "POST", "/score",
                    _single_payload, args.warmup, "warmup/score"
                )

            # ── Benchmark /score ───────────────────────────────────── #
            print(f"\n  Benchmarking POST /score ({args.iterations} requests)…")
            single_latencies = _measure_latencies(
                client, "POST", "/score",
                _single_payload, args.iterations, "POST /score"
            )

            # ── Warm up /score/batch ───────────────────────────────── #
            if args.warmup > 0:
                print(f"\n  Warming up /score/batch ({args.warmup} requests)…")
                _measure_latencies(
                    client, "POST", "/score/batch",
                    lambda i: _batch_payload(args.batch_size, i),
                    args.warmup, "warmup/score/batch"
                )

            # ── Benchmark /score/batch ─────────────────────────────── #
            print(f"\n  Benchmarking POST /score/batch  "
                  f"(batch_size={args.batch_size}, {args.iterations} requests)…")
            batch_latencies = _measure_latencies(
                client, "POST", "/score/batch",
                lambda i: _batch_payload(args.batch_size, i),
                args.iterations, "POST /score/batch"
            )

            # ── Benchmark /health ──────────────────────────────────── #
            print(f"\n  Benchmarking GET /health ({args.iterations} requests)…")
            health_latencies = _measure_latencies(
                client, "GET", "/health",
                None, args.iterations, "GET /health"
            )

    except KeyboardInterrupt:
        print("\n  Interrupted.")
        sys.exit(0)

    # ── Results ───────────────────────────────────────────────────── #
    print(f"\n{'═' * 60}")
    print("  Latency Report")
    print(f"{'═' * 60}")

    _print_latency_report("GET /health", health_latencies)
    _print_latency_report(
        "POST /score  (single alert)", single_latencies, _SLO_SINGLE_P95_MS
    )
    _print_latency_report(
        f"POST /score/batch  ({args.batch_size} alerts per request)",
        batch_latencies, _SLO_BATCH_P95_MS,
    )

    # Per-alert latency inside a batch.
    if batch_latencies and args.batch_size > 0:
        per_alert = [ms / args.batch_size for ms in batch_latencies]
        _print_latency_report(
            f"POST /score/batch  (per-alert amortised, batch_size={args.batch_size})",
            per_alert,
        )

    print(f"\n{'─' * 60}")
    print(
        "  SLO targets are informational.  This benchmark measures single-client\n"
        "  sequential latency.  Cloud Run adds cold-start overhead on the first\n"
        "  request; subsequent requests from a warm instance are faster.\n"
        "  For concurrent load testing, use locust or k6.\n"
    )


if __name__ == "__main__":
    main()
