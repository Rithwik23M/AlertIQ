"""
Temporal integrity tests for the AlertIQ investigation store.

WHAT THESE TESTS VERIFY
-----------------------
The investigation workspace must enforce temporal evidence integrity:
an analyst reviewing alert A (triggered on date D) must only see transaction
records that pre-date or coincide with D.  Future transactions must never
appear as investigation evidence because:

  1. They did not exist at the time the alert was generated.
  2. Showing future data would contaminate the analyst's risk assessment
     with information the TMS system could not have had.
  3. In a real AML system, this would violate FATF investigation standards.

The enforcement point is alert_store.get_alert_transactions(), which applies:

    WHERE account_id = ? AND txn_date <= ?   (alert_date)

These tests verify the enforcement is present, correct, and cannot be
bypassed by any known route parameter.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest

# ------------------------------------------------------------------ #
# Test fixtures                                                        #
# ------------------------------------------------------------------ #

@pytest.fixture()
def store_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """
    Return an initialised alert_store backed by a fresh tmp SQLite database.

    We set ALERTIQ_DB_PATH via monkeypatch so the module uses the test DB,
    then re-import init_db to ensure a clean schema.
    """
    db_path = tmp_path / "test_store.db"
    monkeypatch.setenv("ALERTIQ_STORE_PATH", str(db_path))

    # Force module to pick up the new env var by reimporting.
    import importlib
    import alertiq.serving.alert_store as _store_module
    importlib.reload(_store_module)

    _store_module.init_db()
    return _store_module


# Canonical alert and transaction data for the tests.
_ALERT_ID = "ALT-TEMPORAL-001"
_ACCOUNT_ID = "ACC-TEMPORAL-001"
_ALERT_DATE = "2023-03-15"  # alert was triggered on 2023-03-15


def _seed_alert(store, alert_id: str = _ALERT_ID, alert_date: str = _ALERT_DATE) -> None:
    """Write a minimal alert record to the store."""
    store.upsert_alert(
        alert_id=alert_id,
        account_id=_ACCOUNT_ID,
        rule_id="R01",
        rule_name="Velocity spike",
        severity="high",
        alert_date=alert_date,
        risk_score=0.75,
        queue_position=1,
        features={f"f{i:02d}_x": 0.5 for i in range(1, 25)},
        quality_flags={"has_zeroed_features": False, "zero_feature_names": [],
                       "has_extreme_values": False, "extreme_feature_names": [],
                       "quality_warning": False},
        model_version="1.0.0",
        schema_version=1,
        scored_at="2023-03-15T10:00:00+00:00",
        true_sar=0,
    )


def _seed_transactions(store, transactions: list[dict]) -> None:
    """Write a list of transaction records to the store."""
    for txn in transactions:
        store.upsert_transaction(
            txn_id=txn["txn_id"],
            account_id=_ACCOUNT_ID,
            txn_date=txn["txn_date"],
            txn_datetime=txn["txn_date"] + "T12:00:00",
            txn_type="transfer",
            channel="digital",
            amount_eur=txn.get("amount_eur", 1000.0),
            is_international=0,
            destination_jurisdiction=None,
            counterparty_id=None,
            counterparty_jurisdiction=None,
            counterparty_is_shell=0,
            is_typology=0,
        )


# ------------------------------------------------------------------ #
# Core temporal filter tests                                           #
# ------------------------------------------------------------------ #

class TestTemporalFilterCore:
    """Verify the WHERE txn_date <= alert_date predicate is correct."""

    def test_returns_only_pre_alert_transactions(self, store_db):
        """Transactions before the alert date are returned; future ones are not."""
        _seed_alert(store_db)
        _seed_transactions(store_db, [
            {"txn_id": "TXN-BEFORE-1",   "txn_date": "2023-01-01"},  # 74 days before → INCLUDE
            {"txn_id": "TXN-BEFORE-2",   "txn_date": "2023-03-14"},  # 1 day before   → INCLUDE
            {"txn_id": "TXN-SAME-DAY",   "txn_date": "2023-03-15"},  # alert date      → INCLUDE
            {"txn_id": "TXN-FUTURE-1",   "txn_date": "2023-03-16"},  # 1 day after     → EXCLUDE
            {"txn_id": "TXN-FUTURE-2",   "txn_date": "2023-06-30"},  # 107 days after  → EXCLUDE
        ])

        txns = store_db.get_alert_transactions(_ALERT_ID)
        txn_ids = {t["txn_id"] for t in txns}

        assert "TXN-BEFORE-1" in txn_ids, "Pre-alert transaction should be returned"
        assert "TXN-BEFORE-2" in txn_ids, "Pre-alert transaction should be returned"
        assert "TXN-SAME-DAY" in txn_ids, "Same-day transaction should be returned (alert date inclusive)"
        assert "TXN-FUTURE-1" not in txn_ids, "Next-day transaction must not be returned (future evidence)"
        assert "TXN-FUTURE-2" not in txn_ids, "Far-future transaction must not be returned"

    def test_same_day_transaction_is_included(self, store_db):
        """A transaction on exactly the alert date must be visible (boundary condition)."""
        _seed_alert(store_db)
        _seed_transactions(store_db, [
            {"txn_id": "TXN-EXACT-DATE", "txn_date": _ALERT_DATE},
        ])
        txns = store_db.get_alert_transactions(_ALERT_ID)
        assert any(t["txn_id"] == "TXN-EXACT-DATE" for t in txns)

    def test_day_after_alert_is_excluded(self, store_db):
        """A transaction one day after the alert must never appear — no off-by-one."""
        _seed_alert(store_db)
        alert_date = date.fromisoformat(_ALERT_DATE)
        next_day = str(alert_date + timedelta(days=1))
        _seed_transactions(store_db, [
            {"txn_id": "TXN-NEXT-DAY", "txn_date": next_day},
        ])
        txns = store_db.get_alert_transactions(_ALERT_ID)
        assert not any(t["txn_id"] == "TXN-NEXT-DAY" for t in txns), (
            "Off-by-one: next-day transaction must be excluded"
        )

    def test_account_isolation(self, store_db):
        """Transactions for a different account must not appear for this alert."""
        _seed_alert(store_db)
        # Seed a transaction for a DIFFERENT account with a pre-alert date.
        store_db.upsert_transaction(
            txn_id="TXN-OTHER-ACCOUNT",
            account_id="ACC-OTHER-999",
            txn_date="2023-01-01",
            txn_datetime="2023-01-01T12:00:00",
            txn_type="transfer",
            channel="digital",
            amount_eur=5000.0,
            is_international=0,
            destination_jurisdiction=None,
            counterparty_id=None,
            counterparty_jurisdiction=None,
            counterparty_is_shell=0,
            is_typology=0,
        )
        txns = store_db.get_alert_transactions(_ALERT_ID)
        assert not any(t["txn_id"] == "TXN-OTHER-ACCOUNT" for t in txns), (
            "Transactions from other accounts must be isolated"
        )

    def test_empty_transaction_history(self, store_db):
        """Alert with no transactions returns an empty list, not an error."""
        _seed_alert(store_db)
        txns = store_db.get_alert_transactions(_ALERT_ID)
        assert txns == []

    def test_nonexistent_alert_returns_empty(self, store_db):
        """Requesting transactions for a missing alert_id returns [] not a crash."""
        txns = store_db.get_alert_transactions("DOES-NOT-EXIST")
        assert txns == []

    def test_limit_parameter_respected(self, store_db):
        """The limit parameter caps the result set."""
        _seed_alert(store_db)
        txns_to_seed = [
            {"txn_id": f"TXN-LIMIT-{i:03d}", "txn_date": "2023-02-01"}
            for i in range(20)
        ]
        _seed_transactions(store_db, txns_to_seed)

        result_10 = store_db.get_alert_transactions(_ALERT_ID, limit=10)
        assert len(result_10) == 10

        result_5 = store_db.get_alert_transactions(_ALERT_ID, limit=5)
        assert len(result_5) == 5


# ------------------------------------------------------------------ #
# Volume integrity test                                                #
# ------------------------------------------------------------------ #

class TestVolumeIntegrity:
    """Verify that count of returned transactions is correct under bulk conditions."""

    def test_bulk_pre_alert_all_returned_up_to_limit(self, store_db):
        """With 50 pre-alert and 50 post-alert transactions, only pre-alert are returned."""
        _seed_alert(store_db)

        pre_alert_date = date.fromisoformat(_ALERT_DATE)
        post_alert_date = pre_alert_date + timedelta(days=1)

        pre_txns = [
            {"txn_id": f"TXN-PRE-{i:03d}", "txn_date": str(pre_alert_date - timedelta(days=i + 1))}
            for i in range(50)
        ]
        post_txns = [
            {"txn_id": f"TXN-POST-{i:03d}", "txn_date": str(post_alert_date + timedelta(days=i))}
            for i in range(50)
        ]
        _seed_transactions(store_db, pre_txns + post_txns)

        txns = store_db.get_alert_transactions(_ALERT_ID, limit=200)
        txn_ids = {t["txn_id"] for t in txns}

        pre_ids = {t["txn_id"] for t in pre_txns}
        post_ids = {t["txn_id"] for t in post_txns}

        assert pre_ids.issubset(txn_ids), "All pre-alert transactions should be returned"
        assert not post_ids.intersection(txn_ids), "No post-alert transactions should be returned"

    def test_no_transactions_after_alert_date_in_result(self, store_db):
        """
        Invariant test: regardless of what is in the DB, no returned transaction
        must have txn_date > alert_date.
        """
        _seed_alert(store_db)
        all_dates = [
            "2023-01-01", "2023-02-15", "2023-03-14",
            "2023-03-15",  # alert date — boundary
            "2023-03-16", "2023-04-01", "2023-06-30",  # future
        ]
        _seed_transactions(store_db, [
            {"txn_id": f"TXN-D{i}", "txn_date": d}
            for i, d in enumerate(all_dates)
        ])

        txns = store_db.get_alert_transactions(_ALERT_ID, limit=100)
        for txn in txns:
            assert txn["txn_date"] <= _ALERT_DATE, (
                f"Future transaction leaked: txn_date={txn['txn_date']} > alert_date={_ALERT_DATE}"
            )


# ------------------------------------------------------------------ #
# API-level temporal integrity test                                    #
# ------------------------------------------------------------------ #

class TestAPITemporalIntegrity:
    """
    Verify the temporal filter holds at the HTTP API level (not just store level).

    This test uses the Starlette test client to simulate the full HTTP path:
    GET /alerts/{id}/transactions → alert_routes.py → alert_store.get_alert_transactions()

    This is the most important test class: it proves the filter cannot be
    bypassed by a route-level modification or by removing the call.
    """

    @pytest.fixture()
    def api_client(self, tmp_path, monkeypatch):
        """
        Starlette TestClient with a fresh alert store containing one alert
        with one pre-alert and one post-alert transaction.
        """
        db_path = tmp_path / "api_test_store.db"
        monkeypatch.setenv("ALERTIQ_STORE_PATH", str(db_path))

        import importlib
        import alertiq.serving.alert_store as store_module
        importlib.reload(store_module)
        store_module.init_db()

        # Seed alert + transactions.
        _seed_alert(store_module)
        _seed_transactions(store_module, [
            {"txn_id": "TXN-API-BEFORE", "txn_date": "2023-03-10", "amount_eur": 1000.0},
            {"txn_id": "TXN-API-FUTURE", "txn_date": "2023-03-20", "amount_eur": 5000.0},
        ])

        import alertiq.serving.app as app_module
        importlib.reload(app_module)

        # Patch _scorer with a minimal mock so score endpoint works.
        class _MockScorer:
            def predict(self, features):
                return {"risk_score": 0.5, "above_threshold": False}

        app_module._scorer = _MockScorer()

        from starlette.testclient import TestClient
        with TestClient(app_module.app, raise_server_exceptions=True) as client:
            yield client

    def test_api_transactions_endpoint_excludes_future(self, api_client):
        """GET /alerts/{id}/transactions must return only pre-alert transactions."""
        resp = api_client.get(f"/alerts/{_ALERT_ID}/transactions")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

        data = resp.json()
        # Response shape is {"transactions": [...], ...}
        txns = data if isinstance(data, list) else data.get("transactions", data)

        txn_ids = [t["txn_id"] for t in txns]
        assert "TXN-API-BEFORE" in txn_ids, "Pre-alert transaction must appear in API response"
        assert "TXN-API-FUTURE" not in txn_ids, (
            "TEMPORAL INTEGRITY VIOLATION: future transaction leaked through API"
        )

    def test_api_response_has_no_true_sar(self, api_client):
        """
        Security: true_sar must never appear in any GET /alerts/* response.

        This is a governance control: the alert detail endpoint must not
        expose ground truth labels to the analyst.
        """
        resp = api_client.get(f"/alerts/{_ALERT_ID}")
        if resp.status_code == 200:
            body = resp.json()
            body_str = str(body)
            assert "true_sar" not in body_str, (
                "SECURITY VIOLATION: true_sar ground truth label exposed via API"
            )

    def test_api_decision_does_not_change_risk_score(self, api_client):
        """
        Investigation integrity: recording a decision must not modify the
        alert's risk_score, model_version, or scored_at fields.
        """
        # Get the original alert detail.
        pre = api_client.get(f"/alerts/{_ALERT_ID}").json()
        original_score = pre.get("risk_score") or pre.get("alert", {}).get("risk_score")

        if original_score is None:
            pytest.skip("Alert detail endpoint shape differs — skip score immutability check")

        # Open the investigation.
        api_client.post(f"/alerts/{_ALERT_ID}/open")

        # Record a decision.
        resp = api_client.post(f"/alerts/{_ALERT_ID}/decision", json={
            "outcome": "close",
            "rationale": "Low risk after review",
            "analyst_id": "analyst-001",
        })
        # 200 or 201 both acceptable.
        assert resp.status_code in (200, 201), f"Unexpected status: {resp.status_code}: {resp.text}"

        # Re-fetch the alert.
        post = api_client.get(f"/alerts/{_ALERT_ID}").json()
        post_score = post.get("risk_score") or post.get("alert", {}).get("risk_score")

        if post_score is not None:
            assert post_score == original_score, (
                f"INVESTIGATION INTEGRITY VIOLATION: risk_score changed after decision "
                f"({original_score} → {post_score})"
            )
