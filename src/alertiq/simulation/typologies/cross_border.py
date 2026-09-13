"""
FATF Typology: Cross-Border Cash / Hawala / Informal Value Transfer

Large cross-border transfers through informal channels or to/from
high-risk jurisdictions.  Often involves multiple small international
wires to different countries (smurfing across borders), or a single
very large wire to a high-risk jurisdiction with no clear commercial
rationale.

Real-world pattern:
  A network of accounts simultaneously sends funds to multiple overseas
  accounts in high-risk jurisdictions.  Alternatively, a hawala broker
  receives cash and makes a corresponding payment in another country
  through a partner, leaving minimal documented trail.
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

_HIGH_RISK_JURISDICTIONS = [JurisdictionRisk.HIGH, JurisdictionRisk.VERY_HIGH]


class CrossBorderTypology(BaseTypology):
    typology_type = TypologyType.CROSS_BORDER

    def _generate_transactions(
        self,
        account: Account,
        sim_date: datetime.date,
        rng: np.random.Generator,
        config: SimulationConfig,
    ) -> list[Transaction]:
        txns: list[Transaction] = []

        # Cross-border: 1-5 international wires on activation
        n_txns = int(rng.integers(1, 6))

        for _ in range(n_txns):
            # Amounts vary: small-to-medium for smurfing, large for single
            amount_type = int(rng.choice([0, 1], p=[0.60, 0.40]))
            if amount_type == 0:
                # Smurfing: multiple small wires
                amount = round(float(rng.uniform(1_000, 9_500)), 2)
            else:
                # Single large wire
                amount = round(float(rng.uniform(20_000, 500_000)), -2)
            amount = max(amount, 100.0)

            # Destination is always high-risk for cross-border ML
            cp_jur_idx = int(rng.integers(0, len(_HIGH_RISK_JURISDICTIONS)))
            cp_jurisdiction = _HIGH_RISK_JURISDICTIONS[cp_jur_idx]

            counterparty = Counterparty(
                counterparty_id=new_id("CP"),
                jurisdiction=cp_jurisdiction,
                is_shell=bool(rng.random() < 0.45),
            )

            hour = int(rng.integers(7, 20))
            txn_dt = datetime.datetime.combine(
                sim_date, datetime.time(hour, int(rng.integers(0, 60)))
            )

            txns.append(
                Transaction(
                    txn_id=new_id("TXN"),
                    account_id=account.account_id,
                    txn_date=sim_date,
                    txn_datetime=txn_dt,
                    txn_type=TransactionType.INTERNATIONAL_WIRE,
                    channel=Channel.ONLINE,
                    amount_eur=amount,
                    counterparty=counterparty,
                    is_typology=True,
                    typology_type=TypologyType.CROSS_BORDER,
                    is_international=True,
                    destination_jurisdiction=cp_jurisdiction,
                )
            )

        return txns
