"""
Daily transaction generator.

For each day in the simulation period, this module:
  1. Generates routine transactions for each account (based on account type)
  2. Generates typology transactions for ACTIVE_ML accounts that are
     activated on that day
  3. Returns the combined, date-ordered list

Isolation guarantee
-------------------
This module knows about:  Account, Transaction, SimulationConfig, typologies
This module does NOT access: ground truth, TMS rules, features, alerts

Seeding strategy
----------------
Each account gets a child RNG seeded with (config.seed, "txn", account_idx, day_idx).
This ensures that:
  * Adding accounts does not change transaction generation for existing accounts
  * Changing the simulation period does not change within-period transactions
"""

from __future__ import annotations

import datetime
from typing import Iterator

import numpy as np

from .config import SimulationConfig
from .entities import (
    Account,
    AccountRiskCategory,
    Channel,
    Counterparty,
    JurisdictionRisk,
    Transaction,
    TransactionType,
    new_id,
)
from .typologies import get_typology

# ------------------------------------------------------------------ #
# Channel / transaction type probability tables                       #
# ------------------------------------------------------------------ #

_CHANNEL_PROBS = [0.15, 0.40, 0.35, 0.10]  # BRANCH, ONLINE, MOBILE, ATM
_CHANNELS = [Channel.BRANCH, Channel.ONLINE, Channel.MOBILE, Channel.ATM]

_TXN_TYPE_PROBS = [0.10, 0.05, 0.35, 0.20, 0.25, 0.05]
_TXN_TYPES = [
    TransactionType.CASH_DEPOSIT,
    TransactionType.CASH_WITHDRAWAL,
    TransactionType.DOMESTIC_WIRE,
    TransactionType.INTERNAL_TRANSFER,
    TransactionType.CARD_PAYMENT,
    TransactionType.LOAN_REPAYMENT,
]

# Probability that a routine transaction is international (per account risk)
_INTL_PROB = {
    AccountRiskCategory.LOW_RISK: 0.02,
    AccountRiskCategory.MEDIUM_RISK: 0.06,
    AccountRiskCategory.HIGH_RISK: 0.15,
    AccountRiskCategory.ACTIVE_ML: 0.25,
}


def _counterparty_jurisdiction(
    rng: np.random.Generator,
    account: Account,
) -> JurisdictionRisk:
    """Sample destination jurisdiction weighted by account risk."""
    risk = account.risk_category
    if risk == AccountRiskCategory.LOW_RISK:
        probs = [0.85, 0.12, 0.03, 0.00]
    elif risk == AccountRiskCategory.MEDIUM_RISK:
        probs = [0.60, 0.30, 0.08, 0.02]
    elif risk == AccountRiskCategory.HIGH_RISK:
        probs = [0.30, 0.35, 0.25, 0.10]
    else:  # ACTIVE_ML
        probs = [0.15, 0.30, 0.35, 0.20]

    jurs = [
        JurisdictionRisk.LOW,
        JurisdictionRisk.MEDIUM,
        JurisdictionRisk.HIGH,
        JurisdictionRisk.VERY_HIGH,
    ]
    return jurs[int(rng.choice(len(jurs), p=probs))]


def _generate_routine_transactions(
    account: Account,
    sim_date: datetime.date,
    rng: np.random.Generator,
    config: SimulationConfig,
) -> list[Transaction]:
    """Generate normal-behaviour transactions for one account on one day."""
    # Draw number of transactions from a clipped normal
    n_raw = rng.normal(config.txn_daily_mean, config.txn_daily_std)
    n = max(0, int(round(n_raw)))

    txns: list[Transaction] = []
    for i in range(n):
        # Amount from log-normal
        amount = float(
            rng.lognormal(config.txn_amount_log_mean, config.txn_amount_log_std)
        )
        amount = max(0.01, round(amount, 2))

        txn_type_idx = int(rng.choice(len(_TXN_TYPES), p=_TXN_TYPE_PROBS))
        txn_type = _TXN_TYPES[txn_type_idx]

        channel_idx = int(rng.choice(len(_CHANNELS), p=_CHANNEL_PROBS))
        channel = _CHANNELS[channel_idx]

        # International routing
        is_intl_prob = _INTL_PROB[account.risk_category]
        is_intl = bool(rng.random() < is_intl_prob)
        if is_intl:
            txn_type = TransactionType.INTERNATIONAL_WIRE
            channel = Channel.ONLINE

        dest_jurisdiction: JurisdictionRisk | None = None
        counterparty: Counterparty | None = None
        if is_intl or txn_type in (
            TransactionType.DOMESTIC_WIRE,
            TransactionType.INTERNATIONAL_WIRE,
        ):
            dest_jurisdiction = _counterparty_jurisdiction(rng, account)
            counterparty = Counterparty(
                counterparty_id=new_id("CP"),
                jurisdiction=dest_jurisdiction,
            )

        # Time of day
        hour = int(rng.integers(6, 22))
        minute = int(rng.integers(0, 60))
        txn_dt = datetime.datetime.combine(sim_date, datetime.time(hour, minute))

        txns.append(
            Transaction(
                txn_id=new_id("TXN"),
                account_id=account.account_id,
                txn_date=sim_date,
                txn_datetime=txn_dt,
                txn_type=txn_type,
                channel=channel,
                amount_eur=amount,
                counterparty=counterparty,
                is_typology=False,
                is_international=is_intl,
                destination_jurisdiction=dest_jurisdiction,
            )
        )

    return txns


def generate_daily_transactions(
    accounts: list[Account],
    sim_date: datetime.date,
    day_idx: int,
    config: SimulationConfig,
    account_index: dict[str, int],  # account_id → list index
) -> list[Transaction]:
    """Generate all transactions for all accounts on a single simulation day.

    Args:
        accounts: Full account population.
        sim_date: The current simulation date.
        day_idx: 0-based index of this day within the simulation period.
        config: Simulation configuration.
        account_index: Maps account_id to its index in ``accounts``.

    Returns:
        All transactions generated for this day, in account-then-time order.
    """
    all_txns: list[Transaction] = []
    typology_activation_prob = config.typology_daily_activation_prob

    for acc_idx, account in enumerate(accounts):
        # Seeded child RNG per (seed, account_index, day_index)
        txn_rng = np.random.default_rng([config.seed, 0xABCD, acc_idx, day_idx])

        routine = _generate_routine_transactions(account, sim_date, txn_rng, config)
        all_txns.extend(routine)

        # Typology injection for ACTIVE_ML accounts
        if account.risk_category == AccountRiskCategory.ACTIVE_ML:
            if account.assigned_typology is not None:
                if txn_rng.random() < typology_activation_prob:
                    typology_gen = get_typology(account.assigned_typology)
                    typology_txns = typology_gen.generate(
                        account, sim_date, txn_rng, config
                    )
                    all_txns.extend(typology_txns)

    return all_txns


def iter_simulation_days(
    config: SimulationConfig,
) -> Iterator[tuple[int, datetime.date]]:
    """Yield (day_idx, date) for every day in the simulation period."""
    start = datetime.date.fromisoformat(config.start_date)
    end = datetime.date.fromisoformat(config.end_date)
    day = start
    idx = 0
    while day < end:
        yield idx, day
        day += datetime.timedelta(days=1)
        idx += 1
