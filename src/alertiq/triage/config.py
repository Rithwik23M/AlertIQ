"""
TriageConfig — single source of truth for all triage experiment parameters.

All hyperparameters and split fractions are configurable and validated by
Pydantic v2.  A frozen config instance is passed through the entire triage
pipeline so every module shares identical settings.

The classifier is sklearn HistGradientBoostingClassifier (histogram GBDT),
which implements the same algorithm as LightGBM: histogram-based leaf-wise
tree growth, native handling of missing values, built-in early stopping, and
L2 regularisation.  HistGBM was chosen when LightGBM wheel availability was
confirmed unavailable in this environment; the two are algorithmically
equivalent for this use case.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field, model_validator


class SplitConfig(BaseModel):
    """Temporal train / validation / holdout split fractions (must sum to 1)."""

    train_frac: Annotated[float, Field(gt=0.0, lt=1.0)] = 0.60
    val_frac: Annotated[float, Field(gt=0.0, lt=1.0)] = 0.20
    # holdout_frac is implicit: 1 - train_frac - val_frac

    @model_validator(mode="after")
    def fracs_leave_room_for_holdout(self) -> "SplitConfig":
        if self.train_frac + self.val_frac >= 1.0:
            raise ValueError(
                "train_frac + val_frac must be < 1.0 so a holdout set remains"
            )
        return self

    @property
    def holdout_frac(self) -> float:
        return 1.0 - self.train_frac - self.val_frac


class ModelHyperparams(BaseModel):
    """Hyperparameters for the HistGradientBoostingClassifier."""

    max_iter: Annotated[int, Field(ge=10, le=2000)] = 400
    learning_rate: Annotated[float, Field(gt=0.0, le=1.0)] = 0.05
    max_leaf_nodes: Annotated[int, Field(ge=4, le=256)] = 31
    max_depth: Annotated[int, Field(ge=1, le=20)] = 6
    min_samples_leaf: Annotated[int, Field(ge=5, le=500)] = 20
    l2_regularization: Annotated[float, Field(ge=0.0, le=100.0)] = 1.0
    max_bins: Annotated[int, Field(ge=16, le=255)] = 255
    # Early stopping on the validation set (n_iter_no_change consecutive
    # iterations with no improvement of tol triggers early stop).
    early_stopping: bool = True
    n_iter_no_change: Annotated[int, Field(ge=5, le=100)] = 20
    validation_fraction: Annotated[float, Field(gt=0.0, lt=0.5)] = 0.10
    tol: Annotated[float, Field(gt=0.0)] = 1e-4


class OperationalAssumptions(BaseModel):
    """Cost and capacity assumptions for the operational interpretation layer.

    These are **simulated** costs used to express triage value in analyst-
    time equivalents.  They are not real-world financial figures.
    """

    # Analyst-hours to review one alert to a Close/Escalate decision
    hours_per_alert: Annotated[float, Field(gt=0.0)] = 0.5
    # Analyst-hours to file a SAR (escalation path only)
    hours_per_sar_filing: Annotated[float, Field(gt=0.0)] = 2.0
    # Daily analyst review capacity (hours per analyst per day)
    analyst_daily_hours: Annotated[float, Field(gt=0.0)] = 6.0
    # Review-capacity fractions to evaluate (fraction of total alerts)
    review_capacity_fractions: tuple[float, ...] = (0.10, 0.20, 0.30, 0.50, 1.00)


class TriageConfig(BaseModel):
    """Complete configuration for a Milestone 2 triage experiment run."""

    model_config = {"frozen": True}

    # ------------------------------------------------------------------ #
    # Reproducibility                                                      #
    # ------------------------------------------------------------------ #
    seed: Annotated[int, Field(ge=0, le=2**31 - 1)] = 42

    # ------------------------------------------------------------------ #
    # Data                                                                 #
    # ------------------------------------------------------------------ #
    alerts_csv: str = "data/simulation/alerts.csv"

    # ------------------------------------------------------------------ #
    # Temporal split                                                       #
    # ------------------------------------------------------------------ #
    split: SplitConfig = Field(default_factory=SplitConfig)

    # ------------------------------------------------------------------ #
    # Model                                                                #
    # ------------------------------------------------------------------ #
    hyperparams: ModelHyperparams = Field(default_factory=ModelHyperparams)

    # ------------------------------------------------------------------ #
    # Evaluation                                                           #
    # ------------------------------------------------------------------ #
    operational: OperationalAssumptions = Field(
        default_factory=OperationalAssumptions
    )

    # Classification threshold for hard-label metrics (F1, precision, recall).
    # None = select automatically from validation set to maximise F1.
    classification_threshold: float | None = None

    # ------------------------------------------------------------------ #
    # Features                                                             #
    # ------------------------------------------------------------------ #
    # These 24 features were verified in Milestone 1 to contain no label
    # leakage (no risk_category, is_typology, or true_sar signals).
    feature_columns: tuple[str, ...] = (
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
    )

    # Categorical features passed to HistGBM (native integer encoding).
    # HistGBM handles these without one-hot encoding.
    categorical_feature_indices: tuple[int, ...] = (
        # f18_very_high_jur_flag  (idx 17)
        17,
        # f20_pep_flag            (idx 19)
        19,
        # f21_adverse_media_flag  (idx 20)
        20,
        # f22_high_risk_industry  (idx 21)
        21,
    )
