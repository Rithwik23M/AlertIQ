"""
FATF Typology: Shell Company Layering

Large wire transfers through shell company accounts in high-risk
jurisdictions, often at round amounts with minimal commercial rationale.
Multiple hops through intermediaries within a short window.

Real-world pattern:
  Proceeds are transferred to a shell company abroad, then routed through
  2-4 additional shell entities before integration.  Amounts are large and
  often round.  Jurisdictions are high-risk (e.g. BVI, Cayman, Delaware).
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

# Shell company jurisdictions are predominantly high-risk
_SHELL_JURISDICTIONS = [
    JurisdictionRisk.HIGH,
    JurisdictionRisk.VERY_HIGH,
    JurisdictionRisk.HIGH,
    JurisdictionRisk.MEDIUM,
]


class ShellCompanyTypology(BaseTypology):
    typology_type = TypologyType.SHELL_COMPANY

    def _generate_transactions(
        self,
        account: Account,
        sim_date: datetime.date,
        rng: np.random.Generator,
        config: SimulationConfig,
    ) -> list[Transaction]:
        n_hops = int(rng.integers(2, 5))   # 2–4 layering hops
        txns: list[Transaction] = []

        # Base amount: large, round
        base_amount = float(rng.choice([50_000, 100_000, 250_000, 500_000]))
        # Slight random variation per hop
        for hop in range(n_hops):
            variation = float(rng.uniform(0.90, 1.10))
            amount = round(base_amount * variation, -2)  # round to nearest 100
            amount = max(amount, 1000.0)

            jurisdiction_idx = int(rng.integers(0, len(_SHELL_JURISDICTIONS)))
            cp_jurisdiction = _SHELL_JURISDICTIONS[jurisdiction_idx]

            counterparty = Counterparty(
                counterparty_id=new_id("CP"),
                jurisdiction=cp_jurisdiction,
                is_shell=True,
                is_crypto=False,
                is_pep=bool(rng.random() < 0.10),
            )

            hour = int(rng.integers(9, 17))
            txn_dt = datetime.datetime.combine(
                sim_date, datetime.time(hour, 0)
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
                    typology_type=TypologyType.SHELL_COMPANY,
                    is_international=True,
                    destination_jurisdiction=cp_jurisdiction,
                )
            )

        return txns
