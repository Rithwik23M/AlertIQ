"""
Tests for account population generator.

Covers: count correctness, risk category distribution,
        determinism, account field validity, extreme parameters.
"""

from __future__ import annotations

import pytest

from alertiq.simulation.config import PopulationMix, SimulationConfig
from alertiq.simulation.entities import AccountRiskCategory, TypologyType
from alertiq.simulation.population import generate_account_population


class TestPopulationSize:
    def test_exact_count(self):
        cfg = SimulationConfig(n_accounts=100)
        accounts = generate_account_population(cfg)
        assert len(accounts) == 100

    def test_minimum_population(self):
        cfg = SimulationConfig(n_accounts=10)
        accounts = generate_account_population(cfg)
        assert len(accounts) == 10

    def test_large_population(self):
        cfg = SimulationConfig(n_accounts=5_000)
        accounts = generate_account_population(cfg)
        assert len(accounts) == 5_000


class TestPopulationDeterminism:
    def test_same_seed_same_output(self):
        cfg = SimulationConfig(seed=7, n_accounts=100)
        pop1 = generate_account_population(cfg)
        pop2 = generate_account_population(cfg)
        for a1, a2 in zip(pop1, pop2):
            assert a1.account_id == a2.account_id
            assert a1.risk_category == a2.risk_category
            assert a1.account_type == a2.account_type
            assert a1.jurisdiction == a2.jurisdiction
            assert a1.declared_annual_revenue == a2.declared_annual_revenue

    def test_different_seed_different_output(self):
        cfg1 = SimulationConfig(seed=1, n_accounts=100)
        cfg2 = SimulationConfig(seed=2, n_accounts=100)
        pop1 = generate_account_population(cfg1)
        pop2 = generate_account_population(cfg2)
        # Not all accounts should be identical
        mismatches = sum(
            1 for a1, a2 in zip(pop1, pop2)
            if a1.risk_category != a2.risk_category
        )
        assert mismatches > 0


class TestRiskCategoryDistribution:
    def test_approximate_mix(self):
        cfg = SimulationConfig(seed=42, n_accounts=2_000)
        accounts = generate_account_population(cfg)
        mix = cfg.population_mix

        counts = {rc: 0 for rc in AccountRiskCategory}
        for acc in accounts:
            counts[acc.risk_category] += 1

        n = len(accounts)
        # Allow 3% tolerance around expected proportions
        tolerance = 0.03
        assert abs(counts[AccountRiskCategory.LOW_RISK] / n - mix.low_risk) < tolerance
        assert abs(counts[AccountRiskCategory.MEDIUM_RISK] / n - mix.medium_risk) < tolerance
        assert abs(counts[AccountRiskCategory.HIGH_RISK] / n - mix.high_risk) < tolerance
        assert abs(counts[AccountRiskCategory.ACTIVE_ML] / n - mix.active_ml) < tolerance

    def test_total_equals_n_accounts(self):
        cfg = SimulationConfig(seed=5, n_accounts=1_000)
        accounts = generate_account_population(cfg)
        from collections import Counter
        counts = Counter(acc.risk_category for acc in accounts)
        assert sum(counts.values()) == 1_000

    def test_custom_mix_honoured(self):
        mix = PopulationMix(low_risk=0.0, medium_risk=0.0, high_risk=0.0, active_ml=1.0)
        cfg = SimulationConfig(n_accounts=100, population_mix=mix)
        accounts = generate_account_population(cfg)
        assert all(acc.risk_category == AccountRiskCategory.ACTIVE_ML for acc in accounts)


class TestAccountFields:
    def test_unique_account_ids(self):
        cfg = SimulationConfig(n_accounts=500)
        accounts = generate_account_population(cfg)
        ids = [acc.account_id for acc in accounts]
        assert len(ids) == len(set(ids))

    def test_all_revenues_positive(self):
        cfg = SimulationConfig(n_accounts=200)
        accounts = generate_account_population(cfg)
        assert all(acc.declared_annual_revenue > 0 for acc in accounts)

    def test_all_monthly_volumes_positive(self):
        cfg = SimulationConfig(n_accounts=200)
        accounts = generate_account_population(cfg)
        assert all(acc.expected_monthly_volume > 0 for acc in accounts)

    def test_active_ml_has_typology(self):
        mix = PopulationMix(low_risk=0.0, medium_risk=0.0, high_risk=0.0, active_ml=1.0)
        cfg = SimulationConfig(n_accounts=50, population_mix=mix)
        accounts = generate_account_population(cfg)
        for acc in accounts:
            assert acc.assigned_typology is not None
            assert isinstance(acc.assigned_typology, TypologyType)

    def test_non_active_ml_has_no_typology(self):
        mix = PopulationMix(low_risk=1.0, medium_risk=0.0, high_risk=0.0, active_ml=0.0)
        cfg = SimulationConfig(n_accounts=50, population_mix=mix)
        accounts = generate_account_population(cfg)
        for acc in accounts:
            assert acc.assigned_typology is None

    def test_onboard_date_before_sim_start(self):
        import datetime
        cfg = SimulationConfig(n_accounts=100, start_date="2023-01-01")
        accounts = generate_account_population(cfg)
        sim_start = datetime.date(2023, 1, 1)
        for acc in accounts:
            assert acc.onboard_date <= sim_start
