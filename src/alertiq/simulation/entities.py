"""
Core entity models for AlertIQ simulation.

All entities use plain Python dataclasses for speed during generation,
with Pydantic used only for config validation.  Enums ensure type safety
and prevent invalid state throughout the pipeline.

Ground-truth design
-------------------
``Alert.true_sar`` is set during SAR label assignment (ground_truth.py),
not at alert creation time.  The rule is:

    true_sar = (
        account.risk_category == AccountRiskCategory.ACTIVE_ML
        AND alert.triggered_by_typology_txn
    )

``Transaction.is_typology`` is set by typology generators and is what
enables the second condition above.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum, auto
from typing import Optional


# ======================================================================= #
# Enumerations                                                             #
# ======================================================================= #


class AccountRiskCategory(Enum):
    """Internal risk tier for an account.

    ACTIVE_ML accounts are the positive class — they are running a
    documented FATF money-laundering typology.  This is never revealed
    to the TMS or feature layer; it is ground truth only.
    """

    LOW_RISK = "low_risk"
    MEDIUM_RISK = "medium_risk"
    HIGH_RISK = "high_risk"
    ACTIVE_ML = "active_ml"  # true positive class


class AccountType(Enum):
    """Broad customer segment used to shape transaction behaviour."""

    RETAIL = "retail"
    SME = "sme"
    CORPORATE = "corporate"
    SHELL = "shell"           # legal but thin corporate structure
    CASH_INTENSIVE = "cash_intensive"   # e.g. restaurant, laundromat
    PROFESSIONAL = "professional"       # e.g. lawyer, accountant


class JurisdictionRisk(Enum):
    """FATF-inspired jurisdiction risk tier."""

    LOW = "low"       # FATF-compliant, low-corruption
    MEDIUM = "medium"
    HIGH = "high"     # grey/blacklisted, high-corruption
    VERY_HIGH = "very_high"  # OFAC/UN sanctions adjacent


class TransactionType(Enum):
    """Broad transaction category."""

    CASH_DEPOSIT = "cash_deposit"
    CASH_WITHDRAWAL = "cash_withdrawal"
    DOMESTIC_WIRE = "domestic_wire"
    INTERNATIONAL_WIRE = "international_wire"
    CARD_PAYMENT = "card_payment"
    CRYPTO_EXCHANGE = "crypto_exchange"
    TRADE_SETTLEMENT = "trade_settlement"
    PROPERTY_PURCHASE = "property_purchase"
    LOAN_REPAYMENT = "loan_repayment"
    INTERNAL_TRANSFER = "internal_transfer"


class Channel(Enum):
    """Origination channel."""

    BRANCH = "branch"
    ONLINE = "online"
    MOBILE = "mobile"
    ATM = "atm"
    CORRESPONDENT = "correspondent"
    CRYPTO_WALLET = "crypto_wallet"


class TypologyType(Enum):
    """FATF money-laundering typology labels."""

    STRUCTURING = "structuring"
    SHELL_COMPANY = "shell_company"
    REAL_ESTATE = "real_estate"
    TRADE_BASED = "trade_based"
    CASH_INTENSIVE = "cash_intensive"
    PROFESSIONAL_ML = "professional_ml"
    VIRTUAL_ASSETS = "virtual_assets"
    CROSS_BORDER = "cross_border"


class AlertStatus(Enum):
    """Lifecycle status of an alert."""

    OPEN = "open"
    IN_REVIEW = "in_review"
    CLOSED_SAR = "closed_sar"     # SAR filed
    CLOSED_NO_SAR = "closed_no_sar"  # investigated, no SAR


class AlertSeverity(Enum):
    """TMS-assigned severity — based on rule score, not ground truth."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ======================================================================= #
# Account                                                                  #
# ======================================================================= #


@dataclass
class Account:
    """Simulated bank account / customer entity.

    Fields prefixed ``_`` are ground-truth-only and must not be
    surfaced to ML features.
    """

    account_id: str
    account_type: AccountType
    risk_category: AccountRiskCategory       # ← ground truth (hidden)
    jurisdiction: JurisdictionRisk
    onboard_date: date

    # Business characteristics
    declared_annual_revenue: float           # EUR
    expected_monthly_volume: float           # EUR

    # Relationship context
    has_pep_link: bool = False               # Politically Exposed Person
    has_adverse_media: bool = False
    is_high_risk_industry: bool = False

    # Typology assigned to this account (ACTIVE_ML only)
    assigned_typology: Optional[TypologyType] = None

    # Mutable state (updated during simulation)
    last_txn_date: Optional[date] = None
    cumulative_volume_eur: float = 0.0
    txn_count: int = 0

    @property
    def is_dormant(self) -> bool:
        """True if account has no recorded transactions."""
        return self.last_txn_date is None


# ======================================================================= #
# Counterparty                                                             #
# ======================================================================= #


@dataclass
class Counterparty:
    """Simplified counterparty reference attached to a transaction."""

    counterparty_id: str
    jurisdiction: JurisdictionRisk
    is_shell: bool = False
    is_crypto: bool = False
    is_pep: bool = False


# ======================================================================= #
# Transaction                                                              #
# ======================================================================= #


@dataclass
class Transaction:
    """A single financial transaction in the simulation.

    ``is_typology`` is the critical ground-truth flag set by typology
    generators.  It enables correct SAR labelling when combined with
    the account's risk category.
    """

    txn_id: str
    account_id: str
    txn_date: date
    txn_datetime: datetime
    txn_type: TransactionType
    channel: Channel
    amount_eur: float

    counterparty: Optional[Counterparty] = None

    # Ground-truth flag — set by typology generators only
    is_typology: bool = False
    typology_type: Optional[TypologyType] = None

    # Derived context (set by transaction engine)
    is_international: bool = False
    destination_jurisdiction: Optional[JurisdictionRisk] = None

    def validate(self) -> None:
        """Raise ValueError on obviously invalid state."""
        if self.amount_eur <= 0:
            raise ValueError(
                f"Transaction {self.txn_id}: amount_eur must be > 0, "
                f"got {self.amount_eur}"
            )
        if self.is_typology and self.typology_type is None:
            raise ValueError(
                f"Transaction {self.txn_id}: is_typology=True requires typology_type"
            )


# ======================================================================= #
# Alert                                                                    #
# ======================================================================= #


@dataclass
class Alert:
    """A TMS-generated alert on an account.

    ``true_sar`` is set during ground truth assignment, not at alert
    creation.  It must never influence feature computation.
    """

    alert_id: str
    account_id: str
    triggered_date: date
    rule_id: str
    rule_name: str
    severity: AlertSeverity
    status: AlertStatus = AlertStatus.OPEN

    # Set by ground_truth.py after all transactions are generated
    true_sar: Optional[bool] = None          # None = not yet labelled

    # True when the alert was caused by a typology transaction
    triggered_by_typology_txn: bool = False

    # Snapshot of features at alert creation (set by features.py)
    features: dict[str, float] = field(default_factory=dict)

    # Economic triage scores (set by triage engine — M2+)
    priority_score: Optional[float] = None
    eiv: Optional[float] = None


# ======================================================================= #
# SimulationResult                                                         #
# ======================================================================= #


@dataclass
class SimulationResult:
    """Aggregate output of a completed simulation run."""

    config_seed: int
    start_date: date
    end_date: date

    accounts: list[Account] = field(default_factory=list)
    transactions: list[Transaction] = field(default_factory=list)
    alerts: list[Alert] = field(default_factory=list)

    # Summary statistics (populated by runner)
    n_accounts: int = 0
    n_transactions: int = 0
    n_alerts: int = 0
    n_true_sar: int = 0
    n_active_ml_accounts: int = 0

    # Frequencies for sanity checks
    typology_txn_counts: dict[str, int] = field(default_factory=dict)
    rule_trigger_counts: dict[str, int] = field(default_factory=dict)

    @property
    def sar_rate(self) -> float:
        """Fraction of alerts that are true SARs."""
        if self.n_alerts == 0:
            return 0.0
        return self.n_true_sar / self.n_alerts

    @property
    def alert_rate(self) -> float:
        """Alerts per 1 000 transactions."""
        if self.n_transactions == 0:
            return 0.0
        return (self.n_alerts / self.n_transactions) * 1_000

    def summary(self) -> dict:
        """Return a JSON-serialisable summary dict."""
        return {
            "seed": self.config_seed,
            "period": f"{self.start_date} → {self.end_date}",
            "n_accounts": self.n_accounts,
            "n_active_ml_accounts": self.n_active_ml_accounts,
            "n_transactions": self.n_transactions,
            "n_alerts": self.n_alerts,
            "n_true_sar": self.n_true_sar,
            "sar_rate": round(self.sar_rate, 4),
            "alert_rate_per_1k_txns": round(self.alert_rate, 4),
            "typology_txn_counts": self.typology_txn_counts,
            "rule_trigger_counts": self.rule_trigger_counts,
        }


# ======================================================================= #
# Helper                                                                   #
# ======================================================================= #


def new_id(prefix: str = "") -> str:
    """Generate a short, collision-resistant ID."""
    uid = uuid.uuid4().hex[:12]
    return f"{prefix}{uid}" if prefix else uid
