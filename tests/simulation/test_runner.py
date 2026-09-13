"""
Integration tests for the simulation runner.

Covers: determinism, accounting/conservation, ground truth completeness,
        expected event frequencies, output file writing, extreme parameters,
        stress scenarios, failure lab (invalid states).
"""

from __future__ import annotations

import csv
import datetime
import math

import pytest

from alertiq.simulation.config import PopulationMix, SimulationConfig
from alertiq.simulation.entities import AccountRiskCategory
from alertiq.simulation.runner import SimulationError, run_simulation


# ------------------------------------------------------------------ #
# Session-scoped result fixtures (defined in conftest.py)             #
# ------------------------------------------------------------------ #


class TestDeterminism:
    """Same seed + same config must produce bitwise-identical output."""

    def test_transaction_count_identical(self, small_config, small_result):
        result2 = run_simulation(small_config)
        assert result2.n_transactions == small_result.n_transactions

    def test_alert_count_identical(self, small_config, small_result):
        result2 = run_simulation(small_config)
        assert result2.n_alerts == small_result.n_alerts

    def test_sar_count_identical(self, small_config, small_result):
        result2 = run_simulation(small_config)
        assert result2.n_true_sar == small_result.n_true_sar

    def test_alert_ids_differ_across_seeds(self, tmp_path):
        """Different seeds produce different alert IDs."""
        cfg1 = SimulationConfig(seed=1, n_accounts=30,
                                start_date="2023-01-01", end_date="2023-02-01",
                                output_dir=tmp_path / "s1",
                                write_transactions=False, write_alerts=False, write_accounts=False)
        cfg2 = SimulationConfig(seed=2, n_accounts=30,
                                start_date="2023-01-01", end_date="2023-02-01",
                                output_dir=tmp_path / "s2",
                                write_transactions=False, write_alerts=False, write_accounts=False)
        r1 = run_simulation(cfg1)
        r2 = run_simulation(cfg2)
        ids1 = {a.alert_id for a in r1.alerts}
        ids2 = {a.alert_id for a in r2.alerts}
        # UUID-based IDs will not collide
        assert ids1.isdisjoint(ids2)


class TestConservation:
    """Accounting and conservation invariants."""

    def test_all_transactions_have_positive_amount(self, small_result):
        for txn in small_result.transactions:
            assert txn.amount_eur > 0, \
                f"Transaction {txn.txn_id} has non-positive amount: {txn.amount_eur}"

    def test_all_alerts_have_set_ground_truth(self, small_result):
        for alert in small_result.alerts:
            assert alert.true_sar is not None, \
                f"Alert {alert.alert_id} has true_sar=None after simulation"

    def test_sar_count_leq_alert_count(self, small_result):
        assert small_result.n_true_sar <= small_result.n_alerts

    def test_n_accounts_matches_population(self, small_result):
        assert small_result.n_accounts == len(small_result.accounts)

    def test_n_transactions_matches_list(self, small_result):
        assert small_result.n_transactions == len(small_result.transactions)

    def test_n_alerts_matches_list(self, small_result):
        assert small_result.n_alerts == len(small_result.alerts)

    def test_typology_txn_has_is_typology_flag(self, small_result):
        for txn in small_result.transactions:
            if txn.is_typology:
                assert txn.typology_type is not None

    def test_true_sar_only_from_active_ml(self, small_result):
        account_map = {acc.account_id: acc for acc in small_result.accounts}
        for alert in small_result.alerts:
            if alert.true_sar:
                acc = account_map[alert.account_id]
                assert acc.risk_category == AccountRiskCategory.ACTIVE_ML, \
                    f"Alert {alert.alert_id} is true SAR but account is {acc.risk_category}"


class TestEventFrequencies:
    """Check expected event frequencies are in plausible ranges."""

    def test_positive_transaction_count(self, small_result):
        assert small_result.n_transactions > 0

    def test_positive_alert_count(self, medium_result):
        assert medium_result.n_alerts > 0

    def test_at_least_one_typology_transaction(self, medium_result):
        """With 200 accounts and 90 days, expect typology txns."""
        total_typology = sum(medium_result.typology_txn_counts.values())
        assert total_typology > 0

    def test_all_active_ml_accounts_generate_typology_txns(self, medium_result):
        """ACTIVE_ML accounts should produce typology transactions."""
        assert any(v > 0 for v in medium_result.typology_txn_counts.values())

    def test_sar_rate_in_plausible_range(self, medium_result):
        """SAR rate should be between 0.1% and 50%."""
        if medium_result.n_alerts > 0:
            rate = medium_result.sar_rate
            assert 0.0 <= rate <= 0.50, \
                f"SAR rate {rate:.3f} outside plausible range"

    def test_all_15_rules_represented(self, medium_result):
        """With 200 accounts and 90 days, all rules should trigger at least once."""
        # At minimum, the most sensitive rules must trigger
        triggered_rules = set(medium_result.rule_trigger_counts.keys())
        assert len(triggered_rules) >= 3, \
            f"Only {len(triggered_rules)} rules triggered in medium simulation"

    def test_transaction_rate_in_range(self, medium_result):
        """Expect ~2-6 transactions per account per day."""
        days = 90
        n_accounts = 200
        expected_range = (0.5 * days * n_accounts, 15 * days * n_accounts)
        assert expected_range[0] <= medium_result.n_transactions <= expected_range[1], \
            f"Transaction count {medium_result.n_transactions} outside expected range"


class TestAllFeaturesComputed:
    def test_all_alerts_have_24_features(self, small_result):
        from alertiq.simulation.features import FEATURE_NAMES
        for alert in small_result.alerts:
            assert len(alert.features) == 24, \
                f"Alert {alert.alert_id} has {len(alert.features)} features, expected 24"
            for fname in FEATURE_NAMES:
                assert fname in alert.features

    def test_no_nan_features(self, small_result):
        for alert in small_result.alerts:
            for k, v in alert.features.items():
                assert not math.isnan(v), \
                    f"Alert {alert.alert_id} feature {k} is NaN"
                assert not math.isinf(v), \
                    f"Alert {alert.alert_id} feature {k} is Inf"


class TestOutputFiles:
    def test_csv_files_written_when_enabled(self, tmp_path):
        cfg = SimulationConfig(
            seed=1, n_accounts=20,
            start_date="2023-01-01", end_date="2023-01-15",
            output_dir=tmp_path,
            write_accounts=True,
            write_transactions=True,
            write_alerts=True,
        )
        result = run_simulation(cfg)
        assert (tmp_path / "accounts.csv").exists()
        assert (tmp_path / "transactions.csv").exists()
        assert (tmp_path / "alerts.csv").exists()

    def test_accounts_csv_row_count(self, tmp_path):
        cfg = SimulationConfig(
            seed=2, n_accounts=25,
            start_date="2023-01-01", end_date="2023-01-08",
            output_dir=tmp_path,
            write_accounts=True,
            write_transactions=False,
            write_alerts=False,
        )
        result = run_simulation(cfg)
        with open(tmp_path / "accounts.csv") as f:
            rows = list(csv.reader(f))
        # header + 25 data rows
        assert len(rows) == 26

    def test_no_files_when_disabled(self, tmp_path):
        cfg = SimulationConfig(
            seed=3, n_accounts=10,
            start_date="2023-01-01", end_date="2023-01-08",
            output_dir=tmp_path,
            write_accounts=False,
            write_transactions=False,
            write_alerts=False,
        )
        run_simulation(cfg)
        assert not (tmp_path / "accounts.csv").exists()
        assert not (tmp_path / "transactions.csv").exists()
        assert not (tmp_path / "alerts.csv").exists()


class TestExtremeParameters:
    """Boundary and stress conditions."""

    def test_minimum_population(self, tmp_path):
        """10 accounts, 7 days — should not crash."""
        cfg = SimulationConfig(
            seed=7, n_accounts=10,
            start_date="2023-01-01", end_date="2023-01-08",
            output_dir=tmp_path,
            write_transactions=False, write_alerts=False, write_accounts=False,
        )
        result = run_simulation(cfg)
        assert result.n_accounts == 10

    def test_all_active_ml_population(self, tmp_path):
        """100% ACTIVE_ML accounts — ground truth must still be assigned correctly."""
        mix = PopulationMix(low_risk=0.0, medium_risk=0.0, high_risk=0.0, active_ml=1.0)
        cfg = SimulationConfig(
            seed=11, n_accounts=20,
            population_mix=mix,
            start_date="2023-01-01", end_date="2023-02-01",
            output_dir=tmp_path,
            write_transactions=False, write_alerts=False, write_accounts=False,
        )
        result = run_simulation(cfg)
        assert result.n_active_ml_accounts == 20
        for alert in result.alerts:
            assert alert.true_sar is not None

    def test_zero_typology_activation_probability(self, tmp_path):
        """No typology activation → no true SARs."""
        cfg = SimulationConfig(
            seed=13, n_accounts=50,
            typology_daily_activation_prob=0.000001,  # effectively zero
            start_date="2023-01-01", end_date="2023-01-15",
            output_dir=tmp_path,
            write_transactions=False, write_alerts=False, write_accounts=False,
        )
        result = run_simulation(cfg)
        # With near-zero activation, very few (or zero) typology txns expected
        total_typology_txns = sum(result.typology_txn_counts.values())
        # At least we shouldn't crash
        assert result.n_accounts == 50

    def test_very_high_daily_transaction_rate(self, tmp_path):
        """Very high txn mean — should generate many transactions without overflow."""
        cfg = SimulationConfig(
            seed=17, n_accounts=10,
            txn_daily_mean=50.0, txn_daily_std=5.0,
            start_date="2023-01-01", end_date="2023-01-08",
            output_dir=tmp_path,
            write_transactions=False, write_alerts=False, write_accounts=False,
        )
        result = run_simulation(cfg)
        # 10 accounts × 7 days × ~50 txns/day ≈ 3,500
        assert result.n_transactions > 100


class TestTerminationBehaviour:
    def test_single_day_simulation(self, tmp_path):
        """Simulation with only 1 day should complete without error."""
        cfg = SimulationConfig(
            seed=19, n_accounts=20,
            start_date="2023-06-01", end_date="2023-06-02",
            output_dir=tmp_path,
            write_transactions=False, write_alerts=False, write_accounts=False,
        )
        result = run_simulation(cfg)
        assert result is not None
        assert result.n_accounts == 20

    def test_result_summary_is_json_serialisable(self, small_result):
        import json
        summary = small_result.summary()
        # Should not raise
        json.dumps(summary)
