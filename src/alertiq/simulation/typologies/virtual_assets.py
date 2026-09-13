"""
FATF Typology: Virtual Assets / Cryptocurrency

Criminal proceeds are converted to crypto and back to fiat, or
crypto proceeds are cashed out through exchange accounts.  Transactions
involve crypto exchanges, may be followed by rapid fiat withdrawal, and
counterparties are often crypto-native.

Real-world pattern:
  Funds arrive from a crypto exchange account, are briefly held, then
  transferred to a second exchange or withdrawn as cash.  The layering
  exploits the pseudonymous nature of blockchain transactions.
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


class VirtualAssetsTypology(BaseTypology):
    typology_type = TypologyType.VIRTUAL_ASSETS

    def _generate_transactions(
        self,
        account: Account,
        sim_date: datetime.date,
        rng: np.random.Generator,
        config: SimulationConfig,
    ) -> list[Transaction]:
        txns: list[Transaction] = []

        # 1-3 crypto-related transactions
        n_txns = int(rng.integers(1, 4))

        for _ in range(n_txns):
            # Crypto amounts: €1k – €100k (smaller, more frequent than wire)
            amount = round(float(rng.uniform(1_000, 100_000)), 2)

            # Crypto exchanges can be in any jurisdiction
            cp_jur_idx = int(rng.choice([0, 1, 2, 3], p=[0.20, 0.30, 0.35, 0.15]))
            cp_jurisdiction = [
                JurisdictionRisk.LOW,
                JurisdictionRisk.MEDIUM,
                JurisdictionRisk.HIGH,
                JurisdictionRisk.VERY_HIGH,
            ][cp_jur_idx]

            counterparty = Counterparty(
                counterparty_id=new_id("CRYPTO"),
                jurisdiction=cp_jurisdiction,
                is_crypto=True,
            )

            # Time of day is often outside business hours for crypto
            hour = int(rng.integers(0, 24))
            minute = int(rng.integers(0, 60))
            txn_dt = datetime.datetime.combine(
                sim_date, datetime.time(hour, minute)
            )

            txns.append(
                Transaction(
                    txn_id=new_id("TXN"),
                    account_id=account.account_id,
                    txn_date=sim_date,
                    txn_datetime=txn_dt,
                    txn_type=TransactionType.CRYPTO_EXCHANGE,
                    channel=Channel.CRYPTO_WALLET,
                    amount_eur=amount,
                    counterparty=counterparty,
                    is_typology=True,
                    typology_type=TypologyType.VIRTUAL_ASSETS,
                    is_international=True,
                    destination_jurisdiction=cp_jurisdiction,
                )
            )

        return txns
