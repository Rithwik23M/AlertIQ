"""
FATF Typology: Real Estate Money Laundering

Large property purchase transactions, often with partial cash payment or
inflated invoice amounts.  Transactions are infrequent (property deals
are rare), high-value, and typically involve international wire transfers
or mixed cash/wire payments.

Real-world pattern:
  Criminal proceeds are used to purchase real estate (placement/layering).
  Property may be sold at a loss or rented out (integration).
  Transactions are characterised by very large single amounts, involvement
  of professional intermediaries, and possible overseas jurisdictions.
"""

from __future__ import annotations

import datetime

import numpy as np

from ..config import SimulationConfig
from ..entities import (
    Account,
    Channel,
    Counterparty,
    JurisdictionRisk,
    Transaction,
    TransactionType,
    TypologyType,
    new_id,
)
from .base import BaseTypology


class RealEstateTypology(BaseTypology):
    typology_type = TypologyType.REAL_ESTATE

    def _generate_transactions(
        self,
        account: Account,
        sim_date: datetime.date,
        rng: np.random.Generator,
        config: SimulationConfig,
    ) -> list[Transaction]:
        txns: list[Transaction] = []

        # Real estate deals are large and infrequent — 1-2 transactions
        n_txns = int(rng.choice([1, 2], p=[0.70, 0.30]))

        for _ in range(n_txns):
            # Property value range: €100k – €5M
            amount = round(float(rng.uniform(100_000, 5_000_000)), -3)
            amount = max(amount, 100_000.0)

            # Mostly domestic but sometimes offshore
            is_intl = bool(rng.random() < 0.35)
            dest_jurisdiction = (
                JurisdictionRisk.HIGH if is_intl else JurisdictionRisk.LOW
            )

            counterparty = Counterparty(
                counterparty_id=new_id("CP"),
                jurisdiction=dest_jurisdiction,
                is_shell=bool(rng.random() < 0.40),
            )

            hour = int(rng.integers(10, 16))
            txn_dt = datetime.datetime.combine(
                sim_date, datetime.time(hour, 0)
            )

            txns.append(
                Transaction(
                    txn_id=new_id("TXN"),
                    account_id=account.account_id,
                    txn_date=sim_date,
                    txn_datetime=txn_dt,
                    txn_type=TransactionType.PROPERTY_PURCHASE,
                    channel=Channel.ONLINE,
                    amount_eur=amount,
                    counterparty=counterparty,
                    is_typology=True,
                    typology_type=TypologyType.REAL_ESTATE,
                    is_international=is_intl,
                    destination_jurisdiction=dest_jurisdiction if is_intl else None,
                )
            )

        return txns
