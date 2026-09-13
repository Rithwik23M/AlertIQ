"""
Baseline scorers for alert triage.

Two baselines are implemented:

1. **RandomScorer** — assigns a uniform-random score in [0, 1].  This is the
   theoretical lower-bound for any ranking system and represents a team with
   no prioritisation at all (pure FIFO/random queue processing).

2. **SeverityScorer** — maps alert severity to a fixed priority tier and
   breaks ties with a uniform random draw.  This represents the most common
   real-world approach before an ML triage model is deployed: analysts are
   told to "work CRITICAL first, then HIGH, then MEDIUM, then LOW".

Both scorers implement the same ``score(X, df)`` interface as ``TriageScorer``
so they can be passed to ``Evaluator`` transparently.

Why severity is a reasonable (not artificially weak) baseline
-------------------------------------------------------------
Alert severity in the simulation is assigned by TMS rules based on the
triggering condition (e.g. structuring ratio, velocity spike magnitude).
It correlates with true SAR status — CRITICAL alerts have higher SAR rates
than LOW alerts — so the severity baseline should be meaningfully better
than pure random.  If the ML model cannot beat severity-based triage, the
features F01–F24 contain no information beyond what the TMS rule engine
already encodes.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import TriageConfig

# Severity → priority score (higher = reviewed first)
_SEVERITY_PRIORITY: dict[str, float] = {
    "critical": 1.0,
    "high": 0.75,
    "medium": 0.50,
    "low": 0.25,
}


class RandomScorer:
    """Assigns a uniform-random score in [0, 1].

    Seeded from TriageConfig.seed for reproducibility.
    """

    def __init__(self, config: TriageConfig) -> None:
        self._rng = np.random.default_rng(config.seed)

    def score(self, X: np.ndarray, df: pd.DataFrame) -> np.ndarray:  # noqa: ARG002
        """Return random scores; X is accepted but ignored."""
        return self._rng.random(len(df))

    @property
    def name(self) -> str:
        return "baseline_random"


class SeverityScorer:
    """Ranks alerts by rule severity with tie-breaking random noise.

    The severity tier is read from the ``severity`` column of the alert
    DataFrame.  Ties within a tier are broken by a small uniform-random
    perturbation so that same-severity alerts are randomly ordered (matching
    what an analyst team would do in practice).

    This scorer requires the DataFrame to contain a ``severity`` column.
    """

    def __init__(self, config: TriageConfig) -> None:
        self._rng = np.random.default_rng(config.seed + 1)  # different seed from random

    def score(self, X: np.ndarray, df: pd.DataFrame) -> np.ndarray:  # noqa: ARG002
        """Return severity-based priority scores in [0, 1]."""
        if "severity" not in df.columns:
            raise ValueError(
                "SeverityScorer requires a 'severity' column in the alert DataFrame"
            )
        severity_scores = (
            df["severity"].str.lower().map(_SEVERITY_PRIORITY).fillna(0.0).to_numpy()
        )
        noise = self._rng.uniform(0, 1e-6, size=len(df))
        return severity_scores + noise

    @property
    def name(self) -> str:
        return "baseline_severity"


# Public alias — the primary baseline used for comparison is SeverityScorer
# because it is a plausible real-world alternative.  RandomScorer is the
# lower-bound reference.
BaselineScorer = SeverityScorer
