"""
FATF Typology: Cash-Intensive Business

Criminal proceeds are commingled with legitimate cash business receipts
(e.g. restaurant, car wash, laundromat).  Deposits are frequent, moderate
in amount, and always in cash.  The pattern blends with genuine business
volume but deviates from declared revenue in aggregate.

Real-world pattern:
  A restaurant processing €2,000/day in genuine takings adds €1,500 in
  criminal cash.  From the outside, the deposit looks plausible.  Detection
  requires volume-vs-revenue analysis across many days.
"""

from __future__ import annotations

import datetime

import numpy as np

from ..config import SimulationConfig
from ..entities import (
    Account,
    Channel,
    Transaction,
    TransactionType,
    TypologyType,
    new_id,
)
from .base import BaseTypology


class CashIntensiveTypology(BaseTypology):
    typology_type = TypologyType.CASH_INTENSIVE

    def _generate_transactions(
        self,
        account: Account,
        sim_date: datetime.date,
        rng: np.random.Generator,
        config: SimulationConfig,
    ) -> list[Transaction]:
        txns: list[Transaction] = []

        # 1–3 cash deposits per day, below CTR threshold
        threshold = config.tms_thresholds.ctr_threshold
        n_txns = int(rng.integers(1, 4))

        for i in range(n_txns):
            # Amounts: €500 – (CTR threshold - €500)
            amount = round(float(rng.uniform(500, threshold - 500)), 2)
            amount = max(amount, 100.0)

            # Business cash deposits happen during business hours
            hour = int(rng.integers(7, 19))
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
                    txn_type=TransactionType.CASH_DEPOSIT,
                    channel=Channel.BRANCH,
                    amount_eur=amount,
                    is_typology=True,
                    typology_type=TypologyType.CASH_INTENSIVE,
                    is_international=False,
                )
            )

        return txns
