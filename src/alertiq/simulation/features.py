"""
Alert feature computation.

Computes 24 observable features for each alert at alert creation time.
All features are derived from transaction history and account metadata
visible at the alert date — no ground truth (is_typology, risk_category)
is used here.

Feature groups:
  F01–F05  Transaction volume features
  F06–F10  Velocity and frequency features
  F11–F15  Cash and channel features
  F16–F19  Counterparty and jurisdiction features
  F20–F22  Account relationship features
  F23–F24  Alert-level meta features

These features form the observation layer for the ML model (M2).
"""

from __future__ import annotations

import datetime
import math
from collections import defaultdict

from .entities import (
    Account,
    Alert,
    Channel,
    JurisdictionRisk,
    Transaction,
    TransactionType,
)

# Look-back windows used in feature computation (days)
_W7 = 7
_W30 = 30
_W90 = 90


def _txns_in_window(
    txns: list[Transaction],
    ref_date: datetime.date,
    days: int,
) -> list[Transaction]:
    """Return transactions within `days` before ref_date (inclusive)."""
    cutoff = ref_date - datetime.timedelta(days=days)
    return [t for t in txns if cutoff <= t.txn_date <= ref_date]


def _safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    if denominator == 0:
        return default
    return numerator / denominator


def _log1p(x: float) -> float:
    return math.log1p(max(0.0, x))


def compute_alert_features(
    alert: Alert,
    account: Account,
    account_transactions: list[Transaction],
) -> dict[str, float]:
    """Compute 24 features for an alert.

    Args:
        alert: The alert being enriched (true_sar must still be None).
        account: The account that generated the alert.
        account_transactions: All transactions for this account up to and
            including alert.triggered_date (no look-ahead).

    Returns:
        Dict of feature_name → float.
    """
    ref = alert.triggered_date
    all_txns = [t for t in account_transactions if t.txn_date <= ref]

    w7 = _txns_in_window(all_txns, ref, _W7)
    w30 = _txns_in_window(all_txns, ref, _W30)
    w90 = _txns_in_window(all_txns, ref, _W90)

    # ------------------------------------------------------- #
    # F01–F05: Volume features                                 #
    # ------------------------------------------------------- #

    vol_7d = sum(t.amount_eur for t in w7)
    vol_30d = sum(t.amount_eur for t in w30)
    vol_90d = sum(t.amount_eur for t in w90)

    # F01: Total EUR volume, 7-day window (log-scaled)
    f01_vol_7d_log = _log1p(vol_7d)

    # F02: Total EUR volume, 30-day window (log-scaled)
    f02_vol_30d_log = _log1p(vol_30d)

    # F03: Volume ratio 7d / 30d  (1.0 = proportional; >1 = spike)
    f03_vol_ratio_7_30 = _safe_div(vol_7d * 30, vol_30d * 7, default=1.0)

    # F04: Max single transaction amount in 30d (log-scaled)
    max_amt_30d = max((t.amount_eur for t in w30), default=0.0)
    f04_max_txn_log = _log1p(max_amt_30d)

    # F05: Volume vs declared monthly revenue ratio
    f05_vol_vs_revenue = _safe_div(vol_30d, account.expected_monthly_volume, default=0.0)

    # ------------------------------------------------------- #
    # F06–F10: Velocity and frequency features                 #
    # ------------------------------------------------------- #

    n_7d = len(w7)
    n_30d = len(w30)
    n_90d = len(w90)

    # F06: Transaction count, 7-day window
    f06_txn_count_7d = float(n_7d)

    # F07: Transaction count, 30-day window
    f07_txn_count_30d = float(n_30d)

    # F08: Velocity ratio: 7d count vs 30d mean daily count
    daily_mean_30d = n_30d / 30.0
    f08_velocity_ratio = _safe_div(n_7d / 7.0, daily_mean_30d, default=1.0)

    # F09: Days between last two transactions (recency gap)
    dates = sorted({t.txn_date for t in all_txns})
    if len(dates) >= 2:
        f09_recency_gap_days = float((dates[-1] - dates[-2]).days)
    else:
        f09_recency_gap_days = float((ref - account.onboard_date).days)

    # F10: Account age in days (proxy for relationship depth)
    f10_account_age_days = float((ref - account.onboard_date).days)

    # ------------------------------------------------------- #
    # F11–F15: Cash and channel features                       #
    # ------------------------------------------------------- #

    cash_txns_30d = [
        t for t in w30
        if t.txn_type in (TransactionType.CASH_DEPOSIT, TransactionType.CASH_WITHDRAWAL)
    ]
    cash_vol_30d = sum(t.amount_eur for t in cash_txns_30d)

    # F11: Fraction of 30d volume in cash transactions
    f11_cash_fraction_30d = _safe_div(cash_vol_30d, vol_30d)

    # F12: Number of structuring-like deposits (70–99% of 10,000)
    structuring_like = [
        t for t in w30
        if t.txn_type == TransactionType.CASH_DEPOSIT
        and 7_000 <= t.amount_eur < 10_000
    ]
    f12_structuring_count_30d = float(len(structuring_like))

    # F13: Number of round-amount transactions (multiples of 500, >= 5000)
    round_txns = [
        t for t in w30
        if t.amount_eur >= 5_000 and t.amount_eur % 500 == 0
    ]
    f13_round_amount_count_30d = float(len(round_txns))

    # F14: Fraction of transactions via online/mobile channel (digital)
    digital_count = sum(
        1 for t in w30
        if t.channel in (Channel.ONLINE, Channel.MOBILE, Channel.CRYPTO_WALLET)
    )
    f14_digital_channel_fraction = _safe_div(digital_count, n_30d)

    # F15: Night-time transactions (22:00–06:00) in 30d as fraction
    night_count = sum(
        1 for t in w30
        if t.txn_datetime.hour >= 22 or t.txn_datetime.hour < 6
    )
    f15_night_fraction_30d = _safe_div(night_count, n_30d)

    # ------------------------------------------------------- #
    # F16–F19: Counterparty and jurisdiction features          #
    # ------------------------------------------------------- #

    intl_txns_30d = [t for t in w30 if t.is_international]
    intl_vol_30d = sum(t.amount_eur for t in intl_txns_30d)

    # F16: Fraction of 30d volume in international transactions
    f16_intl_fraction_30d = _safe_div(intl_vol_30d, vol_30d)

    # F17: Number of distinct counterparty jurisdictions in 30d
    jurs_30d = {
        t.destination_jurisdiction
        for t in w30
        if t.destination_jurisdiction is not None
    }
    f17_distinct_jurisdictions_30d = float(len(jurs_30d))

    # F18: Flag — any transaction to VERY_HIGH risk jurisdiction in 90d
    any_very_high = any(
        t.destination_jurisdiction == JurisdictionRisk.VERY_HIGH
        for t in w90
    )
    f18_very_high_jur_flag = 1.0 if any_very_high else 0.0

    # F19: Fraction of counterparties that are shell companies (30d)
    cp_txns = [t for t in w30 if t.counterparty is not None]
    shell_count = sum(1 for t in cp_txns if t.counterparty.is_shell)
    f19_shell_counterparty_fraction = _safe_div(shell_count, len(cp_txns))

    # ------------------------------------------------------- #
    # F20–F22: Account relationship features                   #
    # ------------------------------------------------------- #

    # F20: PEP link flag (observable KYC attribute)
    f20_pep_flag = 1.0 if account.has_pep_link else 0.0

    # F21: Adverse media flag
    f21_adverse_media_flag = 1.0 if account.has_adverse_media else 0.0

    # F22: High-risk industry flag
    f22_high_risk_industry = 1.0 if account.is_high_risk_industry else 0.0

    # ------------------------------------------------------- #
    # F23–F24: Alert meta features                             #
    # ------------------------------------------------------- #

    # F23: Number of alerts for this account in 90d (alert recidivism)
    # Note: we don't have alert history here; this is set by runner.py
    # to the pre-trigger count.  Default to 0.
    f23_prior_alerts_90d = 0.0

    # F24: Account base jurisdiction risk score
    jur_score_map = {
        JurisdictionRisk.LOW: 0.0,
        JurisdictionRisk.MEDIUM: 0.33,
        JurisdictionRisk.HIGH: 0.67,
        JurisdictionRisk.VERY_HIGH: 1.0,
    }
    f24_account_jurisdiction_score = jur_score_map.get(account.jurisdiction, 0.0)

    return {
        "f01_vol_7d_log": f01_vol_7d_log,
        "f02_vol_30d_log": f02_vol_30d_log,
        "f03_vol_ratio_7_30": f03_vol_ratio_7_30,
        "f04_max_txn_log": f04_max_txn_log,
        "f05_vol_vs_revenue": f05_vol_vs_revenue,
        "f06_txn_count_7d": f06_txn_count_7d,
        "f07_txn_count_30d": f07_txn_count_30d,
        "f08_velocity_ratio": f08_velocity_ratio,
        "f09_recency_gap_days": f09_recency_gap_days,
        "f10_account_age_days": f10_account_age_days,
        "f11_cash_fraction_30d": f11_cash_fraction_30d,
        "f12_structuring_count_30d": f12_structuring_count_30d,
        "f13_round_amount_count_30d": f13_round_amount_count_30d,
        "f14_digital_channel_fraction": f14_digital_channel_fraction,
        "f15_night_fraction_30d": f15_night_fraction_30d,
        "f16_intl_fraction_30d": f16_intl_fraction_30d,
        "f17_distinct_jurisdictions_30d": f17_distinct_jurisdictions_30d,
        "f18_very_high_jur_flag": f18_very_high_jur_flag,
        "f19_shell_counterparty_fraction": f19_shell_counterparty_fraction,
        "f20_pep_flag": f20_pep_flag,
        "f21_adverse_media_flag": f21_adverse_media_flag,
        "f22_high_risk_industry": f22_high_risk_industry,
        "f23_prior_alerts_90d": f23_prior_alerts_90d,
        "f24_account_jurisdiction_score": f24_account_jurisdiction_score,
    }


FEATURE_NAMES: list[str] = [
    "f01_vol_7d_log",
    "f02_vol_30d_log",
    "f03_vol_ratio_7_30",
    "f04_max_txn_log",
    "f05_vol_vs_revenue",
    "f06_txn_count_7d",
    "f07_txn_count_30d",
    "f08_velocity_ratio",
    "f09_recency_gap_days",
    "f10_account_age_days",
    "f11_cash_fraction_30d",
    "f12_structuring_count_30d",
    "f13_round_amount_count_30d",
    "f14_digital_channel_fraction",
    "f15_night_fraction_30d",
    "f16_intl_fraction_30d",
    "f17_distinct_jurisdictions_30d",
    "f18_very_high_jur_flag",
    "f19_shell_counterparty_fraction",
    "f20_pep_flag",
    "f21_adverse_media_flag",
    "f22_high_risk_industry",
    "f23_prior_alerts_90d",
    "f24_account_jurisdiction_score",
]
