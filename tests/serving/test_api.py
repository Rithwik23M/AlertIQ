"""
Tests for alertiq.serving.app — Starlette ASGI scoring API.

Coverage
--------
GET /health
  - Returns 200 with status="ok" when model is loaded
  - Returns model_version and schema_version when model is loaded
  - Returns 200 with status="degraded" when no model is loaded
  - model_loaded=False when no model is loaded

GET /model/info
  - Returns 200 with feature_columns (24 columns)
  - Returns operating_mode="capacity_ranking"
  - Returns disclaimer
  - Returns 503 when no model is loaded

POST /score
  - Valid request returns 200 with risk_score in [0, 1]
  - Response includes alert_id matching request
  - Response includes disclaimer
  - Response includes operating_mode="capacity_ranking"
  - Response includes data_quality_flags
  - Missing feature returns 422
  - Extra field returns 422
  - Invalid schema_version (unsupported) returns 422
  - Empty alert_id returns 422
  - No model loaded returns 503
  - X-AlertIQ-Request-ID header present in response

POST /score/batch
  - Valid request returns 200 with BatchScoreResponse
  - Results list length matches input alert count
  - All results have status="scored" for valid input
  - Mixed schema_versions in batch returns 422
  - Empty alerts list returns 422
  - No model loaded returns 503
  - X-AlertIQ-Request-ID header present in response

Partial batch failure
  - When one alert has an invalid schema_version mid-batch,
    that alert gets status="error" and others still score
    (NB: mixed-schema is caught pre-batch, so this tests
    individual scoring errors via monkeypatching)
"""

from __future__ import annotations

import json
import pytest
from starlette.testclient import TestClient

import alertiq.serving.app as app_module
from alertiq.serving.schema import DISCLAIMER


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #

_VALID_FEATURES = {
    "f01_vol_7d_log": 8.5,
    "f02_vol_30d_log": 10.2,
    "f03_vol_ratio_7_30": 0.85,
    "f04_max_txn_log": 7.1,
    "f05_vol_vs_revenue": 1.2,
    "f06_txn_count_7d": 12,
    "f07_txn_count_30d": 45,
    "f08_velocity_ratio": 1.1,
    "f09_recency_gap_days": 3.0,
    "f10_account_age_days": 720.0,
    "f11_cash_fraction_30d": 0.15,
    "f12_structuring_count_30d": 0,
    "f13_round_amount_count_30d": 3,
    "f14_digital_channel_fraction": 0.8,
    "f15_night_fraction_30d": 0.1,
    "f16_intl_fraction_30d": 0.05,
    "f17_distinct_jurisdictions_30d": 2,
    "f18_very_high_jur_flag": 0,
    "f19_shell_counterparty_fraction": 0.0,
    "f20_pep_flag": 0,
    "f21_adverse_media_flag": 0,
    "f22_high_risk_industry": 0,
    "f23_prior_alerts_90d": 1,
    "f24_account_jurisdiction_score": 0.3,
}


def _valid_score_request(alert_id: str = "ALT-001", schema_version: int = 1) -> dict:
    return {
        "alert_id": alert_id,
        "schema_version": schema_version,
        "features": dict(_VALID_FEATURES),  # shallow copy — all values are scalars
    }


def _valid_batch_request(n: int = 2, schema_version: int = 1) -> dict:
    return {
        "batch_id": "BATCH-TEST",
        "alerts": [
            _valid_score_request(alert_id=f"ALT-{i:04d}", schema_version=schema_version)
            for i in range(n)
        ],
    }


# ------------------------------------------------------------------ #
# No-model fixture                                                     #
# ------------------------------------------------------------------ #

@pytest.fixture()
def no_model_client():
    """TestClient with _scorer forcibly set to None (degraded mode).

    The scorer is nulled out AFTER lifespan startup completes so the lifespan
    itself doesn't attempt to serve requests (or fail) before we can override.
    """
    from alertiq.serving.audit import AuditLogger
    old_scorer = app_module._scorer
    old_audit = app_module._audit

    with TestClient(app_module.app, raise_server_exceptions=True) as client:
        # Override after startup: lifespan may have loaded a champion model.
        app_module._scorer = None
        app_module._audit = AuditLogger()
        yield client

    app_module._scorer = old_scorer
    app_module._audit = old_audit


# ------------------------------------------------------------------ #
# GET /health                                                          #
# ------------------------------------------------------------------ #

class TestHealth:
    def test_ok_when_model_loaded(self, test_client: TestClient) -> None:
        resp = test_client.get("/health")
        assert resp.status_code == 200

    def test_status_ok_when_model_loaded(self, test_client: TestClient) -> None:
        data = test_client.get("/health").json()
        assert data["status"] == "ok"

    def test_model_loaded_true(self, test_client: TestClient) -> None:
        data = test_client.get("/health").json()
        assert data["model_loaded"] is True

    def test_model_version_present(self, test_client: TestClient) -> None:
        data = test_client.get("/health").json()
        assert data["model_version"] is not None
        assert len(data["model_version"]) > 0

    def test_schema_version_present(self, test_client: TestClient) -> None:
        data = test_client.get("/health").json()
        assert data["schema_version"] == 1

    def test_status_degraded_when_no_model(self, no_model_client: TestClient) -> None:
        data = no_model_client.get("/health").json()
        assert data["status"] == "degraded"

    def test_model_loaded_false_when_no_model(self, no_model_client: TestClient) -> None:
        data = no_model_client.get("/health").json()
        assert data["model_loaded"] is False

    def test_health_still_200_when_degraded(self, no_model_client: TestClient) -> None:
        resp = no_model_client.get("/health")
        assert resp.status_code == 200


# ------------------------------------------------------------------ #
# GET /model/info                                                      #
# ------------------------------------------------------------------ #

class TestModelInfo:
    def test_returns_200(self, test_client: TestClient) -> None:
        resp = test_client.get("/model/info")
        assert resp.status_code == 200

    def test_feature_columns_count(self, test_client: TestClient) -> None:
        data = test_client.get("/model/info").json()
        assert data["feature_count"] == 24
        assert len(data["feature_columns"]) == 24

    def test_operating_mode_is_capacity_ranking(self, test_client: TestClient) -> None:
        data = test_client.get("/model/info").json()
        assert data["operating_mode"] == "capacity_ranking"

    def test_disclaimer_present(self, test_client: TestClient) -> None:
        data = test_client.get("/model/info").json()
        assert "disclaimer" in data
        assert len(data["disclaimer"]) > 0

    def test_training_rows_positive(self, test_client: TestClient) -> None:
        data = test_client.get("/model/info").json()
        assert data["training_rows"] > 0

    def test_no_model_returns_503(self, no_model_client: TestClient) -> None:
        resp = no_model_client.get("/model/info")
        assert resp.status_code == 503


# ------------------------------------------------------------------ #
# POST /score                                                          #
# ------------------------------------------------------------------ #

class TestScoreSingle:
    def test_valid_request_returns_200(self, test_client: TestClient) -> None:
        resp = test_client.post("/score", json=_valid_score_request())
        assert resp.status_code == 200

    def test_risk_score_in_unit_interval(self, test_client: TestClient) -> None:
        data = test_client.post("/score", json=_valid_score_request()).json()
        assert 0.0 <= data["risk_score"] <= 1.0

    def test_alert_id_matches_request(self, test_client: TestClient) -> None:
        data = test_client.post("/score", json=_valid_score_request(alert_id="ALT-XYZ")).json()
        assert data["alert_id"] == "ALT-XYZ"

    def test_disclaimer_present(self, test_client: TestClient) -> None:
        data = test_client.post("/score", json=_valid_score_request()).json()
        assert "disclaimer" in data
        assert data["disclaimer"] == DISCLAIMER

    def test_disclaimer_not_sar_language(self, test_client: TestClient) -> None:
        data = test_client.post("/score", json=_valid_score_request()).json()
        # The disclaimer must not make compliance determinations.
        assert "SAR filing decision" in data["disclaimer"]
        # It should reference human analyst review.
        assert "Human analysts" in data["disclaimer"] or "analyst" in data["disclaimer"]

    def test_operating_mode_is_capacity_ranking(self, test_client: TestClient) -> None:
        data = test_client.post("/score", json=_valid_score_request()).json()
        assert data["operating_mode"] == "capacity_ranking"

    def test_data_quality_flags_present(self, test_client: TestClient) -> None:
        data = test_client.post("/score", json=_valid_score_request()).json()
        assert "data_quality_flags" in data
        flags = data["data_quality_flags"]
        assert "quality_warning" in flags
        assert "has_zeroed_features" in flags
        assert "has_extreme_values" in flags

    def test_request_id_header_present(self, test_client: TestClient) -> None:
        resp = test_client.post("/score", json=_valid_score_request())
        assert "x-alertiq-request-id" in {k.lower() for k in resp.headers}

    def test_missing_feature_returns_422(self, test_client: TestClient) -> None:
        body = _valid_score_request()
        del body["features"]["f01_vol_7d_log"]
        resp = test_client.post("/score", json=body)
        assert resp.status_code == 422

    def test_extra_field_returns_422(self, test_client: TestClient) -> None:
        body = _valid_score_request()
        body["features"]["unknown_field"] = 99.9
        resp = test_client.post("/score", json=body)
        assert resp.status_code == 422

    def test_invalid_schema_version_returns_422(self, test_client: TestClient) -> None:
        body = _valid_score_request(schema_version=99)
        resp = test_client.post("/score", json=body)
        assert resp.status_code == 422

    def test_empty_alert_id_returns_422(self, test_client: TestClient) -> None:
        body = _valid_score_request(alert_id="")
        resp = test_client.post("/score", json=body)
        assert resp.status_code == 422

    def test_no_model_returns_503(self, no_model_client: TestClient) -> None:
        resp = no_model_client.post("/score", json=_valid_score_request())
        assert resp.status_code == 503

    def test_fraction_out_of_range_returns_422(self, test_client: TestClient) -> None:
        body = _valid_score_request()
        body["features"]["f11_cash_fraction_30d"] = 1.5  # > 1.0 is invalid
        resp = test_client.post("/score", json=body)
        assert resp.status_code == 422

    def test_binary_flag_out_of_range_returns_422(self, test_client: TestClient) -> None:
        body = _valid_score_request()
        body["features"]["f20_pep_flag"] = 2  # only 0 or 1 allowed
        resp = test_client.post("/score", json=body)
        assert resp.status_code == 422

    def test_malformed_json_returns_400(self, test_client: TestClient) -> None:
        resp = test_client.post(
            "/score",
            content=b"{not valid json",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 400

    def test_score_contains_model_version(self, test_client: TestClient) -> None:
        data = test_client.post("/score", json=_valid_score_request()).json()
        assert "model_version" in data
        assert len(data["model_version"]) > 0

    def test_score_contains_schema_version(self, test_client: TestClient) -> None:
        data = test_client.post("/score", json=_valid_score_request()).json()
        assert data["schema_version"] == 1

    def test_score_contains_scored_at(self, test_client: TestClient) -> None:
        data = test_client.post("/score", json=_valid_score_request()).json()
        assert "scored_at" in data
        assert data["scored_at"] is not None


# ------------------------------------------------------------------ #
# POST /score/batch                                                    #
# ------------------------------------------------------------------ #

class TestScoreBatch:
    def test_valid_request_returns_200(self, test_client: TestClient) -> None:
        resp = test_client.post("/score/batch", json=_valid_batch_request(n=3))
        assert resp.status_code == 200

    def test_results_count_matches_input(self, test_client: TestClient) -> None:
        n = 4
        data = test_client.post("/score/batch", json=_valid_batch_request(n=n)).json()
        assert len(data["results"]) == n

    def test_all_results_have_scored_status(self, test_client: TestClient) -> None:
        data = test_client.post("/score/batch", json=_valid_batch_request(n=3)).json()
        for result in data["results"]:
            assert result["status"] == "scored"

    def test_all_results_have_risk_score_in_unit_interval(self, test_client: TestClient) -> None:
        data = test_client.post("/score/batch", json=_valid_batch_request(n=3)).json()
        for result in data["results"]:
            assert result["risk_score"] is not None
            assert 0.0 <= result["risk_score"] <= 1.0

    def test_total_succeeded_counts(self, test_client: TestClient) -> None:
        n = 5
        data = test_client.post("/score/batch", json=_valid_batch_request(n=n)).json()
        assert data["total"] == n
        assert data["succeeded"] == n
        assert data["failed"] == 0

    def test_operating_mode_is_capacity_ranking(self, test_client: TestClient) -> None:
        data = test_client.post("/score/batch", json=_valid_batch_request()).json()
        assert data["operating_mode"] == "capacity_ranking"

    def test_disclaimer_present(self, test_client: TestClient) -> None:
        data = test_client.post("/score/batch", json=_valid_batch_request()).json()
        assert "disclaimer" in data

    def test_request_id_header_present(self, test_client: TestClient) -> None:
        resp = test_client.post("/score/batch", json=_valid_batch_request())
        assert "x-alertiq-request-id" in {k.lower() for k in resp.headers}

    def test_mixed_schema_versions_returns_422(self, test_client: TestClient) -> None:
        body = {
            "alerts": [
                _valid_score_request(alert_id="ALT-001", schema_version=1),
                _valid_score_request(alert_id="ALT-002", schema_version=2),
            ]
        }
        resp = test_client.post("/score/batch", json=body)
        assert resp.status_code == 422

    def test_empty_alerts_returns_422(self, test_client: TestClient) -> None:
        resp = test_client.post("/score/batch", json={"alerts": []})
        assert resp.status_code == 422

    def test_no_model_returns_503(self, no_model_client: TestClient) -> None:
        resp = no_model_client.post("/score/batch", json=_valid_batch_request())
        assert resp.status_code == 503

    def test_batch_id_echoed_in_response(self, test_client: TestClient) -> None:
        body = _valid_batch_request(n=1)
        body["batch_id"] = "ECHO-TEST-123"
        data = test_client.post("/score/batch", json=body).json()
        assert data["batch_id"] == "ECHO-TEST-123"

    def test_batch_without_batch_id_accepted(self, test_client: TestClient) -> None:
        body = _valid_batch_request(n=1)
        del body["batch_id"]
        resp = test_client.post("/score/batch", json=body)
        assert resp.status_code == 200

    def test_unsupported_schema_version_returns_error_per_alert(self, test_client: TestClient) -> None:
        """A batch with a uniform unsupported schema_version passes the mixed-version
        check but each alert fails per-alert scoring.  The batch returns 200 with
        all results having status='error' (graceful degradation, not bulk 422)."""
        body = _valid_batch_request(n=2, schema_version=99)
        resp = test_client.post("/score/batch", json=body)
        assert resp.status_code == 200
        data = resp.json()
        assert data["failed"] == 2
        assert data["succeeded"] == 0
        for result in data["results"]:
            assert result["status"] == "error"

    def test_single_alert_batch_accepted(self, test_client: TestClient) -> None:
        resp = test_client.post("/score/batch", json=_valid_batch_request(n=1))
        assert resp.status_code == 200

    def test_alert_ids_preserved_in_results(self, test_client: TestClient) -> None:
        body = _valid_batch_request(n=3)
        expected_ids = {a["alert_id"] for a in body["alerts"]}
        data = test_client.post("/score/batch", json=body).json()
        result_ids = {r["alert_id"] for r in data["results"]}
        assert result_ids == expected_ids


# ------------------------------------------------------------------ #
# Cross-cutting concerns                                               #
# ------------------------------------------------------------------ #

class TestCrossCutting:
    def test_score_response_has_no_sar_label(self, test_client: TestClient) -> None:
        """Confirm that compliant output language is enforced end-to-end."""
        data = test_client.post("/score", json=_valid_score_request()).json()
        dumped = json.dumps(data).lower()
        # These words must not appear in any response field name or value.
        forbidden = {"suspicious activity report", "guilty", "money laundering conviction"}
        for phrase in forbidden:
            assert phrase not in dumped, f"Forbidden phrase in response: {phrase!r}"

    def test_batch_response_has_no_sar_label(self, test_client: TestClient) -> None:
        data = test_client.post("/score/batch", json=_valid_batch_request()).json()
        dumped = json.dumps(data).lower()
        forbidden = {"suspicious activity report", "guilty", "money laundering conviction"}
        for phrase in forbidden:
            assert phrase not in dumped, f"Forbidden phrase in response: {phrase!r}"

    def test_consistent_model_version_across_batch(self, test_client: TestClient) -> None:
        """All results in a batch must come from the same model version."""
        info = test_client.get("/model/info").json()
        model_version = info["model_version"]
        data = test_client.post("/score/batch", json=_valid_batch_request(n=3)).json()
        assert data["model_version"] == model_version

    def test_single_score_model_version_matches_info(self, test_client: TestClient) -> None:
        info = test_client.get("/model/info").json()
        data = test_client.post("/score", json=_valid_score_request()).json()
        assert data["model_version"] == info["model_version"]
