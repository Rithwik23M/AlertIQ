"""
FATF Typology: Professional Money Laundering (Gatekeepers)

Lawyers, accountants, and financial advisors who knowingly facilitate
ML by managing client accounts, forming shell companies, and executing
transactions on behalf of criminal clients.

Real-world pattern:
  A solicitor's client account receives large transfers from multiple
  third parties (not the nominal client), then wire funds onwards with
  minimal paper trail.  Transactions look like legitimate professional
  services payments but come from high-risk sources and flow to
  unusual destinations.
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


class ProfessionalMLTypology(BaseTypology):
    typology_type = TypologyType.PROFESSIONAL_ML

    def _generate_transactions(
        self,
        account: Account,
        sim_date: datetime.date,
        rng: np.random.Generator,
        config: SimulationConfig,
    ) -> list[Transaction]:
        txns: list[Transaction] = []

        # Professional services: 1-3 client account movements
        n_txns = int(rng.integers(1, 4))

        for _ in range(n_txns):
            # Amounts: professional fees range €5k – €250k
            amount = round(float(rng.uniform(5_000, 250_000)), 2)

            # Mix of domestic and international
            is_intl = bool(rng.random() < 0.55)

            if is_intl:
                cp_jur_idx = int(rng.choice([0, 1, 2], p=[0.40, 0.35, 0.25]))
                cp_jurisdiction = [
                    JurisdictionRisk.HIGH,
                    JurisdictionRisk.MEDIUM,
                    JurisdictionRisk.VERY_HIGH,
                ][cp_jur_idx]
                dest_jurisdiction: JurisdictionRisk | None = cp_jurisdiction
            else:
                cp_jurisdiction = JurisdictionRisk.LOW
                dest_jurisdiction = None

            counterparty = Counterparty(
                counterparty_id=new_id("CP"),
                jurisdiction=cp_jurisdiction,
                is_shell=bool(rng.random() < 0.35),
                is_pep=bool(rng.random() < 0.12),
            )

            txn_type = (
                TransactionType.INTERNATIONAL_WIRE
                if is_intl
                else TransactionType.DOMESTIC_WIRE
            )

            hour = int(rng.integers(9, 17))
            txn_dt = datetime.datetime.combine(
                sim_date, datetime.time(hour, int(rng.integers(0, 60)))
            )

            txns.append(
                Transaction(
                    txn_id=new_id("TXN"),
                    account_id=account.account_id,
                    txn_date=sim_date,
                    txn_datetime=txn_dt,
                    txn_type=txn_type,
                    channel=Channel.ONLINE,
                    amount_eur=amount,
                    counterparty=counterparty,
                    is_typology=True,
                    typology_type=TypologyType.PROFESSIONAL_ML,
                    is_international=is_intl,
                    destination_jurisdiction=dest_jurisdiction,
                )
            )

        return txns
