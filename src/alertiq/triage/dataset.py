"""
AlertDataset — loads the simulation alerts CSV and produces temporal splits.

Temporal integrity rules
------------------------
* Splits are determined by ``triggered_date`` percentile, NOT by row index.
* Train < Validation < Holdout with hard date boundaries (no overlap).
* The same date boundaries are reused across baseline and model evaluation
  so comparisons are always on identical alert sets.
* No future information is used in any feature — verified in Milestone 1.

Leakage guard
-------------
``AlertDataset`` deliberately drops the following columns before returning
any feature matrix:
  - ``true_sar`` (the label itself)
  - ``triggered_by_typology_txn`` (a direct sub-component of true_sar)
  - ``account_id``, ``alert_id`` (identifiers, no information value)
  - ``status`` (always "open" in simulation output)

Any column in ``config.feature_columns`` that is absent from the CSV raises
immediately so silent feature drift does not produce wrong results.
"""

from __future__ import annotations

import datetime
import logging

import numpy as np
import pandas as pd

from .config import TriageConfig

log = logging.getLogger(__name__)

# Columns that must NEVER appear in a feature matrix.
_LEAKAGE_COLUMNS = frozenset(
    ["true_sar", "triggered_by_typology_txn", "account_id", "alert_id", "status"]
)


class SplitBoundaries:
    """Holds the date boundaries computed from a temporal split."""

    def __init__(
        self,
        train_end: datetime.date,
        val_end: datetime.date,
        total_alerts: int,
        train_alerts: int,
        val_alerts: int,
        holdout_alerts: int,
    ) -> None:
        self.train_end = train_end
        self.val_end = val_end
        self.total_alerts = total_alerts
        self.train_alerts = train_alerts
        self.val_alerts = val_alerts
        self.holdout_alerts = holdout_alerts

    def __repr__(self) -> str:
        return (
            f"SplitBoundaries("
            f"train_end={self.train_end}, val_end={self.val_end}, "
            f"n={self.total_alerts}: "
            f"train={self.train_alerts} val={self.val_alerts} holdout={self.holdout_alerts})"
        )


class AlertDataset:
    """Loads and splits the alert dataset for triage experiments.

    Args:
        config: Frozen TriageConfig.
        alerts_csv: Optional path override (uses config.alerts_csv by default).

    Attributes:
        df: The full alert DataFrame with all metadata columns.
        boundaries: SplitBoundaries after the dataset is loaded.
    """

    def __init__(
        self,
        config: TriageConfig,
        alerts_csv: str | None = None,
    ) -> None:
        self._config = config
        csv_path = alerts_csv or config.alerts_csv
        self.df = self._load_and_validate(csv_path)
        self.boundaries = self._compute_boundaries()
        log.info("AlertDataset loaded: %s, boundaries=%s", csv_path, self.boundaries)

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def train_Xy(self) -> tuple[np.ndarray, np.ndarray]:
        """Feature matrix and labels for the training split."""
        mask = self.df["triggered_date"] <= self.boundaries.train_end
        return self._to_Xy(self.df.loc[mask])

    def val_Xy(self) -> tuple[np.ndarray, np.ndarray]:
        """Feature matrix and labels for the validation split."""
        mask = (self.df["triggered_date"] > self.boundaries.train_end) & (
            self.df["triggered_date"] <= self.boundaries.val_end
        )
        return self._to_Xy(self.df.loc[mask])

    def holdout_Xy(self) -> tuple[np.ndarray, np.ndarray]:
        """Feature matrix and labels for the holdout (final evaluation) split."""
        mask = self.df["triggered_date"] > self.boundaries.val_end
        return self._to_Xy(self.df.loc[mask])

    def holdout_df(self) -> pd.DataFrame:
        """Full holdout DataFrame (includes metadata for error analysis)."""
        mask = self.df["triggered_date"] > self.boundaries.val_end
        return self.df.loc[mask].copy()

    def train_val_Xy(self) -> tuple[np.ndarray, np.ndarray]:
        """Merged train+val for final model re-fit after hyperparameter selection."""
        mask = self.df["triggered_date"] <= self.boundaries.val_end
        return self._to_Xy(self.df.loc[mask])

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _load_and_validate(self, path: str) -> pd.DataFrame:
        df = pd.read_csv(path, parse_dates=["triggered_date"])
        df["triggered_date"] = df["triggered_date"].dt.date

        # Verify required feature columns are present
        missing = [c for c in self._config.feature_columns if c not in df.columns]
        if missing:
            raise ValueError(
                f"AlertDataset: {len(missing)} expected feature columns absent "
                f"from {path}: {missing}"
            )

        # Verify label column
        if "true_sar" not in df.columns:
            raise ValueError(f"AlertDataset: 'true_sar' column absent from {path}")
        if df["true_sar"].isna().any():
            raise ValueError(
                f"AlertDataset: {df['true_sar'].isna().sum()} null true_sar values — "
                "ground truth must be fully populated"
            )

        # Verify no leakage columns in configured features
        leak = _LEAKAGE_COLUMNS & set(self._config.feature_columns)
        if leak:
            raise ValueError(
                f"AlertDataset: leakage columns in config.feature_columns: {leak}"
            )

        # Sort by date (deterministic ordering within date uses stable sort)
        df = df.sort_values("triggered_date", kind="stable").reset_index(drop=True)

        log.debug(
            "Loaded %d alerts, date range %s–%s, SAR rate %.2f%%",
            len(df),
            df["triggered_date"].min(),
            df["triggered_date"].max(),
            df["true_sar"].mean() * 100,
        )
        return df

    def _compute_boundaries(self) -> SplitBoundaries:
        dates = self.df["triggered_date"].values
        n = len(dates)
        train_cut = int(n * self._config.split.train_frac)
        val_cut = int(n * (self._config.split.train_frac + self._config.split.val_frac))

        # Boundaries are the date of the last alert in each split.
        # Using date-level boundaries avoids splitting a single day across sets.
        train_end = dates[train_cut - 1]
        val_end = dates[val_cut - 1]

        # Recount using the date boundaries (handles ties at boundary dates)
        train_mask = dates <= train_end
        val_mask = (dates > train_end) & (dates <= val_end)
        holdout_mask = dates > val_end

        return SplitBoundaries(
            train_end=train_end,
            val_end=val_end,
            total_alerts=n,
            train_alerts=int(train_mask.sum()),
            val_alerts=int(val_mask.sum()),
            holdout_alerts=int(holdout_mask.sum()),
        )

    def _to_Xy(self, subset: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        X = subset[list(self._config.feature_columns)].to_numpy(dtype=np.float64)
        y = subset["true_sar"].to_numpy(dtype=np.int32)
        return X, y
