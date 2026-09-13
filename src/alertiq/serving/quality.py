"""
Data quality checks applied before model inference.

Motivation
----------
Milestone 3 stress test S03 showed that when 30% of features are
zeroed-out (missing data filled with zeros) Recall@20% drops from 1.000
to 0.907 — near the 0.90 monitoring threshold.  Silent zeroing is the
most likely failure mode in production data pipelines.

These checks do NOT reject the request; they annotate the response with
DataQualityFlags so analysts can interpret flagged scores cautiously.
The API's audit log records quality flags alongside every score.

Feature groups
--------------
SHOULD_BE_POSITIVE:
    Features that represent accumulated activity and should never be
    exactly zero for a real alert.  A zero value strongly suggests a
    pipeline fill value rather than genuine zero activity.

    Note: the model can still score zero-valued features.  The flag is
    informational; it does not prevent inference.

EXTREME_VALUE_THRESHOLDS:
    Upper bounds derived from the M1/M3 training dataset.  Values beyond
    these bounds are more than ~5σ from the training distribution and may
    indicate data-pipeline unit errors (e.g. amounts in cents instead of
    pounds) or genuine outliers the model has not seen during training.

    These are approximate; a future production release should derive them
    from the actual training dataset statistics (mean ± 5σ) and version
    them with the model artifact.
"""

from __future__ import annotations

from alertiq.serving.schema import AlertFeatures, DataQualityFlags

# Features that should be > 0 for any real alert.
# An alert that genuinely has zero 30-day volume might exist (dormant account),
# but zero is the default fill for missing pipeline values, so we flag it.
SHOULD_BE_POSITIVE: frozenset[str] = frozenset({
    "f01_vol_7d_log",
    "f02_vol_30d_log",
    "f04_max_txn_log",
    "f06_txn_count_7d",
    "f07_txn_count_30d",
    "f10_account_age_days",
})

# Approximate upper bounds for extreme-value detection.
# Values beyond these are flagged; inference continues.
EXTREME_VALUE_THRESHOLDS: dict[str, float] = {
    "f01_vol_7d_log": 20.0,      # log(~500M)
    "f02_vol_30d_log": 22.0,     # log(~3.5B)
    "f03_vol_ratio_7_30": 10.0,
    "f04_max_txn_log": 18.0,     # log(~65M per transaction)
    "f05_vol_vs_revenue": 100.0,
    "f06_txn_count_7d": 5000,
    "f07_txn_count_30d": 15000,
    "f08_velocity_ratio": 20.0,
    "f09_recency_gap_days": 365.0,
    "f10_account_age_days": 20000.0,
    "f12_structuring_count_30d": 200,
    "f13_round_amount_count_30d": 500,
    "f17_distinct_jurisdictions_30d": 50,
    "f23_prior_alerts_90d": 100,
    "f24_account_jurisdiction_score": 1.0,  # schema-enforced, redundant but explicit
}


def check_data_quality(features: AlertFeatures) -> DataQualityFlags:
    """Inspect *features* for quality issues and return DataQualityFlags.

    Parameters
    ----------
    features:
        A validated ``AlertFeatures`` instance.

    Returns
    -------
    DataQualityFlags
        Populated flags; ``quality_warning`` is True if any issue was
        detected.
    """
    feature_dict = features.model_dump()

    # --- Zero-value check ---
    zero_names: list[str] = [
        name for name in SHOULD_BE_POSITIVE
        if _is_exactly_zero(feature_dict.get(name))
    ]

    # --- Extreme-value check ---
    extreme_names: list[str] = [
        name
        for name, upper in EXTREME_VALUE_THRESHOLDS.items()
        if _exceeds(feature_dict.get(name), upper)
    ]

    return DataQualityFlags(
        has_zeroed_features=bool(zero_names),
        zero_feature_names=sorted(zero_names),
        has_extreme_values=bool(extreme_names),
        extreme_feature_names=sorted(extreme_names),
        quality_warning=bool(zero_names or extreme_names),
    )


def _is_exactly_zero(value: object) -> bool:
    """True if *value* is numeric and exactly equal to 0."""
    if isinstance(value, (int, float)):
        return value == 0
    return False


def _exceeds(value: object, upper: float) -> bool:
    """True if *value* is numeric and strictly greater than *upper*."""
    if isinstance(value, (int, float)):
        return float(value) > upper
    return False
