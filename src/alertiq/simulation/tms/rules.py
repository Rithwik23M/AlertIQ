"""
15 TMS rules covering the 8 FATF typologies.

Rules operate only on observable transaction data — never on ground truth.
Each rule returns zero or more Alert objects with ``true_sar=None``.

Rule inventory:
  R01  Cash Structuring (multiple deposits near CTR threshold)
  R02  Large Single Cash Transaction
  R03  Transaction Velocity Spike
  R04  Round-Amount Pattern
  R05  Dormant Account Sudden Activity
  R06  High-Risk Jurisdiction Wire
  R07  Rapid Fund Movement (in → out)
  R08  Multiple Counterparty Layering
  R09  PEP / Adverse Media High-Value Transaction
  R10  Cryptocurrency Exchange Activity
  R11  Trade Invoice Anomaly (amount deviation)
  R12  Shell Company Counterparty Wire
  R13  Real Estate Large Transaction
  R14  Nighttime / Off-Hours Transaction Pattern
  R15  Cross-Border Multi-Country Fan-Out
"""

from __future__ import annotations

import datetime
from collections import defaultdict

from ..config import SimulationConfig
from ..entities import (
    Account,
    Alert,
    AlertSeverity,
    AlertStatus,
    Channel,
    JurisdictionRisk,
    Transaction,
    TransactionType,
    new_id,
)
from .base import BaseRule, RuleMetadata


# ======================================================================= #
# Helper functions                                                         #
# ======================================================================= #


def _make_alert(
    account: Account,
    triggered_date: datetime.date,
    rule: "BaseRule",
    severity: AlertSeverity,
    triggered_by_typology: bool = False,
) -> Alert:
    return Alert(
        alert_id=new_id("ALT"),
        account_id=account.account_id,
        triggered_date=triggered_date,
        rule_id=rule.metadata.rule_id,
        rule_name=rule.metadata.rule_name,
        severity=severity,
        status=AlertStatus.OPEN,
        true_sar=None,
        triggered_by_typology_txn=triggered_by_typology,
    )


def _cash_deposits(txns: list[Transaction]) -> list[Transaction]:
    return [
        t for t in txns
        if t.txn_type in (
            TransactionType.CASH_DEPOSIT,
            TransactionType.CASH_WITHDRAWAL,
        )
    ]


def _intl_wires(txns: list[Transaction]) -> list[Transaction]:
    return [t for t in txns if t.txn_type == TransactionType.INTERNATIONAL_WIRE]


def _high_risk_dest(txn: Transaction) -> bool:
    return txn.destination_jurisdiction in (
        JurisdictionRisk.HIGH,
        JurisdictionRisk.VERY_HIGH,
    )


# ======================================================================= #
# R01 — Cash Structuring                                                   #
# ======================================================================= #


class CashStructuringRule(BaseRule):
    _meta = RuleMetadata(
        rule_id="R01",
        rule_name="Cash Structuring",
        description=(
            "Multiple cash deposits near the CTR threshold within a rolling window "
            "suggest deliberate structuring to avoid reporting."
        ),
        typology_affinity=["structuring", "cash_intensive"],
    )

    @property
    def metadata(self) -> RuleMetadata:
        return self._meta

    def _evaluate(
        self,
        account: Account,
        window_transactions: list[Transaction],
        all_account_transactions: list[Transaction],
    ) -> list[Alert]:
        cfg_thresholds = _get_global_thresholds()
        threshold = cfg_thresholds.ctr_threshold
        min_txns = cfg_thresholds.structuring_min_txns

        near_threshold_deposits = [
            t for t in window_transactions
            if t.txn_type == TransactionType.CASH_DEPOSIT
            and 0.70 * threshold <= t.amount_eur < threshold
        ]
        if len(near_threshold_deposits) >= min_txns:
            total = sum(t.amount_eur for t in near_threshold_deposits)
            severity = (
                AlertSeverity.CRITICAL if total > threshold * 3
                else AlertSeverity.HIGH if len(near_threshold_deposits) >= 5
                else AlertSeverity.MEDIUM
            )
            trigger_date = max(t.txn_date for t in near_threshold_deposits)
            has_typology = any(t.is_typology for t in near_threshold_deposits)
            return [_make_alert(account, trigger_date, self, severity, has_typology)]
        return []


# ======================================================================= #
# R02 — Large Single Cash Transaction                                      #
# ======================================================================= #


class LargeCashRule(BaseRule):
    _meta = RuleMetadata(
        rule_id="R02",
        rule_name="Large Cash Transaction",
        description="Single cash transaction exceeding large-cash threshold.",
        typology_affinity=["structuring", "cash_intensive"],
    )

    @property
    def metadata(self) -> RuleMetadata:
        return self._meta

    def _evaluate(
        self,
        account: Account,
        window_transactions: list[Transaction],
        all_account_transactions: list[Transaction],
    ) -> list[Alert]:
        thr = _get_global_thresholds().large_cash_threshold
        large = [
            t for t in window_transactions
            if t.txn_type in (TransactionType.CASH_DEPOSIT, TransactionType.CASH_WITHDRAWAL)
            and t.amount_eur >= thr
        ]
        alerts = []
        for txn in large:
            severity = (
                AlertSeverity.CRITICAL if txn.amount_eur >= thr * 3
                else AlertSeverity.HIGH
            )
            alerts.append(
                _make_alert(account, txn.txn_date, self, severity, txn.is_typology)
            )
        return alerts


# ======================================================================= #
# R03 — Transaction Velocity Spike                                         #
# ======================================================================= #


class VelocitySpikeRule(BaseRule):
    _meta = RuleMetadata(
        rule_id="R03",
        rule_name="Transaction Velocity Spike",
        description=(
            "Abnormally high number of transactions within a short window "
            "compared to the account's baseline."
        ),
        typology_affinity=["structuring", "cross_border", "virtual_assets"],
    )

    @property
    def metadata(self) -> RuleMetadata:
        return self._meta

    def _evaluate(
        self,
        account: Account,
        window_transactions: list[Transaction],
        all_account_transactions: list[Transaction],
    ) -> list[Alert]:
        """Detect velocity spikes by comparing 7-day count to 30-day baseline.

        Algorithm:
          - recent_count  = transactions in the last `velocity_window_days` days
          - baseline_count = transactions in the 30-day window (the full window)
          - expected_recent = baseline_count × (window_days / 30)
          - Spike if recent_count > spike_ratio × expected_recent AND
                    recent_count >= velocity_threshold_count (absolute minimum)

        This prevents the rule from firing every day for every account when the
        absolute threshold is far below typical transaction rates.
        """
        thresholds = _get_global_thresholds()
        min_count = thresholds.velocity_threshold_count
        spike_ratio = thresholds.velocity_spike_ratio
        window_days = thresholds.velocity_window_days

        if not window_transactions:
            return []

        sim_date = max(t.txn_date for t in window_transactions)
        recent_cutoff = sim_date - datetime.timedelta(days=window_days)
        recent_txns = [t for t in window_transactions if t.txn_date > recent_cutoff]
        recent_count = len(recent_txns)

        if recent_count < min_count:
            return []  # Not enough recent transactions to matter

        # Baseline: 30-day window count extrapolated to the recent window length
        baseline_30d = len(window_transactions)
        if baseline_30d == 0:
            return []
        expected_recent = baseline_30d * (window_days / 30.0)

        # Need at least some baseline to compare against
        if expected_recent < 1.0:
            return []

        actual_ratio = recent_count / expected_recent
        if actual_ratio >= spike_ratio:
            severity = (
                AlertSeverity.CRITICAL if actual_ratio >= spike_ratio * 2
                else AlertSeverity.HIGH if actual_ratio >= spike_ratio * 1.5
                else AlertSeverity.MEDIUM
            )
            has_typology = any(t.is_typology for t in recent_txns)
            return [_make_alert(account, sim_date, self, severity, has_typology)]
        return []


# ======================================================================= #
# R04 — Round-Amount Pattern                                               #
# ======================================================================= #


class RoundAmountRule(BaseRule):
    _meta = RuleMetadata(
        rule_id="R04",
        rule_name="Round Amount Pattern",
        description=(
            "Multiple transactions at suspiciously round amounts within a window "
            "suggest pre-planned layering."
        ),
        typology_affinity=["shell_company", "professional_ml"],
    )

    @property
    def metadata(self) -> RuleMetadata:
        return self._meta

    def _evaluate(
        self,
        account: Account,
        window_transactions: list[Transaction],
        all_account_transactions: list[Transaction],
    ) -> list[Alert]:
        thresholds = _get_global_thresholds()
        precision = thresholds.round_amount_precision
        min_amount = thresholds.round_amount_min
        min_count = thresholds.round_amount_min_count

        round_txns = [
            t for t in window_transactions
            if t.amount_eur >= min_amount
            and t.amount_eur % precision == 0
        ]
        if len(round_txns) >= min_count:
            trigger_date = max(t.txn_date for t in round_txns)
            has_typology = any(t.is_typology for t in round_txns)
            return [
                _make_alert(account, trigger_date, self, AlertSeverity.MEDIUM, has_typology)
            ]
        return []


# ======================================================================= #
# R05 — Dormant Account Sudden Activity                                    #
# ======================================================================= #


class DormantAccountRule(BaseRule):
    _meta = RuleMetadata(
        rule_id="R05",
        rule_name="Dormant Account Sudden Activity",
        description=(
            "A previously dormant account suddenly shows high-value transactions, "
            "a pattern associated with account takeover or new ML use."
        ),
        typology_affinity=["shell_company", "cash_intensive"],
    )

    @property
    def metadata(self) -> RuleMetadata:
        return self._meta

    def _evaluate(
        self,
        account: Account,
        window_transactions: list[Transaction],
        all_account_transactions: list[Transaction],
    ) -> list[Alert]:
        dormancy_days = _get_global_thresholds().dormancy_threshold_days
        if not window_transactions:
            return []

        # Sort window transactions by date to find earliest
        sorted_window = sorted(window_transactions, key=lambda t: t.txn_date)
        earliest_window_txn = sorted_window[0]

        alerts = []

        # --- Path 1: gap detected within the provided transaction window ---
        if len(all_account_transactions) >= 2:
            sorted_txns = sorted(all_account_transactions, key=lambda t: t.txn_date)
            for i in range(1, len(sorted_txns)):
                gap = (sorted_txns[i].txn_date - sorted_txns[i - 1].txn_date).days
                if (
                    gap >= dormancy_days
                    and sorted_txns[i] in window_transactions
                    and sorted_txns[i].amount_eur >= 5_000
                ):
                    alerts.append(
                        _make_alert(
                            account,
                            sorted_txns[i].txn_date,
                            self,
                            AlertSeverity.HIGH,
                            sorted_txns[i].is_typology,
                        )
                    )
                    break  # one alert per dormancy event

        # --- Path 2: account.last_txn_date predates the window by dormancy_days ---
        # This handles accounts that were dormant before the simulation window opened.
        # The runner updates last_txn_date *after* rule evaluation, so at evaluation
        # time it holds the date of the last transaction that preceded today's batch.
        #
        # We check ALL transactions on the reactivation day (not just the earliest
        # by insertion order) because multiple transactions share the same txn_date
        # and the triggering one may not be first in the sorted list.
        if not alerts and account.last_txn_date is not None:
            gap = (earliest_window_txn.txn_date - account.last_txn_date).days
            if gap >= dormancy_days:
                # Find the largest transaction on the first reactivation day
                reactivation_day = earliest_window_txn.txn_date
                first_day_txns = [
                    t for t in window_transactions if t.txn_date == reactivation_day
                ]
                large_txns = [t for t in first_day_txns if t.amount_eur >= 5_000]
                if large_txns:
                    trigger_txn = max(large_txns, key=lambda t: t.amount_eur)
                    alerts.append(
                        _make_alert(
                            account,
                            reactivation_day,
                            self,
                            AlertSeverity.HIGH,
                            trigger_txn.is_typology,
                        )
                    )

        return alerts


# ======================================================================= #
# R06 — High-Risk Jurisdiction Wire                                        #
# ======================================================================= #


class HighRiskJurisdictionRule(BaseRule):
    _meta = RuleMetadata(
        rule_id="R06",
        rule_name="High-Risk Jurisdiction Wire",
        description=(
            "Wire transfers to or from high-risk or sanctioned jurisdictions "
            "above the threshold amount."
        ),
        typology_affinity=["cross_border", "shell_company", "trade_based"],
    )

    @property
    def metadata(self) -> RuleMetadata:
        return self._meta

    def _evaluate(
        self,
        account: Account,
        window_transactions: list[Transaction],
        all_account_transactions: list[Transaction],
    ) -> list[Alert]:
        thr = _get_global_thresholds().high_risk_jurisdiction_threshold
        risky = [
            t for t in window_transactions
            if _high_risk_dest(t) and t.amount_eur >= thr
        ]
        alerts = []
        for txn in risky:
            severity = (
                AlertSeverity.CRITICAL
                if txn.destination_jurisdiction == JurisdictionRisk.VERY_HIGH
                else AlertSeverity.HIGH
            )
            alerts.append(
                _make_alert(account, txn.txn_date, self, severity, txn.is_typology)
            )
        return alerts


# ======================================================================= #
# R07 — Rapid Fund Movement                                                #
# ======================================================================= #


class RapidFundMovementRule(BaseRule):
    _meta = RuleMetadata(
        rule_id="R07",
        rule_name="Rapid Fund Movement",
        description=(
            "Funds received and then withdrawn/transferred out within a short "
            "window — classic pass-through layering."
        ),
        typology_affinity=["shell_company", "professional_ml", "virtual_assets"],
    )

    @property
    def metadata(self) -> RuleMetadata:
        return self._meta

    def _evaluate(
        self,
        account: Account,
        window_transactions: list[Transaction],
        all_account_transactions: list[Transaction],
    ) -> list[Alert]:
        thresholds = _get_global_thresholds()
        hours = thresholds.rapid_movement_hours
        ratio_thr = thresholds.rapid_movement_ratio

        # Look for inflows followed rapidly by outflows
        inflows = [
            t for t in window_transactions
            if t.txn_type in (
                TransactionType.CASH_DEPOSIT,
                TransactionType.DOMESTIC_WIRE,
                TransactionType.INTERNATIONAL_WIRE,
            )
        ]
        outflows = [
            t for t in window_transactions
            if t.txn_type in (
                TransactionType.CASH_WITHDRAWAL,
                TransactionType.INTERNATIONAL_WIRE,
                TransactionType.CRYPTO_EXCHANGE,
            )
        ]

        if not inflows or not outflows:
            return []

        total_in = sum(t.amount_eur for t in inflows)
        total_out = sum(t.amount_eur for t in outflows)

        if total_in == 0:
            return []

        ratio = total_out / total_in
        if ratio < ratio_thr:
            return []

        # Check temporal proximity: any outflow within `hours` of an inflow
        for inf in inflows:
            for out in outflows:
                if out.txn_datetime >= inf.txn_datetime:
                    delta_hours = (
                        out.txn_datetime - inf.txn_datetime
                    ).total_seconds() / 3600
                    if delta_hours <= hours:
                        has_typology = inf.is_typology or out.is_typology
                        return [
                            _make_alert(
                                account, out.txn_date, self, AlertSeverity.HIGH, has_typology
                            )
                        ]
        return []


# ======================================================================= #
# R08 — Multiple Counterparty Layering                                     #
# ======================================================================= #


class LayeringRule(BaseRule):
    _meta = RuleMetadata(
        rule_id="R08",
        rule_name="Multiple Counterparty Layering",
        description=(
            "Transfers to many distinct counterparties within a short window "
            "suggest layering through multiple entities."
        ),
        typology_affinity=["shell_company", "cross_border"],
    )

    @property
    def metadata(self) -> RuleMetadata:
        return self._meta

    def _evaluate(
        self,
        account: Account,
        window_transactions: list[Transaction],
        all_account_transactions: list[Transaction],
    ) -> list[Alert]:
        min_hops = _get_global_thresholds().layering_min_hops

        # Count distinct counterparties in wires
        wire_txns = [
            t for t in window_transactions
            if t.txn_type in (
                TransactionType.DOMESTIC_WIRE,
                TransactionType.INTERNATIONAL_WIRE,
            )
            and t.counterparty is not None
        ]
        counterparty_ids = {t.counterparty.counterparty_id for t in wire_txns}

        if len(counterparty_ids) >= min_hops:
            trigger_date = max(t.txn_date for t in wire_txns)
            has_typology = any(t.is_typology for t in wire_txns)
            severity = (
                AlertSeverity.HIGH if len(counterparty_ids) >= min_hops * 2
                else AlertSeverity.MEDIUM
            )
            return [_make_alert(account, trigger_date, self, severity, has_typology)]
        return []


# ======================================================================= #
# R09 — PEP / Adverse Media High-Value Transaction                        #
# ======================================================================= #


class PEPHighValueRule(BaseRule):
    _meta = RuleMetadata(
        rule_id="R09",
        rule_name="PEP / Adverse Media High-Value Transaction",
        description=(
            "A PEP-linked or adverse-media-flagged account conducting high-value "
            "transactions requires enhanced due diligence review."
        ),
        typology_affinity=["professional_ml", "shell_company"],
    )

    @property
    def metadata(self) -> RuleMetadata:
        return self._meta

    def _evaluate(
        self,
        account: Account,
        window_transactions: list[Transaction],
        all_account_transactions: list[Transaction],
    ) -> list[Alert]:
        if not (account.has_pep_link or account.has_adverse_media):
            return []

        thr = _get_global_thresholds().pep_threshold
        high_value = [t for t in window_transactions if t.amount_eur >= thr]

        if high_value:
            trigger_date = max(t.txn_date for t in high_value)
            has_typology = any(t.is_typology for t in high_value)
            severity = (
                AlertSeverity.CRITICAL if account.has_pep_link
                else AlertSeverity.HIGH
            )
            return [_make_alert(account, trigger_date, self, severity, has_typology)]
        return []


# ======================================================================= #
# R10 — Cryptocurrency Exchange Activity                                   #
# ======================================================================= #


class CryptoActivityRule(BaseRule):
    _meta = RuleMetadata(
        rule_id="R10",
        rule_name="Cryptocurrency Exchange Activity",
        description=(
            "Transactions with cryptocurrency exchanges above threshold — "
            "a known layering vehicle."
        ),
        typology_affinity=["virtual_assets"],
    )

    @property
    def metadata(self) -> RuleMetadata:
        return self._meta

    def _evaluate(
        self,
        account: Account,
        window_transactions: list[Transaction],
        all_account_transactions: list[Transaction],
    ) -> list[Alert]:
        thr = _get_global_thresholds().crypto_threshold
        crypto_txns = [
            t for t in window_transactions
            if (
                t.txn_type == TransactionType.CRYPTO_EXCHANGE
                or (t.counterparty is not None and t.counterparty.is_crypto)
                or t.channel == Channel.CRYPTO_WALLET
            )
            and t.amount_eur >= thr
        ]
        if crypto_txns:
            total = sum(t.amount_eur for t in crypto_txns)
            trigger_date = max(t.txn_date for t in crypto_txns)
            has_typology = any(t.is_typology for t in crypto_txns)
            severity = (
                AlertSeverity.HIGH if total >= thr * 10
                else AlertSeverity.MEDIUM
            )
            return [_make_alert(account, trigger_date, self, severity, has_typology)]
        return []


# ======================================================================= #
# R11 — Trade Invoice Anomaly                                              #
# ======================================================================= #


class TradeInvoiceAnomalyRule(BaseRule):
    _meta = RuleMetadata(
        rule_id="R11",
        rule_name="Trade Invoice Anomaly",
        description=(
            "Trade settlement amounts deviate significantly from declared "
            "transaction value — possible over/under invoicing."
        ),
        typology_affinity=["trade_based"],
    )

    @property
    def metadata(self) -> RuleMetadata:
        return self._meta

    def _evaluate(
        self,
        account: Account,
        window_transactions: list[Transaction],
        all_account_transactions: list[Transaction],
    ) -> list[Alert]:
        deviation = _get_global_thresholds().trade_invoice_deviation
        # Proxy: trade settlements to high-risk counterparties at amounts
        # significantly above the expected monthly volume
        monthly_vol = account.expected_monthly_volume
        trade_txns = [
            t for t in window_transactions
            if t.txn_type == TransactionType.TRADE_SETTLEMENT
            and t.amount_eur > monthly_vol * (1 + deviation)
        ]
        if trade_txns:
            trigger_date = max(t.txn_date for t in trade_txns)
            has_typology = any(t.is_typology for t in trade_txns)
            return [
                _make_alert(account, trigger_date, self, AlertSeverity.HIGH, has_typology)
            ]
        return []


# ======================================================================= #
# R12 — Shell Company Counterparty Wire                                    #
# ======================================================================= #


class ShellCounterpartyRule(BaseRule):
    _meta = RuleMetadata(
        rule_id="R12",
        rule_name="Shell Company Counterparty Wire",
        description=(
            "Large wire transfer to a known shell company counterparty in a "
            "high-risk jurisdiction."
        ),
        typology_affinity=["shell_company", "professional_ml"],
    )

    @property
    def metadata(self) -> RuleMetadata:
        return self._meta

    def _evaluate(
        self,
        account: Account,
        window_transactions: list[Transaction],
        all_account_transactions: list[Transaction],
    ) -> list[Alert]:
        thr = _get_global_thresholds().shell_counterparty_threshold
        shell_wires = [
            t for t in window_transactions
            if t.counterparty is not None
            and t.counterparty.is_shell
            and _high_risk_dest(t)
            and t.amount_eur >= thr
        ]
        alerts = []
        for txn in shell_wires:
            alerts.append(
                _make_alert(account, txn.txn_date, self, AlertSeverity.HIGH, txn.is_typology)
            )
        return alerts


# ======================================================================= #
# R13 — Real Estate Large Transaction                                      #
# ======================================================================= #


class RealEstateLargeRule(BaseRule):
    _meta = RuleMetadata(
        rule_id="R13",
        rule_name="Real Estate Large Transaction",
        description=(
            "Property purchase transaction above threshold triggers EDD — "
            "real estate is a primary integration vehicle."
        ),
        typology_affinity=["real_estate"],
    )

    @property
    def metadata(self) -> RuleMetadata:
        return self._meta

    def _evaluate(
        self,
        account: Account,
        window_transactions: list[Transaction],
        all_account_transactions: list[Transaction],
    ) -> list[Alert]:
        thr = _get_global_thresholds().real_estate_threshold
        prop_txns = [
            t for t in window_transactions
            if t.txn_type == TransactionType.PROPERTY_PURCHASE
            and t.amount_eur >= thr
        ]
        alerts = []
        for txn in prop_txns:
            severity = (
                AlertSeverity.CRITICAL if txn.amount_eur >= thr * 5
                else AlertSeverity.HIGH
            )
            alerts.append(
                _make_alert(account, txn.txn_date, self, severity, txn.is_typology)
            )
        return alerts


# ======================================================================= #
# R14 — Nighttime / Off-Hours Transaction Pattern                          #
# ======================================================================= #


class OffHoursPatternRule(BaseRule):
    _meta = RuleMetadata(
        rule_id="R14",
        rule_name="Off-Hours Transaction Pattern",
        description=(
            "Multiple transactions outside business hours (22:00–06:00) "
            "suggest automated layering or scripted activity."
        ),
        typology_affinity=["virtual_assets", "cross_border"],
    )

    @property
    def metadata(self) -> RuleMetadata:
        return self._meta

    def _evaluate(
        self,
        account: Account,
        window_transactions: list[Transaction],
        all_account_transactions: list[Transaction],
    ) -> list[Alert]:
        off_hours = [
            t for t in window_transactions
            if t.txn_datetime.hour >= 22 or t.txn_datetime.hour < 6
        ]
        if len(off_hours) >= 3:
            trigger_date = max(t.txn_date for t in off_hours)
            has_typology = any(t.is_typology for t in off_hours)
            return [
                _make_alert(account, trigger_date, self, AlertSeverity.MEDIUM, has_typology)
            ]
        return []


# ======================================================================= #
# R15 — Cross-Border Multi-Country Fan-Out                                 #
# ======================================================================= #


class CrossBorderFanOutRule(BaseRule):
    _meta = RuleMetadata(
        rule_id="R15",
        rule_name="Cross-Border Fan-Out",
        description=(
            "International wires sent to 3 or more distinct jurisdictions "
            "within a short window — typical of cross-border smurfing."
        ),
        typology_affinity=["cross_border"],
    )

    @property
    def metadata(self) -> RuleMetadata:
        return self._meta

    def _evaluate(
        self,
        account: Account,
        window_transactions: list[Transaction],
        all_account_transactions: list[Transaction],
    ) -> list[Alert]:
        intl_txns = [
            t for t in window_transactions
            if t.is_international and t.destination_jurisdiction is not None
        ]
        distinct_jurs = {t.destination_jurisdiction for t in intl_txns}

        if len(distinct_jurs) >= 3:
            trigger_date = max(t.txn_date for t in intl_txns)
            has_typology = any(t.is_typology for t in intl_txns)
            severity = (
                AlertSeverity.CRITICAL if len(distinct_jurs) >= 5
                else AlertSeverity.HIGH
            )
            return [_make_alert(account, trigger_date, self, severity, has_typology)]
        return []


# ======================================================================= #
# Global threshold accessor (populated by runner before rule evaluation)  #
# ======================================================================= #

# Module-level storage for thresholds — set once by the runner
_THRESHOLDS_STORE: dict = {}


def configure_thresholds(config: SimulationConfig) -> None:
    """Call this once at simulation start to configure all rules."""
    global _THRESHOLDS_STORE
    _THRESHOLDS_STORE["instance"] = config.tms_thresholds


def _get_global_thresholds():
    """Retrieve configured thresholds."""
    thr = _THRESHOLDS_STORE.get("instance")
    if thr is None:
        # Fallback: use defaults (for testing without runner)
        from ..config import TMSThresholds
        return TMSThresholds()
    return thr


# ======================================================================= #
# Rule registry                                                            #
# ======================================================================= #

ALL_RULES: list[BaseRule] = [
    CashStructuringRule(),
    LargeCashRule(),
    VelocitySpikeRule(),
    RoundAmountRule(),
    DormantAccountRule(),
    HighRiskJurisdictionRule(),
    RapidFundMovementRule(),
    LayeringRule(),
    PEPHighValueRule(),
    CryptoActivityRule(),
    TradeInvoiceAnomalyRule(),
    ShellCounterpartyRule(),
    RealEstateLargeRule(),
    OffHoursPatternRule(),
    CrossBorderFanOutRule(),
]

RULE_BY_ID: dict[str, BaseRule] = {r.metadata.rule_id: r for r in ALL_RULES}
