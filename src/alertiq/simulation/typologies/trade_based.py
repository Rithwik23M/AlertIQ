"""
FATF Typology: Trade-Based Money Laundering (TBML)

Manipulated trade invoices — over/under invoicing, multiple invoicing,
or false description of goods.  Transactions appear as legitimate trade
settlements but at amounts that deviate significantly from fair market
value.  Counterparties are in high-risk jurisdictions.

Real-world pattern:
  An exporter (or importer) deliberately misrepresents the price or
  quantity of goods.  For example, a €10,000 shipment is invoiced at
  €40,000 — the excess €30,000 represents value transfer.
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


class TradeBasedTypology(BaseTypology):
    typology_type = TypologyType.TRADE_BASED

    def _generate_transactions(
        self,
        account: Account,
        sim_date: datetime.date,
        rng: np.random.Generator,
        config: SimulationConfig,
    ) -> list[Transaction]:
        txns: list[Transaction] = []

        # 1–3 trade settlements per activation
        n_txns = int(rng.integers(1, 4))
        deviation_threshold = config.tms_thresholds.trade_invoice_deviation

        for _ in range(n_txns):
            # Fair market value (FMV): €5k – €500k
            fmv = float(rng.uniform(5_000, 500_000))

            # Over-invoice by (deviation_threshold + 10%) to (3× FMV)
            over_ratio = float(rng.uniform(1 + deviation_threshold + 0.10, 3.0))
            amount = round(fmv * over_ratio, 2)
            amount = max(amount, 1000.0)

            # TBML counterparties are in high-risk jurisdictions
            jurisdiction_choices = [
                JurisdictionRisk.HIGH,
                JurisdictionRisk.VERY_HIGH,
                JurisdictionRisk.MEDIUM,
            ]
            cp_jur_idx = int(rng.choice([0, 1, 2], p=[0.45, 0.30, 0.25]))
            cp_jurisdiction = jurisdiction_choices[cp_jur_idx]

            counterparty = Counterparty(
                counterparty_id=new_id("CP"),
                jurisdiction=cp_jurisdiction,
                is_shell=bool(rng.random() < 0.30),
            )

            hour = int(rng.integers(8, 17))
            txn_dt = datetime.datetime.combine(
                sim_date, datetime.time(hour, int(rng.integers(0, 60)))
            )

            txns.append(
                Transaction(
                    txn_id=new_id("TXN"),
                    account_id=account.account_id,
                    txn_date=sim_date,
                    txn_datetime=txn_dt,
                    txn_type=TransactionType.TRADE_SETTLEMENT,
                    channel=Channel.CORRESPONDENT,
                    amount_eur=amount,
                    counterparty=counterparty,
                    is_typology=True,
                    typology_type=TypologyType.TRADE_BASED,
                    is_international=True,
                    destination_jurisdiction=cp_jurisdiction,
                )
            )

        return txns
