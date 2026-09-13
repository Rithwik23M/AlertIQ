"""
Pydantic v2 request / response schemas for the AlertIQ scoring API.

Design decisions
----------------
1. schema_version (int) is a required field on every ScoreRequest.
   Unknown schema versions are REJECTED with HTTP 422, not silently
   downgraded.  This prevents stale clients from sending misaligned
   feature sets.

2. All 24 feature fields are individually typed with domain-appropriate
   bounds.  Pydantic rejects invalid values before any numpy array is
   constructed.

3. Floating-point features use Python ``float`` (not ``Optional[float]``).
   Clients MUST send all 24 features.  Missing features are rejected
   (HTTP 422) because silent imputation would produce undisclosed
   score changes.

4. Binary flag features use ``int`` with ``Literal[0, 1]`` — the
   underlying model ingests these as categorical integers; bool would
   require a conversion step.

5. ScoreResponse does NOT include a "SAR probability" label, a
   "suspicious" label, or any compliance determination.  The score is
   presented as a relative risk priority for analyst review.

6. batch_id on BatchScoreRequest is optional but strongly recommended
   by the API documentation for audit correlation.

7. operating_mode in every response is always "capacity_ranking" —
   clients must NOT apply a fixed decision threshold to these scores.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

# ------------------------------------------------------------------ #
# Constants                                                            #
# ------------------------------------------------------------------ #

SUPPORTED_SCHEMA_VERSIONS: frozenset[int] = frozenset({1})

DISCLAIMER = (
    "AlertIQ scores are a relative alert prioritisation indicator for "
    "analyst review only. They are not a compliance determination and "
    "do not constitute a SAR filing decision. Human analysts review all "
    "flagged alerts."
)


# ------------------------------------------------------------------ #
# Shared types                                                         #
# ------------------------------------------------------------------ #

LogPosFloat = Annotated[float, Field(ge=0.0, description="Log-transformed positive value")]
Fraction = Annotated[float, Field(ge=0.0, le=1.0, description="Fraction in [0, 1]")]
BinaryFlag = Annotated[int, Field(ge=0, le=1, description="Binary flag: 0 or 1")]
NonNegFloat = Annotated[float, Field(ge=0.0, description="Non-negative float")]
PosInt = Annotated[int, Field(ge=0, description="Non-negative integer")]
PosFloat = Annotated[float, Field(ge=0.0, description="Non-negative float")]


# ------------------------------------------------------------------ #
# Feature sub-schema                                                   #
# ------------------------------------------------------------------ #

class AlertFeatures(BaseModel):
    """The 24-feature contract (schema_version=1).

    Column order is enforced by ``to_array()``: features are assembled
    in the canonical order defined by ``TriageConfig.feature_columns``.
    This order MUST match the training-time order — the model is
    order-sensitive.
    """

    model_config = {"extra": "forbid"}  # unknown fields → 422

    # Volume / amount
    f01_vol_7d_log: LogPosFloat
    f02_vol_30d_log: LogPosFloat
    f03_vol_ratio_7_30: NonNegFloat
    f04_max_txn_log: LogPosFloat
    f05_vol_vs_revenue: NonNegFloat
    # Transaction counts and velocity
    f06_txn_count_7d: PosInt
    f07_txn_count_30d: PosInt
    f08_velocity_ratio: NonNegFloat
    # Recency and account tenure
    f09_recency_gap_days: NonNegFloat
    f10_account_age_days: NonNegFloat
    # Behavioural fractions
    f11_cash_fraction_30d: Fraction
    f12_structuring_count_30d: PosInt
    f13_round_amount_count_30d: PosInt
    f14_digital_channel_fraction: Fraction
    f15_night_fraction_30d: Fraction
    f16_intl_fraction_30d: Fraction
    # Jurisdiction and counterparty risk
    f17_distinct_jurisdictions_30d: PosInt
    f18_very_high_jur_flag: BinaryFlag
    f19_shell_counterparty_fraction: Fraction
    # Customer-level risk flags (categorical; treated natively by HistGBM)
    f20_pep_flag: BinaryFlag
    f21_adverse_media_flag: BinaryFlag
    f22_high_risk_industry: BinaryFlag
    # Historical context
    f23_prior_alerts_90d: PosInt
    f24_account_jurisdiction_score: NonNegFloat = Field(ge=0.0, le=1.0)

    def to_array(self) -> list[float]:
        """Return features as an ordered list matching TriageConfig.feature_columns.

        The explicit ordering here must stay in sync with the canonical
        feature_columns tuple in TriageConfig.  Integration tests verify
        this at test time.
        """
        return [
            self.f01_vol_7d_log,
            self.f02_vol_30d_log,
            self.f03_vol_ratio_7_30,
            self.f04_max_txn_log,
            self.f05_vol_vs_revenue,
            float(self.f06_txn_count_7d),
            float(self.f07_txn_count_30d),
            self.f08_velocity_ratio,
            self.f09_recency_gap_days,
            self.f10_account_age_days,
            self.f11_cash_fraction_30d,
            float(self.f12_structuring_count_30d),
            float(self.f13_round_amount_count_30d),
            self.f14_digital_channel_fraction,
            self.f15_night_fraction_30d,
            self.f16_intl_fraction_30d,
            float(self.f17_distinct_jurisdictions_30d),
            float(self.f18_very_high_jur_flag),
            self.f19_shell_counterparty_fraction,
            float(self.f20_pep_flag),
            float(self.f21_adverse_media_flag),
            float(self.f22_high_risk_industry),
            float(self.f23_prior_alerts_90d),
            self.f24_account_jurisdiction_score,
        ]


# ------------------------------------------------------------------ #
# Request schemas                                                      #
# ------------------------------------------------------------------ #

class ScoreRequest(BaseModel):
    """Single-alert scoring request.

    Attributes
    ----------
    alert_id:
        Client-supplied identifier for audit correlation.  Stored in the
        audit log; never used for model inference.  Must be non-empty.
    schema_version:
        Feature schema revision.  Must be in SUPPORTED_SCHEMA_VERSIONS.
        Currently only version 1 is supported.  Future schema changes
        increment this value; old clients will receive HTTP 422 until
        updated to send the new schema.
    features:
        The 24 model features.  All fields are required; missing fields
        produce HTTP 422.
    """

    alert_id: Annotated[str, Field(min_length=1, max_length=128)]
    schema_version: int
    features: AlertFeatures


class BatchScoreRequest(BaseModel):
    """Batch alert scoring request (up to 500 alerts per request).

    Attributes
    ----------
    batch_id:
        Optional client-supplied batch identifier for log correlation.
    alerts:
        List of alert scoring requests (1–500 items).  Each item is a
        full ScoreRequest including its own alert_id and schema_version.
        All alerts in a batch MUST use the same schema_version.
    """

    batch_id: Annotated[str | None, Field(default=None, max_length=128)]
    alerts: Annotated[list[ScoreRequest], Field(min_length=1, max_length=500)]


# ------------------------------------------------------------------ #
# Response schemas                                                     #
# ------------------------------------------------------------------ #

class DataQualityFlags(BaseModel):
    """Data quality assessment for a single alert."""

    has_zeroed_features: bool = Field(
        description="True if any feature that should be non-zero is exactly 0.0"
    )
    zero_feature_names: list[str] = Field(
        default_factory=list,
        description="Names of features that are unexpectedly zero"
    )
    has_extreme_values: bool = Field(
        description="True if any feature is more than 5 standard deviations from its training mean"
    )
    extreme_feature_names: list[str] = Field(
        default_factory=list,
        description="Names of features with extreme values"
    )
    quality_warning: bool = Field(
        description="True if any quality issue was detected — interpret score with caution"
    )


class ScoreResponse(BaseModel):
    """Single-alert scoring response.

    The risk_score is a probability in [0, 1] that measures relative
    investigative priority.  Higher scores should be reviewed first.

    IMPORTANT: This score does NOT determine whether a SAR will be filed.
    Human analysts make all SAR filing decisions after reviewing flagged
    alerts.  Do not apply a fixed decision threshold to these scores.
    """

    alert_id: str
    risk_score: Annotated[float, Field(ge=0.0, le=1.0, description=(
        "Relative investigative priority score in [0, 1]. "
        "Higher = review earlier. "
        "NOT a SAR probability or compliance determination."
    ))]
    model_version: str
    schema_version: int
    scored_at: datetime
    operating_mode: Literal["capacity_ranking"] = "capacity_ranking"
    data_quality_flags: DataQualityFlags
    disclaimer: str = DISCLAIMER


class BatchAlertResult(BaseModel):
    """Result for a single alert within a batch response."""

    alert_id: str
    risk_score: Annotated[float | None, Field(description=(
        "Risk score, or null if this alert failed to score (see error)."
    ))]
    status: Literal["scored", "error"]
    error: str | None = None
    data_quality_flags: DataQualityFlags | None = None


class BatchScoreResponse(BaseModel):
    """Batch alert scoring response."""

    batch_id: str | None
    model_version: str
    schema_version: int
    scored_at: datetime
    operating_mode: Literal["capacity_ranking"] = "capacity_ranking"
    total: int
    succeeded: int
    failed: int
    results: list[BatchAlertResult]
    disclaimer: str = DISCLAIMER


# ------------------------------------------------------------------ #
# Health and model-info responses                                      #
# ------------------------------------------------------------------ #

class HealthResponse(BaseModel):
    """GET /health response.

    Deployment traceability fields (git_sha, image_digest) are populated from
    environment variables injected by the CD workflow at deploy time.  They are
    ``None`` in local development where those variables are not set.
    """

    status: Literal["ok", "degraded", "error"]
    model_loaded: bool
    model_version: str | None
    schema_version: int | None
    checked_at: datetime
    # Deployment traceability — injected by CD workflow via env vars.
    git_sha: str | None = None
    image_digest: str | None = None


class ModelInfoResponse(BaseModel):
    """GET /model/info response."""

    model_version: str
    schema_version: int
    operating_mode: Literal["capacity_ranking"]
    feature_count: int
    feature_columns: list[str]
    trained_at: str
    training_rows: int
    best_iter: int
    classification_threshold: float = Field(
        description=(
            "F1-optimal classification threshold (supplementary diagnostic only). "
            "Not used in capacity-ranking mode. Do not apply this threshold to risk_score."
        )
    )
    disclaimer: str = DISCLAIMER
