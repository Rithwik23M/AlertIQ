"""
Abstract base class for FATF money-laundering typologies.

Each concrete typology receives:
  - the target Account
  - the current simulation date
  - a seeded numpy Generator (child of the account's generator)
  - simulation config

It returns a (possibly empty) list of Transactions.
Every transaction in that list has ``is_typology=True`` and the
appropriate ``typology_type``.

The base class enforces these invariants via ``generate()``.
Subclasses implement ``_generate_transactions()``.
"""

from __future__ import annotations

import datetime
from abc import ABC, abstractmethod

import numpy as np

from ..config import SimulationConfig
from ..entities import Account, Transaction, TypologyType


class BaseTypology(ABC):
    """Abstract typology generator."""

    typology_type: TypologyType  # must be set on subclass

    def generate(
        self,
        account: Account,
        sim_date: datetime.date,
        rng: np.random.Generator,
        config: SimulationConfig,
    ) -> list[Transaction]:
        """Generate typology transactions for this account on ``sim_date``.

        This method validates that every returned transaction:
          - has ``is_typology=True``
          - has ``typology_type`` matching this class
          - has ``amount_eur > 0``
          - has ``account_id`` matching the account
        """
        txns = self._generate_transactions(account, sim_date, rng, config)
        for txn in txns:
            if not txn.is_typology:
                raise AssertionError(
                    f"{self.__class__.__name__}: transaction {txn.txn_id} "
                    f"is_typology must be True"
                )
            if txn.typology_type != self.typology_type:
                raise AssertionError(
                    f"{self.__class__.__name__}: transaction {txn.txn_id} "
                    f"typology_type must be {self.typology_type}, "
                    f"got {txn.typology_type}"
                )
            if txn.amount_eur <= 0:
                raise ValueError(
                    f"{self.__class__.__name__}: transaction {txn.txn_id} "
                    f"amount_eur={txn.amount_eur} must be > 0"
                )
            if txn.account_id != account.account_id:
                raise AssertionError(
                    f"{self.__class__.__name__}: transaction {txn.txn_id} "
                    f"account_id mismatch"
                )
        return txns

    @abstractmethod
    def _generate_transactions(
        self,
        account: Account,
        sim_date: datetime.date,
        rng: np.random.Generator,
        config: SimulationConfig,
    ) -> list[Transaction]:
        """Subclasses implement the typology logic here."""
        ...
