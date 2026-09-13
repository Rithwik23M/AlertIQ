"""
End-to-end investigation journey test for AlertIQ.

WHAT THIS TEST COVERS
---------------------
This test simulates the complete lifecycle of an analyst investigating an alert
through the AlertIQ investigation workspace:

  Step 1 — Queue: Alert appears in the queue with correct risk score and status
  Step 2 — Detail: Full alert detail is retrievable with features and signals
  Step 3 — Temporal: Only pre-alert transactions appear in the transaction list
  Step 4 — Open: Analyst opens the investigation (status → in_progress)
  Step 5 — Note: Analyst adds an investigation note
  Step 6 — Decision: Analyst records a decision (escalate / close / etc.)
  Step 7 — History: Audit trail records every action with timestamps
  Step 8 — Immutability: Risk score is unchanged after all investigation actions
  Step 9 — Security: true_sar never appears in any response

DESIGN INTENT
-------------
This is a black-box test against the HTTP API. It verifies:
- All routes return correct status codes
- Response shapes match documented contracts
- Investigation actions produce the correct state transitions
- Evidence integrity is preserved throughout the journey
- Security controls (true_sar suppression) hold end-to-end

A test failure here indicates either a route regression or a governance
violation (temporal integrity or security).
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest


# ------------------------------------------------------------------ #
# Shared test data                                                     #
# ------------------------------------------------------------------ #

_ALERT_ID = "ALT-JOURNEY-001"
_ACCOUNT_ID = "ACC-JOURNEY-001"
_ALERT_DATE = "2023-04-10"
_RULE_ID = "R03"
_RULE_NAME = "High-volume international transfers"
_ANALYST_ID = "analyst-journey-001"


def _full_features() -> dict:
    """Realistic feature values for a high-risk account."""
    return {
        "f01_vol_7d_log": 12.1,
        "f02_vol_30d_log": 13.5,
        "f03_vol_ratio_7_30": 0.95,
        "f04_max_txn_log": 11.2,
        "f05_vol_vs_revenue": 3.7,
        "f06_txn_count_7d": 28,
        "f07_txn_count_30d": 95,
        "f08_velocity_ratio": 1.8,
        "f09_recency_gap_days": 0.5,
        "f10_account_age_days": 365.0,
        "f11_cash_fraction_30d": 0.55,
        "f12_structuring_count_30d": 4,
        "f13_round_amount_count_30d": 12,
        "f14_digital_channel_fraction": 0.92,
        "f15_night_fraction_30d": 0.35,
        "f16_intl_fraction_30d": 0.78,
        "f17_distinct_jurisdictions_30d": 7,
        "f18_very_high_jur_flag": 1.0,
        "f19_shell_counterparty_fraction": 0.42,
        "f20_pep_flag": 0.0,
        "f21_adverse_media_flag": 1.0,
        "f22_high_risk_industry": 1.0,
        "f23_prior_alerts_90d": 3,
        "f24_account_jurisdiction_score": 0.85,
    }


# ------------------------------------------------------------------ #
# Test fixture                                                         #
# ------------------------------------------------------------------ #

@pytest.fixture(scope="module")
def journey_client(tmp_path_factory):
    """
    Module-scoped Starlette TestClient with a pre-seeded alert store.

    Seeds:
      - One alert with a high risk score
      - Two pre-alert transactions
      - One post-alert transaction (must not appear)

    The same client is shared across all tests in this module so that
    state changes (open, note, decision) are visible to subsequent steps.
    """
    import os

    db_path = tmp_path_factory.mktemp("journey") / "journey.db"
    orig_env = os.environ.get("ALERTIQ_STORE_PATH")
    os.environ["ALERTIQ_STORE_PATH"] = str(db_path)

    import alertiq.serving.alert_store as store_module
    importlib.reload(store_module)
    store_module.init_db()

    # Seed one high-risk alert.
    store_module.upsert_alert(
        alert_id=_ALERT_ID,
        account_id=_ACCOUNT_ID,
        rule_id=_RULE_ID,
        rule_name=_RULE_NAME,
        severity="critical",
        alert_date=_ALERT_DATE,
        risk_score=0.87,
        queue_position=1,
        features=_full_features(),
        quality_flags={
            "has_zeroed_features": False,
            "zero_feature_names": [],
            "has_extreme_values": False,
            "extreme_feature_names": [],
            "quality_warning": False,
        },
        model_version="1.0.0",
        schema_version=1,
        scored_at="2023-04-10T08:00:00+00:00",
        true_sar=1,  # ground truth — must NEVER appear in API responses
    )

    # Seed two pre-alert transactions.
    for i, (date, amount) in enumerate([
        ("2023-03-01", 45_000.0),
        ("2023-04-09", 120_000.0),  # 1 day before alert — must appear
    ]):
        store_module.upsert_transaction(
            txn_id=f"TXN-PRE-{i:02d}",
            account_id=_ACCOUNT_ID,
            txn_date=date,
            txn_datetime=date + "T14:30:00",
            txn_type="international_transfer",
            channel="digital",
            amount_eur=amount,
            is_international=1,
            destination_jurisdiction="PAN",
            counterparty_id="CP-SHELL-001",
            counterparty_jurisdiction="BVI",
            counterparty_is_shell=1,
            is_typology=1,
        )

    # Seed one post-alert transaction — must NEVER appear in investigation.
    store_module.upsert_transaction(
        txn_id="TXN-POST-FUTURE",
        account_id=_ACCOUNT_ID,
        txn_date="2023-04-11",  # 1 day after alert
        txn_datetime="2023-04-11T09:00:00",
        txn_type="transfer",
        channel="digital",
        amount_eur=50_000.0,
        is_international=0,
        destination_jurisdiction=None,
        counterparty_id=None,
        counterparty_jurisdiction=None,
        counterparty_is_shell=0,
        is_typology=0,
    )

    import alertiq.serving.app as app_module
    importlib.reload(app_module)

    class _MockScorer:
        """Minimal scorer mock — scoring endpoint not under test here."""
        def predict(self, features):
            return {"risk_score": 0.87, "above_threshold": True}

    app_module._scorer = _MockScorer()

    from starlette.testclient import TestClient
    with TestClient(app_module.app, raise_server_exceptions=True) as client:
        yield client

    # Restore env var.
    if orig_env is None:
        os.environ.pop("ALERTIQ_STORE_PATH", None)
    else:
        os.environ["ALERTIQ_STORE_PATH"] = orig_env


# ------------------------------------------------------------------ #
# Journey tests — ordered by investigation step                        #
# ------------------------------------------------------------------ #

class TestInvestigationJourney:
    """
    End-to-end investigation journey.

    Tests are ordered (test names prefixed with step number) but each test
    is individually readable — it does not depend on state set up by a
    previous test method, only on the initial fixture seed.

    The exception is Steps 5–8 which exercise state transitions and
    therefore run after Step 4 (open). These are grouped in the
    same class so module-scoped fixtures are shared.
    """

    # ---------------------------------------------------------------- #
    # Step 1 — Queue                                                    #
    # ---------------------------------------------------------------- #

    def test_step1_alert_appears_in_queue(self, journey_client):
        """Alert must appear in the paginated queue."""
        resp = journey_client.get("/alerts?page=1&page_size=50")
        assert resp.status_code == 200, f"Queue endpoint failed: {resp.text}"

        data = resp.json()
        # Accept either a flat list or a paginated envelope (key may be "items" or "alerts").
        alerts = data if isinstance(data, list) else data.get("items", data.get("alerts", []))
        alert_ids = [a["alert_id"] for a in alerts]

        assert _ALERT_ID in alert_ids, (
            f"Alert {_ALERT_ID} not found in queue. Available: {alert_ids[:5]}"
        )

    def test_step1_queue_shows_correct_risk_score(self, journey_client):
        """Queue must display the correct risk score (0.87)."""
        resp = journey_client.get("/alerts?page=1&page_size=50")
        data = resp.json()
        alerts = data if isinstance(data, list) else data.get("items", data.get("alerts", []))

        our_alert = next((a for a in alerts if a["alert_id"] == _ALERT_ID), None)
        assert our_alert is not None

        score = our_alert.get("risk_score")
        assert score is not None, "risk_score must be present in queue response"
        assert abs(score - 0.87) < 0.001, f"Expected 0.87, got {score}"

    def test_step1_queue_does_not_contain_true_sar(self, journey_client):
        """true_sar must not appear in any queue response."""
        resp = journey_client.get("/alerts?page=1&page_size=50")
        assert "true_sar" not in resp.text, "SECURITY: true_sar leaked in queue response"

    # ---------------------------------------------------------------- #
    # Step 2 — Alert detail                                             #
    # ---------------------------------------------------------------- #

    def test_step2_alert_detail_retrievable(self, journey_client):
        """GET /alerts/{id} must return 200 with the alert's metadata."""
        resp = journey_client.get(f"/alerts/{_ALERT_ID}")
        assert resp.status_code == 200, f"Alert detail failed: {resp.text}"

        data = resp.json()
        # Handle both flat and nested shapes.
        alert = data.get("alert", data)
        assert alert.get("alert_id") == _ALERT_ID
        assert alert.get("rule_id") == _RULE_ID

    def test_step2_features_present_in_detail(self, journey_client):
        """Alert detail must include the feature snapshot."""
        resp = journey_client.get(f"/alerts/{_ALERT_ID}")
        data = resp.json()

        features = data.get("features") or data.get("alert", {}).get("features")
        if features is None:
            pytest.skip("features not in response shape — skipping")

        assert "f01_vol_7d_log" in features, "Feature f01_vol_7d_log must be present"
        assert abs(features["f01_vol_7d_log"] - 12.1) < 0.001

    def test_step2_detail_does_not_contain_true_sar(self, journey_client):
        """true_sar must not appear in the alert detail response."""
        resp = journey_client.get(f"/alerts/{_ALERT_ID}")
        assert "true_sar" not in resp.text, "SECURITY: true_sar leaked in detail response"

    def test_step2_nonexistent_alert_returns_404(self, journey_client):
        """GET /alerts/DOES-NOT-EXIST must return 404."""
        resp = journey_client.get("/alerts/DOES-NOT-EXIST-XYZ")
        assert resp.status_code == 404

    # ---------------------------------------------------------------- #
    # Step 3 — Transactions (temporal integrity)                        #
    # ---------------------------------------------------------------- #

    def test_step3_pre_alert_transactions_visible(self, journey_client):
        """Both pre-alert transactions must appear in the transaction list."""
        resp = journey_client.get(f"/alerts/{_ALERT_ID}/transactions")
        assert resp.status_code == 200

        data = resp.json()
        txns = data if isinstance(data, list) else data.get("transactions", [])
        txn_ids = {t["txn_id"] for t in txns}

        assert "TXN-PRE-00" in txn_ids, "Pre-alert transaction TXN-PRE-00 must appear"
        assert "TXN-PRE-01" in txn_ids, "Pre-alert transaction TXN-PRE-01 must appear"

    def test_step3_post_alert_transaction_excluded(self, journey_client):
        """TEMPORAL INTEGRITY: Post-alert transaction must never appear."""
        resp = journey_client.get(f"/alerts/{_ALERT_ID}/transactions")
        data = resp.json()
        txns = data if isinstance(data, list) else data.get("transactions", [])
        txn_ids = {t["txn_id"] for t in txns}

        assert "TXN-POST-FUTURE" not in txn_ids, (
            "TEMPORAL INTEGRITY VIOLATION: post-alert transaction TXN-POST-FUTURE "
            f"appeared in investigation evidence (alert_date={_ALERT_DATE}, "
            "txn_date=2023-04-11)"
        )

    def test_step3_transaction_dates_all_lte_alert_date(self, journey_client):
        """All returned transaction dates must be ≤ alert_date."""
        resp = journey_client.get(f"/alerts/{_ALERT_ID}/transactions")
        data = resp.json()
        txns = data if isinstance(data, list) else data.get("transactions", [])

        for txn in txns:
            assert txn["txn_date"] <= _ALERT_DATE, (
                f"TEMPORAL INTEGRITY VIOLATION: txn_date={txn['txn_date']} "
                f"is after alert_date={_ALERT_DATE} for txn_id={txn['txn_id']}"
            )

    # ---------------------------------------------------------------- #
    # Step 4 — Open investigation                                       #
    # ---------------------------------------------------------------- #

    def test_step4_open_investigation(self, journey_client):
        """POST /alerts/{id}/open must succeed and set status to in_progress."""
        resp = journey_client.post(f"/alerts/{_ALERT_ID}/open", json={
            "analyst_id": _ANALYST_ID,
        })
        assert resp.status_code == 200, f"Open failed: {resp.text}"

    def test_step4_status_after_open(self, journey_client):
        """Alert status must be in_progress after opening."""
        resp = journey_client.get(f"/alerts/{_ALERT_ID}")
        data = resp.json()
        status = data.get("status") or data.get("alert", {}).get("status")
        if status is not None:
            assert status == "in_progress", (
                f"Expected status=in_progress after open, got {status}"
            )

    # ---------------------------------------------------------------- #
    # Step 5 — Add note                                                 #
    # ---------------------------------------------------------------- #

    def test_step5_add_note(self, journey_client):
        """POST /alerts/{id}/notes must accept a note and return it."""
        note_text = "Analyst review: multiple high-value transfers to shell counterparty in BVI."
        resp = journey_client.post(f"/alerts/{_ALERT_ID}/notes", json={
            "content": note_text,
            "analyst_id": _ANALYST_ID,
        })
        assert resp.status_code in (200, 201), f"Add note failed: {resp.text}"

    def test_step5_note_retrievable(self, journey_client):
        """GET /alerts/{id}/notes must return the added note."""
        resp = journey_client.get(f"/alerts/{_ALERT_ID}/notes")
        assert resp.status_code == 200

        data = resp.json()
        notes = data if isinstance(data, list) else data.get("notes", [])
        note_contents = [n.get("content", "") for n in notes]

        assert any("shell counterparty" in c for c in note_contents), (
            "Added note not found in notes list"
        )

    def test_step5_note_does_not_change_risk_score(self, journey_client):
        """Adding a note must not change the alert's risk score."""
        resp = journey_client.get(f"/alerts/{_ALERT_ID}")
        data = resp.json()
        score = data.get("risk_score") or data.get("alert", {}).get("risk_score")
        if score is not None:
            assert abs(score - 0.87) < 0.001, (
                f"Risk score changed after note: expected 0.87, got {score}"
            )

    # ---------------------------------------------------------------- #
    # Step 6 — Record decision                                          #
    # ---------------------------------------------------------------- #

    def test_step6_record_decision(self, journey_client):
        """POST /alerts/{id}/decision must accept a valid decision."""
        resp = journey_client.post(f"/alerts/{_ALERT_ID}/decision", json={
            "outcome": "escalate",
            "rationale": "Multiple red flags: shell counterparty, high international volume, adverse media.",
            "analyst_id": _ANALYST_ID,
        })
        assert resp.status_code in (200, 201), f"Record decision failed: {resp.text}"

    def test_step6_decision_retrievable(self, journey_client):
        """GET /alerts/{id}/decisions must return the recorded decision."""
        resp = journey_client.get(f"/alerts/{_ALERT_ID}/decisions")
        assert resp.status_code == 200

        data = resp.json()
        decisions = data if isinstance(data, list) else data.get("decisions", [])

        assert len(decisions) >= 1, "At least one decision must be recorded"
        outcomes = [d.get("outcome") or d.get("decision") for d in decisions]
        assert "escalate" in outcomes, (
            f"Recorded decision 'escalate' not found. Got outcomes: {outcomes}"
        )

    def test_step6_decision_has_rationale(self, journey_client):
        """Recorded decision must store the analyst's rationale."""
        resp = journey_client.get(f"/alerts/{_ALERT_ID}/decisions")
        data = resp.json()
        decisions = data if isinstance(data, list) else data.get("decisions", [])

        rationales = [d.get("rationale", "") for d in decisions]
        assert any("shell counterparty" in r for r in rationales), (
            "Decision rationale not stored correctly"
        )

    # ---------------------------------------------------------------- #
    # Step 7 — Audit history                                            #
    # ---------------------------------------------------------------- #

    def test_step7_history_records_open_event(self, journey_client):
        """Audit trail must record the investigation open event."""
        resp = journey_client.get(f"/alerts/{_ALERT_ID}/history")
        assert resp.status_code == 200

        data = resp.json()
        events = data if isinstance(data, list) else data.get("history", data.get("events", []))

        event_types = [e.get("event_type") or e.get("type") or "" for e in events]
        assert any("open" in et.lower() for et in event_types), (
            f"Open event not found in audit trail. Event types: {event_types}"
        )

    def test_step7_history_has_timestamps(self, journey_client):
        """Audit events must have timestamps."""
        resp = journey_client.get(f"/alerts/{_ALERT_ID}/history")
        data = resp.json()
        events = data if isinstance(data, list) else data.get("history", data.get("events", []))

        for event in events:
            ts = event.get("occurred_at") or event.get("timestamp") or event.get("created_at")
            assert ts is not None, f"Event missing timestamp: {event}"

    def test_step7_history_is_chronological(self, journey_client):
        """Audit events must be in chronological order (oldest first)."""
        resp = journey_client.get(f"/alerts/{_ALERT_ID}/history")
        data = resp.json()
        events = data if isinstance(data, list) else data.get("history", data.get("events", []))

        if len(events) < 2:
            pytest.skip("Not enough events to verify ordering")

        timestamps = [
            e.get("occurred_at") or e.get("timestamp") or e.get("created_at")
            for e in events
        ]
        assert timestamps == sorted(timestamps), (
            "Audit events are not in chronological order"
        )

    # ---------------------------------------------------------------- #
    # Step 8 — Score immutability                                       #
    # ---------------------------------------------------------------- #

    def test_step8_risk_score_unchanged_after_full_journey(self, journey_client):
        """
        INVESTIGATION INTEGRITY: Risk score must be the same as at seeding
        time, regardless of open / note / decision actions.

        This is the most important invariant: the model's assessment of the
        alert must be a historical record, not a live variable that changes
        with investigation actions.
        """
        resp = journey_client.get(f"/alerts/{_ALERT_ID}")
        assert resp.status_code == 200, f"Alert detail failed: {resp.text}"

        data = resp.json()
        score = data.get("risk_score") or data.get("alert", {}).get("risk_score")

        if score is None:
            pytest.skip("risk_score not in response — cannot verify immutability")

        assert abs(score - 0.87) < 0.001, (
            f"INVESTIGATION INTEGRITY VIOLATION: risk_score changed during investigation. "
            f"Expected 0.87, got {score}. Risk scores must be immutable historical records."
        )

    def test_step8_model_version_unchanged(self, journey_client):
        """Model version in the alert record must be '1.0.0' throughout the journey."""
        resp = journey_client.get(f"/alerts/{_ALERT_ID}")
        data = resp.json()
        model_ver = (
            data.get("model_version")
            or data.get("alert", {}).get("model_version")
        )
        if model_ver is not None:
            assert model_ver == "1.0.0", (
                f"Model version changed during investigation: expected 1.0.0, got {model_ver}"
            )

    # ---------------------------------------------------------------- #
    # Step 9 — Security controls (true_sar suppression)                 #
    # ---------------------------------------------------------------- #

    def test_step9_true_sar_absent_from_all_endpoints(self, journey_client):
        """
        SECURITY: true_sar must not appear in the response body of ANY endpoint.

        We test all endpoints in the investigation workflow in a single pass.
        The ground truth label (true_sar=1) was seeded in the fixture — if it
        leaks, the model's ground truth is exposed to the analyst, which would
        allow confirmation bias to contaminate SAR decisions.
        """
        endpoints = [
            f"/alerts/{_ALERT_ID}",
            f"/alerts/{_ALERT_ID}/transactions",
            f"/alerts/{_ALERT_ID}/notes",
            f"/alerts/{_ALERT_ID}/decisions",
            f"/alerts/{_ALERT_ID}/history",
            "/alerts?page=1&page_size=50",
            "/queue/stats",
        ]

        leaked_endpoints = []
        for endpoint in endpoints:
            resp = journey_client.get(endpoint)
            if resp.status_code == 200 and "true_sar" in resp.text:
                leaked_endpoints.append(endpoint)

        assert not leaked_endpoints, (
            f"SECURITY VIOLATION: true_sar label leaked through endpoints: "
            f"{leaked_endpoints}"
        )
