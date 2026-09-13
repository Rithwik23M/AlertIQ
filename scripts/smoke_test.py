#!/usr/bin/env python3
"""
AlertIQ Smoke Test
==================

Post-deployment smoke tests for the AlertIQ scoring API.

Runs a minimal set of checks against a live API instance to confirm that the
deployment succeeded, the model loaded, and the scoring endpoints respond
correctly.  Not a substitute for the full pytest suite — designed to complete
in under 30 seconds from a fresh Cloud Run cold start.

Usage
-----
    python scripts/smoke_test.py --base-url https://alertiq-api-staging.run.app
    python scripts/smoke_test.py --base-url http://localhost:8080
    python scripts/smoke_test.py --base-url http://localhost:8080 --timeout 60

Exit codes
----------
    0   All checks passed.
    1   One or more checks failed.

Dependencies
------------
    pip install httpx
"""

from __future__ import annotations

import argparse
import sys
import time
import json
from typing import Any

try:
    import httpx
except ImportError:
    print("ERROR: httpx is required.  Install it with: pip install httpx")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Minimal valid score request
# ---------------------------------------------------------------------------

_SAMPLE_FEATURES: dict[str, Any] = {
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

_SAMPLE_SINGLE_REQUEST = {
    "alert_id": "smoke-test-single-001",
    "schema_version": 1,
    "features": _SAMPLE_FEATURES,
}

_SAMPLE_BATCH_REQUEST = {
    "batch_id": "smoke-test-batch-001",
    "alerts": [
        {
            "alert_id": f"smoke-test-batch-{i:03d}",
            "schema_version": 1,
            "features": _SAMPLE_FEATURES,
        }
        for i in range(5)
    ],
}


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

class SmokeTestResult:
    def __init__(self, name: str) -> None:
        self.name = name
        self.passed = False
        self.message = ""
        self.duration_ms = 0.0

    def ok(self, message: str = "", duration_ms: float = 0.0) -> "SmokeTestResult":
        self.passed = True
        self.message = message
        self.duration_ms = duration_ms
        return self

    def fail(self, message: str, duration_ms: float = 0.0) -> "SmokeTestResult":
        self.passed = False
        self.message = message
        self.duration_ms = duration_ms
        return self

    def __str__(self) -> str:
        icon = "✅" if self.passed else "❌"
        suffix = f"  [{self.duration_ms:.0f} ms]" if self.duration_ms else ""
        return f"  {icon} {self.name}: {self.message}{suffix}"


def run_smoke_tests(base_url: str, timeout: int) -> list[SmokeTestResult]:
    base_url = base_url.rstrip("/")
    results: list[SmokeTestResult] = []

    with httpx.Client(base_url=base_url, timeout=timeout) as client:

        # ── 1. GET /health ─────────────────────────────────────────── #
        r = SmokeTestResult("GET /health")
        try:
            t0 = time.perf_counter()
            resp = client.get("/health")
            ms = (time.perf_counter() - t0) * 1000
            if resp.status_code != 200:
                results.append(r.fail(f"HTTP {resp.status_code}", ms))
            else:
                data = resp.json()
                status = data.get("status", "unknown")
                model_loaded = data.get("model_loaded", False)
                if status not in ("ok", "degraded"):
                    results.append(r.fail(f"Unexpected status: {status!r}", ms))
                elif not model_loaded:
                    results.append(r.fail(
                        f"Model not loaded (status={status!r}). "
                        "Deploy a trained model artifact.", ms
                    ))
                else:
                    results.append(r.ok(
                        f"status={status!r} model_version={data.get('model_version')!r}", ms
                    ))
        except httpx.RequestError as exc:
            results.append(r.fail(f"Request error: {exc}"))

        # ── 2. GET /metrics ─────────────────────────────────────────── #
        r = SmokeTestResult("GET /metrics")
        try:
            t0 = time.perf_counter()
            resp = client.get("/metrics")
            ms = (time.perf_counter() - t0) * 1000
            if resp.status_code != 200:
                results.append(r.fail(f"HTTP {resp.status_code}", ms))
            else:
                data = resp.json()
                uptime = data.get("uptime_seconds", -1)
                results.append(r.ok(f"uptime={uptime:.1f}s", ms))
        except httpx.RequestError as exc:
            results.append(r.fail(f"Request error: {exc}"))

        # ── 3. GET /model/info ──────────────────────────────────────── #
        r = SmokeTestResult("GET /model/info")
        try:
            t0 = time.perf_counter()
            resp = client.get("/model/info")
            ms = (time.perf_counter() - t0) * 1000
            if resp.status_code not in (200, 503):
                results.append(r.fail(f"HTTP {resp.status_code}", ms))
            elif resp.status_code == 503:
                results.append(r.ok("503 (no model loaded — expected in degraded mode)", ms))
            else:
                data = resp.json()
                results.append(r.ok(
                    f"model_version={data.get('model_version')!r} "
                    f"features={data.get('feature_count')}", ms
                ))
        except httpx.RequestError as exc:
            results.append(r.fail(f"Request error: {exc}"))

        # ── 4. POST /score ─────────────────────────────────────────── #
        r = SmokeTestResult("POST /score")
        try:
            t0 = time.perf_counter()
            resp = client.post("/score", json=_SAMPLE_SINGLE_REQUEST)
            ms = (time.perf_counter() - t0) * 1000
            if resp.status_code == 503:
                # Model not loaded; degrade gracefully rather than hard-fail.
                results.append(r.ok("503 (no model loaded — scoring skipped)", ms))
            elif resp.status_code != 200:
                results.append(r.fail(
                    f"HTTP {resp.status_code}: {resp.text[:200]}", ms
                ))
            else:
                data = resp.json()
                risk_score = data.get("risk_score")
                if risk_score is None:
                    results.append(r.fail("Missing risk_score in response", ms))
                elif not (0.0 <= risk_score <= 1.0):
                    results.append(r.fail(f"risk_score={risk_score} out of [0, 1]", ms))
                else:
                    # Confirm the disclaimer is present (human-in-the-loop check).
                    disclaimer = data.get("disclaimer", "")
                    has_disclaimer = len(disclaimer) > 10
                    results.append(r.ok(
                        f"risk_score={risk_score:.4f} disclaimer={'present' if has_disclaimer else 'MISSING'}",
                        ms,
                    ))
        except httpx.RequestError as exc:
            results.append(r.fail(f"Request error: {exc}"))

        # ── 5. POST /score/batch ───────────────────────────────────── #
        r = SmokeTestResult("POST /score/batch")
        try:
            t0 = time.perf_counter()
            resp = client.post("/score/batch", json=_SAMPLE_BATCH_REQUEST)
            ms = (time.perf_counter() - t0) * 1000
            if resp.status_code == 503:
                results.append(r.ok("503 (no model loaded — batch scoring skipped)", ms))
            elif resp.status_code != 200:
                results.append(r.fail(
                    f"HTTP {resp.status_code}: {resp.text[:200]}", ms
                ))
            else:
                data = resp.json()
                total = data.get("total", 0)
                succeeded = data.get("succeeded", 0)
                failed = data.get("failed", 0)
                expected = len(_SAMPLE_BATCH_REQUEST["alerts"])
                if total != expected:
                    results.append(r.fail(
                        f"total={total} expected={expected}", ms
                    ))
                elif failed > 0:
                    results.append(r.fail(
                        f"{failed}/{total} alerts failed", ms
                    ))
                else:
                    results.append(r.ok(
                        f"{succeeded}/{total} scored successfully", ms
                    ))
        except httpx.RequestError as exc:
            results.append(r.fail(f"Request error: {exc}"))

        # ── 6. POST /score — 413 on oversized payload ──────────────── #
        r = SmokeTestResult("POST /score — 413 on oversized payload")
        try:
            oversized = {
                "alert_id": "smoke-oversized",
                "schema_version": 1,
                # 12 MB of padding to exceed the default 10 MB limit.
                "features": {"padding": "x" * (12 * 1024 * 1024)},
            }
            t0 = time.perf_counter()
            resp = client.post("/score", content=json.dumps(oversized).encode())
            ms = (time.perf_counter() - t0) * 1000
            if resp.status_code == 413:
                results.append(r.ok("Correctly rejected with 413", ms))
            else:
                results.append(r.fail(
                    f"Expected 413, got {resp.status_code}", ms
                ))
        except httpx.RequestError as exc:
            results.append(r.fail(f"Request error: {exc}"))

    return results


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="AlertIQ post-deployment smoke tests")
    parser.add_argument(
        "--base-url",
        required=True,
        help="Base URL of the deployed API (e.g. https://alertiq-api-staging.run.app)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="HTTP request timeout in seconds (default: 30)",
    )
    args = parser.parse_args()

    print(f"\nAlertIQ Smoke Tests — {args.base_url}\n{'─' * 60}")

    results = run_smoke_tests(args.base_url, args.timeout)

    for result in results:
        print(result)

    passed = sum(1 for r in results if r.passed)
    total = len(results)
    print(f"\n{'─' * 60}")
    print(f"Result: {passed}/{total} checks passed")

    if passed < total:
        failed_names = [r.name for r in results if not r.passed]
        print(f"Failed: {', '.join(failed_names)}")
        sys.exit(1)
    else:
        print("✅ All smoke tests passed — deployment looks healthy")
        sys.exit(0)


if __name__ == "__main__":
    main()
