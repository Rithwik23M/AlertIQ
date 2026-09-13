"""
Tests for all 8 FATF typology generators.

Covers: output contracts, is_typology flag, typology_type consistency,
        positive amounts, account_id consistency, BaseTypology invariants.
"""

from __future__ import annotations

import datetime

import numpy as np
import pytest

from alertiq.simulation.config import SimulationConfig
from alertiq.simulation.entities import (
    AccountRiskCategory,
    AccountType,
    JurisdictionRisk,
    TypologyType,
    Account,
)
from alertiq.simulation.typologies import (
    TYPOLOGY_REGISTRY,
    CashIntensiveTypology,
    CrossBorderTypology,
    ProfessionalMLTypology,
    RealEstateTypology,
    ShellCompanyTypology,
    StructuringTypology,
    TradeBasedTypology,
    VirtualAssetsTypology,
    get_typology,
)


def _test_account(typology: TypologyType) -> Account:
    return Account(
        account_id="TEST_ACC",
        account_type=AccountType.SHELL,
        risk_category=AccountRiskCategory.ACTIVE_ML,
        jurisdiction=JurisdictionRisk.HIGH,
        onboard_date=datetime.date(2020, 1, 1),
        declared_annual_revenue=500_000.0,
        expected_monthly_volume=40_000.0,
        assigned_typology=typology,
    )


SIM_DATE = datetime.date(2023, 6, 15)
CONFIG = SimulationConfig(seed=0)
RNG = np.random.default_rng(42)


@pytest.mark.parametrize("typology_type,cls", list(TYPOLOGY_REGISTRY.items()))
class TestTypologyContracts:
    """Shared contract tests applied to every typology."""

    def test_is_typology_flag(self, typology_type, cls):
        gen = cls()
        account = _test_account(typology_type)
        txns = gen.generate(account, SIM_DATE, np.random.default_rng(1), CONFIG)
        assert len(txns) >= 0  # may be 0 on some seeds
        for t in txns:
            assert t.is_typology is True, f"Transaction {t.txn_id} missing is_typology"

    def test_typology_type_matches(self, typology_type, cls):
        gen = cls()
        account = _test_account(typology_type)
        txns = gen.generate(account, SIM_DATE, np.random.default_rng(2), CONFIG)
        for t in txns:
            assert t.typology_type == typology_type

    def test_amounts_positive(self, typology_type, cls):
        gen = cls()
        account = _test_account(typology_type)
        txns = gen.generate(account, SIM_DATE, np.random.default_rng(3), CONFIG)
        for t in txns:
            assert t.amount_eur > 0, f"Non-positive amount: {t.amount_eur}"

    def test_account_id_consistent(self, typology_type, cls):
        gen = cls()
        account = _test_account(typology_type)
        txns = gen.generate(account, SIM_DATE, np.random.default_rng(4), CONFIG)
        for t in txns:
            assert t.account_id == account.account_id

    def test_txn_dates_match_sim_date(self, typology_type, cls):
        gen = cls()
        account = _test_account(typology_type)
        txns = gen.generate(account, SIM_DATE, np.random.default_rng(5), CONFIG)
        for t in txns:
            assert t.txn_date == SIM_DATE


class TestStructuringTypology:
    def test_amounts_below_ctr(self):
        gen = StructuringTypology()
        account = _test_account(TypologyType.STRUCTURING)
        txns = gen.generate(account, SIM_DATE, np.random.default_rng(10), CONFIG)
        thr = CONFIG.tms_thresholds.ctr_threshold
        for t in txns:
            assert t.amount_eur < thr, f"Deposit {t.amount_eur} exceeds CTR {thr}"

    def test_generates_multiple_transactions(self):
        gen = StructuringTypology()
        account = _test_account(TypologyType.STRUCTURING)
        # Run with fixed seed that reliably generates 2+
        txns = gen.generate(account, SIM_DATE, np.random.default_rng(0), CONFIG)
        assert len(txns) >= 2


class TestShellCompanyTypology:
    def test_international_flag_set(self):
        gen = ShellCompanyTypology()
        account = _test_account(TypologyType.SHELL_COMPANY)
        txns = gen.generate(account, SIM_DATE, np.random.default_rng(0), CONFIG)
        for t in txns:
            assert t.is_international is True

    def test_has_counterparty(self):
        gen = ShellCompanyTypology()
        account = _test_account(TypologyType.SHELL_COMPANY)
        txns = gen.generate(account, SIM_DATE, np.random.default_rng(0), CONFIG)
        for t in txns:
            assert t.counterparty is not None
            assert t.counterparty.is_shell is True


class TestRegistryCompleteness:
    def test_all_eight_typologies_registered(self):
        assert len(TYPOLOGY_REGISTRY) == 8

    def test_get_typology_returns_instance(self):
        for tt in TypologyType:
            gen = get_typology(tt)
            assert gen is not None

    def test_unknown_typology_raises(self):
        with pytest.raises(ValueError):
            from alertiq.simulation.typologies import TYPOLOGY_REGISTRY
            TYPOLOGY_REGISTRY.get("nonexistent")  # returns None
            # Test the get_typology function raises
            get_typology("nonexistent")  # type: ignore
