"""
InferenceScorer — stateless inference wrapper for the AlertIQ serving layer.

Responsibilities
----------------
1. Holds a loaded ModelArtifact (immutable after startup).
2. Converts a validated AlertFeatures object into a numpy array in the
   correct feature order.
3. Calls TriageScorer.score() to obtain a probability in [0, 1].
4. Enforces the capacity-ranking policy: no fixed decision threshold is
   applied; the raw probability IS the API output.
5. Validates that the incoming schema_version matches the artifact's
   schema_version before performing inference.

Operating policy enforcement
-----------------------------
The API NEVER converts a risk_score into a binary 0/1 prediction.
TriageScorer.predict() is not called.  The capacity-ranking policy
(review the top-K alerts by score) is the sole operating mode.

This is not merely a code choice — it reflects the Milestone 3 finding
that the F1-optimal classification threshold ranged from 0.056 to 0.253
across walk-forward windows (range = 0.198).  Hard-coding any single
threshold would produce unreliable binary outputs as the score
distribution shifts with customer portfolio changes.

Schema mismatch handling
------------------------
If the request schema_version != artifact.schema_version, the scorer
raises SchemaVersionMismatchError.  The API catches this and returns
HTTP 422 with a clear error message.  The request is logged with
status="error" in the audit log.

Feature array construction
--------------------------
AlertFeatures.to_array() returns features in the order defined by
TriageConfig.feature_columns.  The serving layer does not re-sort or
re-map features; it trusts the schema contract validated at build time.
"""

from __future__ import annotations

import logging
import time

import numpy as np

from alertiq.serving.artifact import ModelArtifact
from alertiq.serving.quality import check_data_quality
from alertiq.serving.schema import (
    AlertFeatures,
    DataQualityFlags,
    ScoreResponse,
    SUPPORTED_SCHEMA_VERSIONS,
)

log = logging.getLogger(__name__)


class SchemaVersionMismatchError(ValueError):
    """Raised when the request schema_version does not match the artifact."""

    def __init__(self, requested: int, supported: set[int]) -> None:
        super().__init__(
            f"Schema version {requested} is not supported. "
            f"Supported versions: {sorted(supported)}. "
            "Update your client to send the current schema version."
        )
        self.requested = requested
        self.supported = supported


class InferenceScorer:
    """Stateless inference wrapper around a loaded ModelArtifact.

    Parameters
    ----------
    artifact:
        A loaded ``ModelArtifact`` (from ``load_artifact`` or
        ``ModelRegistry.get_champion()``).
    """

    def __init__(self, artifact: ModelArtifact) -> None:
        self._artifact = artifact
        self._n_features = len(artifact.feature_columns)
        log.info(
            "InferenceScorer initialised: model_version=%s schema_version=%d "
            "features=%d operating_mode=%s",
            artifact.model_version,
            artifact.schema_version,
            self._n_features,
            artifact.operating_mode,
        )

    @property
    def artifact(self) -> ModelArtifact:
        return self._artifact

    def score_single(
        self,
        schema_version: int,
        features: AlertFeatures,
    ) -> tuple[float, DataQualityFlags, float]:
        """Score a single alert.

        Parameters
        ----------
        schema_version:
            Schema version asserted by the client request.  Must match
            the artifact's schema_version.
        features:
            Validated feature values.

        Returns
        -------
        tuple[float, DataQualityFlags, float]
            ``(risk_score, quality_flags, latency_ms)``

        Raises
        ------
        SchemaVersionMismatchError
            If the client's schema_version is not supported or does not
            match the artifact's version.
        """
        self._validate_schema_version(schema_version)

        t0 = time.perf_counter()

        quality_flags = check_data_quality(features)
        if quality_flags.quality_warning:
            log.warning(
                "Data quality warning: zero_features=%s extreme_features=%s",
                quality_flags.zero_feature_names,
                quality_flags.extreme_feature_names,
            )

        X = self._build_feature_array(features)
        raw_scores = self._artifact.scorer.score(X)
        risk_score = float(raw_scores[0])
        # Clamp to [0, 1] — should already be in range but guards against
        # numerical edge cases from predict_proba.
        risk_score = max(0.0, min(1.0, risk_score))

        latency_ms = (time.perf_counter() - t0) * 1000.0
        return risk_score, quality_flags, latency_ms

    def score_batch(
        self,
        schema_version: int,
        features_list: list[AlertFeatures],
    ) -> tuple[np.ndarray, list[DataQualityFlags], float]:
        """Score a list of alerts as a single batch.

        All alerts must use the same schema_version (enforced upstream by
        BatchScoreRequest validation).

        Parameters
        ----------
        schema_version:
            Schema version asserted by the batch request.
        features_list:
            List of validated feature objects.

        Returns
        -------
        tuple[np.ndarray, list[DataQualityFlags], float]
            ``(risk_scores array, quality_flags list, latency_ms)``

        Raises
        ------
        SchemaVersionMismatchError
            If the client's schema_version is not supported.
        """
        self._validate_schema_version(schema_version)

        t0 = time.perf_counter()

        quality_flags_list = [check_data_quality(f) for f in features_list]

        rows = [f.to_array() for f in features_list]
        X = np.array(rows, dtype=np.float64)
        raw_scores = self._artifact.scorer.score(X)
        # Clamp to [0, 1]
        risk_scores = np.clip(raw_scores, 0.0, 1.0)

        latency_ms = (time.perf_counter() - t0) * 1000.0
        return risk_scores, quality_flags_list, latency_ms

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _validate_schema_version(self, schema_version: int) -> None:
        if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise SchemaVersionMismatchError(
                requested=schema_version,
                supported=set(SUPPORTED_SCHEMA_VERSIONS),
            )
        if schema_version != self._artifact.schema_version:
            raise SchemaVersionMismatchError(
                requested=schema_version,
                supported={self._artifact.schema_version},
            )

    def _build_feature_array(self, features: AlertFeatures) -> np.ndarray:
        """Build a (1, n_features) float64 array from validated features."""
        row = features.to_array()
        return np.array([row], dtype=np.float64)
