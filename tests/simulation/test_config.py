"""
Tests for SimulationConfig validation.

Covers: valid config, invalid dates, date ordering,
        population mix sum, typology weight constraints,
        extreme parameter values.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from alertiq.simulation.config import (
    PopulationMix,
    SimulationConfig,
    TMSThresholds,
    TypologyWeights,
)


class TestPopulationMix:
    def test_default_sums_to_one(self):
        mix = PopulationMix()
        total = mix.low_risk + mix.medium_risk + mix.high_risk + mix.active_ml
        assert abs(total - 1.0) < 1e-9

    def test_custom_valid(self):
        mix = PopulationMix(low_risk=0.50, medium_risk=0.30, high_risk=0.15, active_ml=0.05)
        assert abs(mix.low_risk + mix.medium_risk + mix.high_risk + mix.active_ml - 1.0) < 1e-9

    def test_rejects_sum_not_one(self):
        with pytest.raises(ValidationError, match="sum to 1.0"):
            PopulationMix(low_risk=0.50, medium_risk=0.30, high_risk=0.10, active_ml=0.05)

    def test_rejects_negative(self):
        with pytest.raises(ValidationError):
            PopulationMix(low_risk=-0.10, medium_risk=0.60, high_risk=0.30, active_ml=0.20)

    def test_rejects_above_one(self):
        with pytest.raises(ValidationError):
            PopulationMix(low_risk=1.50, medium_risk=0.0, high_risk=0.0, active_ml=0.0)


class TestTypologyWeights:
    def test_normalised_sums_to_one(self):
        w = TypologyWeights()
        norms = w.normalised()
        assert abs(sum(norms.values()) - 1.0) < 1e-9

    def test_all_zero_rejected(self):
        with pytest.raises(ValidationError, match="non-zero"):
            TypologyWeights(
                structuring=0, shell_company=0, real_estate=0,
                trade_based=0, cash_intensive=0, professional_ml=0,
                virtual_assets=0, cross_border=0,
            )

    def test_partial_zero_valid(self):
        """Setting some weights to zero is allowed (typology disabled)."""
        w = TypologyWeights(structuring=1.0, shell_company=0.0,
                            real_estate=0.0, trade_based=0.0,
                            cash_intensive=0.0, professional_ml=0.0,
                            virtual_assets=0.0, cross_border=0.0)
        assert w.normalised()["structuring"] == pytest.approx(1.0)


class TestSimulationConfig:
    def test_default_is_valid(self):
        cfg = SimulationConfig()
        assert cfg.seed == 42
        assert cfg.n_accounts == 1_000

    def test_simulation_days(self):
        cfg = SimulationConfig(start_date="2023-01-01", end_date="2023-12-31")
        assert cfg.simulation_days() == 364

    def test_frozen(self):
        cfg = SimulationConfig()
        with pytest.raises(Exception):  # pydantic frozen raises
            cfg.seed = 100  # type: ignore

    def test_invalid_date_format(self):
        with pytest.raises(ValidationError, match="ISO date"):
            SimulationConfig(start_date="01-01-2023")

    def test_start_must_be_before_end(self):
        with pytest.raises(ValidationError, match="before end_date"):
            SimulationConfig(start_date="2023-12-31", end_date="2023-01-01")

    def test_start_equals_end_rejected(self):
        with pytest.raises(ValidationError, match="before end_date"):
            SimulationConfig(start_date="2023-06-15", end_date="2023-06-15")

    def test_n_accounts_min(self):
        cfg = SimulationConfig(n_accounts=10)
        assert cfg.n_accounts == 10

    def test_n_accounts_too_small(self):
        with pytest.raises(ValidationError):
            SimulationConfig(n_accounts=5)

    def test_seed_boundaries(self):
        SimulationConfig(seed=0)
        SimulationConfig(seed=2**31 - 1)

    def test_seed_out_of_range(self):
        with pytest.raises(ValidationError):
            SimulationConfig(seed=-1)

    def test_extreme_daily_mean(self):
        """Very large or very small txn_daily_mean must remain positive."""
        cfg = SimulationConfig(txn_daily_mean=0.001, txn_daily_std=0.0)
        assert cfg.txn_daily_mean > 0

    def test_tms_thresholds_defaults(self):
        thr = TMSThresholds()
        assert thr.ctr_threshold == 10_000.0
        assert thr.large_cash_threshold == 8_000.0
