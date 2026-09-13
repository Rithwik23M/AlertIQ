"""
FATF Typology: Structuring (Smurfing)

Multiple cash deposits just below the Currency Transaction Report threshold
(€10,000 default) within a rolling window.  Each deposit is slightly below
the threshold, spread across 2-5 transactions in a single day to avoid
detection.

Real-world pattern:
  A money launderer splits a large cash sum across multiple deposits,
  each just under the reporting threshold, often across multiple branches
  or on consecutive days.
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


class StructuringTypology(BaseTypology):
    typology_type = TypologyType.STRUCTURING

    def _generate_transactions(
        self,
        account: Account,
        sim_date: datetime.date,
        rng: np.random.Generator,
        config: SimulationConfig,
    ) -> list[Transaction]:
        threshold = config.tms_thresholds.ctr_threshold
        n_txns = int(rng.integers(2, 6))          # 2–5 deposits
        txns: list[Transaction] = []

        for i in range(n_txns):
            # Amount: 70–99% of CTR threshold
            ratio = float(rng.uniform(0.70, 0.99))
            amount = round(threshold * ratio, 2)

            # Spread times across the day
            hour = int(rng.integers(8, 18))
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
                    typology_type=TypologyType.STRUCTURING,
                    is_international=False,
                )
            )

        return txns
