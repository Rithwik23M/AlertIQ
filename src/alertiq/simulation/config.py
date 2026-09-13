"""
SimulationConfig — single source of truth for all simulation parameters.

All parameters are configurable and validated by Pydantic v2.
A frozen config instance is passed through the entire pipeline so
every module shares the same settings and the simulation is fully
reproducible from config + seed alone.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, Field, field_validator, model_validator


class PopulationMix(BaseModel):
    """Proportion of accounts in each risk category.  Must sum to 1.0."""

    low_risk: Annotated[float, Field(ge=0.0, le=1.0)] = 0.55
    medium_risk: Annotated[float, Field(ge=0.0, le=1.0)] = 0.30
    high_risk: Annotated[float, Field(ge=0.0, le=1.0)] = 0.10
    active_ml: Annotated[float, Field(ge=0.0, le=1.0)] = 0.05

    @model_validator(mode="after")
    def proportions_sum_to_one(self) -> "PopulationMix":
        total = self.low_risk + self.medium_risk + self.high_risk + self.active_ml
        if abs(total - 1.0) > 1e-9:
            raise ValueError(
                f"PopulationMix proportions must sum to 1.0, got {total:.6f}"
            )
        return self


class TypologyWeights(BaseModel):
    """Relative frequency weights for each FATF typology (unnormalised)."""

    structuring: Annotated[float, Field(ge=0.0)] = 0.30
    shell_company: Annotated[float, Field(ge=0.0)] = 0.20
    real_estate: Annotated[float, Field(ge=0.0)] = 0.10
    trade_based: Annotated[float, Field(ge=0.0)] = 0.10
    cash_intensive: Annotated[float, Field(ge=0.0)] = 0.10
    professional_ml: Annotated[float, Field(ge=0.0)] = 0.08
    virtual_assets: Annotated[float, Field(ge=0.0)] = 0.07
    cross_border: Annotated[float, Field(ge=0.0)] = 0.05

    @model_validator(mode="after")
    def at_least_one_nonzero(self) -> "TypologyWeights":
        values = [
            self.structuring,
            self.shell_company,
            self.real_estate,
            self.trade_based,
            self.cash_intensive,
            self.professional_ml,
            self.virtual_assets,
            self.cross_border,
        ]
        if sum(values) == 0.0:
            raise ValueError("At least one typology weight must be non-zero")
        return self

    def normalised(self) -> dict[str, float]:
        """Return weights as a probability distribution."""
        values = {
            "structuring": self.structuring,
            "shell_company": self.shell_company,
            "real_estate": self.real_estate,
            "trade_based": self.trade_based,
            "cash_intensive": self.cash_intensive,
            "professional_ml": self.professional_ml,
            "virtual_assets": self.virtual_assets,
            "cross_border": self.cross_border,
        }
        total = sum(values.values())
        return {k: v / total for k, v in values.items()}


class TMSThresholds(BaseModel):
    """Configurable thresholds for TMS rule engine."""

    # Cash structuring
    ctr_threshold: Annotated[float, Field(gt=0)] = 10_000.0
    structuring_window_days: Annotated[int, Field(ge=1, le=90)] = 10
    structuring_min_txns: Annotated[int, Field(ge=2, le=20)] = 3

    # Large cash
    large_cash_threshold: Annotated[float, Field(gt=0)] = 8_000.0

    # Velocity spike — R03 fires when 7-day transaction count exceeds
    # velocity_spike_ratio × the account's 30-day average 7-day rate.
    # velocity_threshold_count is the minimum absolute 7-day count required
    # before the ratio test is applied (avoids noise from nearly-dormant accounts).
    velocity_window_days: Annotated[int, Field(ge=1, le=30)] = 7
    velocity_threshold_count: Annotated[int, Field(ge=2, le=500)] = 10
    velocity_spike_ratio: Annotated[float, Field(gt=1.0, le=20.0)] = 2.5

    # Round-amount
    round_amount_precision: Annotated[float, Field(gt=0)] = 500.0
    round_amount_min: Annotated[float, Field(gt=0)] = 5_000.0
    round_amount_window_days: Annotated[int, Field(ge=1, le=90)] = 30
    round_amount_min_count: Annotated[int, Field(ge=1, le=20)] = 3

    # Dormant account activity
    dormancy_threshold_days: Annotated[int, Field(ge=30, le=730)] = 90

    # High-risk jurisdiction
    high_risk_jurisdiction_threshold: Annotated[float, Field(gt=0)] = 5_000.0

    # Rapid fund movement
    rapid_movement_hours: Annotated[int, Field(ge=1, le=72)] = 48
    rapid_movement_ratio: Annotated[float, Field(gt=0, le=1.0)] = 0.80

    # Layering
    layering_min_hops: Annotated[int, Field(ge=2, le=10)] = 3
    layering_window_days: Annotated[int, Field(ge=1, le=30)] = 5

    # PEP / adverse media proxy
    pep_threshold: Annotated[float, Field(gt=0)] = 2_000.0

    # Crypto-related
    crypto_threshold: Annotated[float, Field(gt=0)] = 1_000.0

    # Trade-based ML
    trade_invoice_deviation: Annotated[float, Field(gt=0)] = 0.30

    # Shell company proxy
    shell_counterparty_threshold: Annotated[float, Field(gt=0)] = 20_000.0

    # Real estate proxy
    real_estate_threshold: Annotated[float, Field(gt=0)] = 100_000.0


class SimulationConfig(BaseModel):
    """Complete configuration for a single simulation run.

    Pass this frozen instance to all simulation components.
    Reproducibility guarantee: same ``seed`` + same ``SimulationConfig``
    → bitwise-identical output.
    """

    model_config = {"frozen": True}

    # ------------------------------------------------------------------ #
    # Reproducibility                                                      #
    # ------------------------------------------------------------------ #
    seed: Annotated[int, Field(ge=0, le=2**31 - 1)] = 42

    # ------------------------------------------------------------------ #
    # Population                                                           #
    # ------------------------------------------------------------------ #
    n_accounts: Annotated[int, Field(ge=10, le=100_000)] = 1_000
    population_mix: PopulationMix = Field(default_factory=PopulationMix)

    # ------------------------------------------------------------------ #
    # Simulation period                                                    #
    # ------------------------------------------------------------------ #
    start_date: str = "2023-01-01"
    end_date: str = "2023-12-31"

    @field_validator("start_date", "end_date")
    @classmethod
    def valid_date(cls, v: str) -> str:
        import datetime

        try:
            datetime.date.fromisoformat(v)
        except ValueError as exc:
            raise ValueError(f"Expected ISO date YYYY-MM-DD, got '{v}'") from exc
        return v

    @model_validator(mode="after")
    def start_before_end(self) -> "SimulationConfig":
        import datetime

        start = datetime.date.fromisoformat(self.start_date)
        end = datetime.date.fromisoformat(self.end_date)
        if start >= end:
            raise ValueError(
                f"start_date ({self.start_date}) must be before end_date ({self.end_date})"
            )
        return self

    # ------------------------------------------------------------------ #
    # Typology parameters                                                  #
    # ------------------------------------------------------------------ #
    typology_weights: TypologyWeights = Field(default_factory=TypologyWeights)

    # Expected fraction of active-ML accounts that run a typology per day
    typology_daily_activation_prob: Annotated[float, Field(gt=0, le=1.0)] = 0.40

    # ------------------------------------------------------------------ #
    # TMS thresholds                                                       #
    # ------------------------------------------------------------------ #
    tms_thresholds: TMSThresholds = Field(default_factory=TMSThresholds)

    # ------------------------------------------------------------------ #
    # Transaction generation parameters                                   #
    # ------------------------------------------------------------------ #
    # Mean number of routine transactions per account per day
    txn_daily_mean: Annotated[float, Field(gt=0)] = 3.5
    txn_daily_std: Annotated[float, Field(ge=0)] = 1.2

    # Amount distribution (log-normal)
    txn_amount_log_mean: Annotated[float, Field(gt=0)] = 6.5   # ln(EUR ~665)
    txn_amount_log_std: Annotated[float, Field(gt=0)] = 1.4

    # ------------------------------------------------------------------ #
    # Output                                                               #
    # ------------------------------------------------------------------ #
    output_dir: Path = Path("data/simulation")
    write_transactions: bool = True
    write_alerts: bool = True
    write_accounts: bool = True

    def simulation_days(self) -> int:
        """Number of calendar days in the simulation period."""
        import datetime

        start = datetime.date.fromisoformat(self.start_date)
        end = datetime.date.fromisoformat(self.end_date)
        return (end - start).days
