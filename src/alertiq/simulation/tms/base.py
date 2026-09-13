"""
Abstract base class for TMS (Transaction Monitoring System) rules.

Each rule receives a window of transactions for an account and returns
zero or more alerts.  Rules operate only on transaction data visible at
alert creation time — they cannot access ground truth.

Design constraints:
  - Rules must be stateless: no instance-level mutation between calls.
  - Rules must not access Account.risk_category or Transaction.is_typology.
  - A rule that cannot possibly trigger (no matching transactions) must
    return an empty list, never raise.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..entities import Account, Alert, Transaction


@dataclass(frozen=True)
class RuleMetadata:
    """Static metadata about a TMS rule."""

    rule_id: str
    rule_name: str
    description: str
    typology_affinity: list[str]  # FATF typology names this rule covers


class BaseRule(ABC):
    """Abstract TMS rule."""

    @property
    @abstractmethod
    def metadata(self) -> RuleMetadata:
        """Return static rule metadata."""
        ...

    def evaluate(
        self,
        account: Account,
        window_transactions: list[Transaction],
        all_account_transactions: list[Transaction],
    ) -> list[Alert]:
        """Evaluate rule and return zero or more alerts.

        Args:
            account: The account being evaluated.
            window_transactions: Transactions within the rule's look-back window.
            all_account_transactions: All transactions for this account to date
                (for rules that need the full history, e.g. dormancy).

        Returns:
            List of Alert objects (may be empty).  Alerts must have
            ``true_sar=None`` — ground truth is set later by ground_truth.py.
        """
        alerts = self._evaluate(account, window_transactions, all_account_transactions)
        for alert in alerts:
            if alert.true_sar is not None:
                raise AssertionError(
                    f"Rule {self.metadata.rule_id}: alert {alert.alert_id} "
                    f"must have true_sar=None at creation"
                )
        return alerts

    @abstractmethod
    def _evaluate(
        self,
        account: Account,
        window_transactions: list[Transaction],
        all_account_transactions: list[Transaction],
    ) -> list[Alert]:
        """Subclasses implement rule logic here."""
        ...
