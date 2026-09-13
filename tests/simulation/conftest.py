"""Shared fixtures for simulation tests."""

from __future__ import annotations

import datetime
from pathlib import Path

import pytest

from alertiq.simulation.config import SimulationConfig, TMSThresholds
from alertiq.simulation.entities import (
    Account,
    AccountRiskCategory,
    AccountType,
    Channel,
    JurisdictionRisk,
    Transaction,
    TransactionType,
    TypologyType,
    new_id,
)
from alertiq.simulation.population import generate_account_population
from alertiq.simulation.runner import run_simulation


# ------------------------------------------------------------------ #
# Standard small config for fast unit tests                           #
# ------------------------------------------------------------------ #

@pytest.fixture(scope="session")
def small_config(tmp_path_factory) -> SimulationConfig:
    """50 accounts, 30-day period.  Session-scoped for speed."""
    out = tmp_path_factory.mktemp("sim_out")
    return SimulationConfig(
        seed=99,
        n_accounts=50,
        start_date="2023-01-01",
        end_date="2023-01-31",
        output_dir=out,
        write_transactions=False,
        write_alerts=False,
        write_accounts=False,
    )


@pytest.fixture(scope="session")
def medium_config(tmp_path_factory) -> SimulationConfig:
    """200 accounts, 90-day period — used for frequency and coverage tests."""
    out = tmp_path_factory.mktemp("sim_out_med")
    return SimulationConfig(
        seed=42,
        n_accounts=200,
        start_date="2023-01-01",
        end_date="2023-04-01",
        output_dir=out,
        write_transactions=False,
        write_alerts=False,
        write_accounts=False,
    )


@pytest.fixture(scope="session")
def small_result(small_config):
    """Run simulation once; reuse for all session-scoped tests."""
    return run_simulation(small_config)


@pytest.fixture(scope="session")
def medium_result(medium_config):
    return run_simulation(medium_config)


# ------------------------------------------------------------------ #
# Synthetic account fixtures                                           #
# ------------------------------------------------------------------ #

@pytest.fixture
def active_ml_account() -> Account:
    return Account(
        account_id="ACC_ML_001",
        account_type=AccountType.SHELL,
        risk_category=AccountRiskCategory.ACTIVE_ML,
        jurisdiction=JurisdictionRisk.HIGH,
        onboard_date=datetime.date(2020, 1, 1),
        declared_annual_revenue=500_000.0,
        expected_monthly_volume=40_000.0,
        assigned_typology=TypologyType.STRUCTURING,
    )


@pytest.fixture
def low_risk_account() -> Account:
    return Account(
        account_id="ACC_LR_001",
        account_type=AccountType.RETAIL,
        risk_category=AccountRiskCategory.LOW_RISK,
        jurisdiction=JurisdictionRisk.LOW,
        onboard_date=datetime.date(2015, 6, 15),
        declared_annual_revenue=30_000.0,
        expected_monthly_volume=2_500.0,
    )


@pytest.fixture
def sim_date() -> datetime.date:
    return datetime.date(2023, 6, 15)


def make_cash_deposit(
    account_id: str,
    amount: float,
    txn_date: datetime.date | None = None,
    hour: int = 10,
) -> Transaction:
    d = txn_date or datetime.date(2023, 6, 15)
    return Transaction(
        txn_id=new_id("TXN"),
        account_id=account_id,
        txn_date=d,
        txn_datetime=datetime.datetime.combine(d, datetime.time(hour, 0)),
        txn_type=TransactionType.CASH_DEPOSIT,
        channel=Channel.BRANCH,
        amount_eur=amount,
    )


def make_intl_wire(
    account_id: str,
    amount: float,
    jurisdiction: JurisdictionRisk = JurisdictionRisk.HIGH,
    txn_date: datetime.date | None = None,
) -> Transaction:
    from alertiq.simulation.entities import Counterparty
    d = txn_date or datetime.date(2023, 6, 15)
    cp = Counterparty(counterparty_id=new_id("CP"), jurisdiction=jurisdiction)
    return Transaction(
        txn_id=new_id("TXN"),
        account_id=account_id,
        txn_date=d,
        txn_datetime=datetime.datetime.combine(d, datetime.time(14, 0)),
        txn_type=TransactionType.INTERNATIONAL_WIRE,
        channel=Channel.ONLINE,
        amount_eur=amount,
        counterparty=cp,
        is_international=True,
        destination_jurisdiction=jurisdiction,
    )
