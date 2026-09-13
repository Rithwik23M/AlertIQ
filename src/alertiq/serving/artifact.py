"""
ModelArtifact — serialise and deserialise a trained TriageScorer.

Artifact format
---------------
A single joblib file (gzip-compressed) whose payload is a dict:

    {
        "scorer":          TriageScorer instance,
        "feature_columns": tuple[str, ...],   # ordered feature schema
        "schema_version":  int,               # schema revision (starts at 1)
        "model_version":   str,               # semver string e.g. "1.0.0"
        "trained_at":      str,               # ISO-8601 UTC timestamp
        "training_rows":   int,               # rows used in final fit
        "best_iter":       int,               # early-stopping iteration count
        "threshold":       float,             # selected classification threshold
                                              # (supplementary; not used for ranking)
        "operating_mode":  str,               # always "capacity_ranking"
        "notes":           str,               # free-text provenance notes
    }

The artifact dict is sha256-checksummed; the checksum is stored alongside
the artifact so load_artifact can detect corruption or tampering before
constructing the scorer.  The checksum covers the joblib bytes, not the
dict contents, so it catches filesystem / transfer corruption.

Checksum file naming
--------------------
Artifact path  : models/v1.0.0/model.joblib
Checksum path  : models/v1.0.0/model.joblib.sha256

Usage
-----
    # Save
    save_artifact(scorer, config, model_version="1.0.0",
                  path=Path("models/v1.0.0/model.joblib"),
                  training_rows=42000)

    # Load (verifies checksum automatically)
    artifact = load_artifact(Path("models/v1.0.0/model.joblib"))
    scores = artifact.scorer.score(X)
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib

from alertiq.triage.config import TriageConfig
from alertiq.triage.scorer import TriageScorer

log = logging.getLogger(__name__)

# Current schema version.  Increment when the feature contract changes.
CURRENT_SCHEMA_VERSION: int = 1


@dataclass(frozen=True)
class ModelArtifact:
    """Loaded model artifact with metadata.

    Attributes
    ----------
    scorer:
        Fitted TriageScorer ready to call ``.score(X)``.
    feature_columns:
        Ordered tuple of feature names; matches the 24-column contract from
        ``TriageConfig.feature_columns`` at training time.
    schema_version:
        Integer schema revision.  Serving layer uses this to detect schema
        mismatches between the artifact and incoming requests.
    model_version:
        Semver string identifying this model release.
    trained_at:
        ISO-8601 UTC timestamp when the artifact was created.
    training_rows:
        Number of rows used to fit the final model.
    best_iter:
        Early-stopping iteration count from phase-1 training.
    threshold:
        F1-optimal classification threshold (supplementary; not used for
        capacity-ranking mode).
    operating_mode:
        Always ``"capacity_ranking"`` — confirms the API policy.
    notes:
        Free-text provenance notes.
    artifact_path:
        Filesystem path to the .joblib file (set by ``load_artifact``).
    checksum_sha256:
        SHA-256 hex digest of the .joblib file (verified on load).
    """

    scorer: TriageScorer
    feature_columns: tuple[str, ...]
    schema_version: int
    model_version: str
    trained_at: str
    training_rows: int
    best_iter: int
    threshold: float
    operating_mode: str
    notes: str
    artifact_path: Path
    checksum_sha256: str


# ------------------------------------------------------------------ #
# Save                                                                 #
# ------------------------------------------------------------------ #

def save_artifact(
    scorer: TriageScorer,
    config: TriageConfig,
    *,
    model_version: str,
    path: Path,
    training_rows: int,
    notes: str = "",
    schema_version: int = CURRENT_SCHEMA_VERSION,
) -> Path:
    """Serialise a fitted TriageScorer to *path* and write a checksum file.

    Parameters
    ----------
    scorer:
        A fitted TriageScorer (phase 2 preferred; phase 1 is accepted).
    config:
        The TriageConfig used during training (supplies the feature schema).
    model_version:
        Semver string for this release, e.g. ``"1.0.0"``.
    path:
        Destination ``.joblib`` file path.  Parent directories are created
        automatically.
    training_rows:
        Number of rows in the dataset used for the final fit.
    notes:
        Optional free-text provenance string (training script, commit hash…).
    schema_version:
        Schema revision (default: ``CURRENT_SCHEMA_VERSION``).

    Returns
    -------
    Path
        The path to the saved artifact file.

    Raises
    ------
    RuntimeError
        If the scorer has not been fitted (no internal model).
    ValueError
        If model_version is empty.
    """
    if not model_version.strip():
        raise ValueError("model_version must not be empty")
    if scorer._model is None:  # noqa: SLF001
        raise RuntimeError("TriageScorer must be fitted before serialisation")

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    payload: dict[str, Any] = {
        "scorer": scorer,
        "feature_columns": config.feature_columns,
        "schema_version": schema_version,
        "model_version": model_version,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "training_rows": training_rows,
        "best_iter": scorer.best_iter or 0,
        "threshold": scorer.threshold,
        "operating_mode": "capacity_ranking",
        "notes": notes,
    }

    joblib.dump(payload, path, compress=3)
    log.info("Artifact saved: path=%s version=%s", path, model_version)

    checksum = _sha256_file(path)
    checksum_path = path.with_suffix(path.suffix + ".sha256")
    checksum_path.write_text(checksum + "\n", encoding="utf-8")
    log.info("Checksum written: %s  sha256=%s", checksum_path, checksum[:16] + "…")

    return path


# ------------------------------------------------------------------ #
# Load                                                                 #
# ------------------------------------------------------------------ #

def load_artifact(path: Path) -> ModelArtifact:
    """Load a serialised ModelArtifact, verifying the SHA-256 checksum.

    Parameters
    ----------
    path:
        Path to the ``.joblib`` file.  The corresponding ``.sha256`` file
        must exist alongside it.

    Returns
    -------
    ModelArtifact

    Raises
    ------
    FileNotFoundError
        If the artifact or checksum file is missing.
    ValueError
        If the checksum does not match (corruption / tampering).
    KeyError
        If the artifact payload is missing a required key.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Artifact not found: {path}")

    checksum_path = path.with_suffix(path.suffix + ".sha256")
    if not checksum_path.exists():
        raise FileNotFoundError(f"Checksum file not found: {checksum_path}")

    expected = checksum_path.read_text(encoding="utf-8").strip()
    actual = _sha256_file(path)
    if actual != expected:
        raise ValueError(
            f"Artifact checksum mismatch — expected {expected[:16]}… "
            f"but computed {actual[:16]}… — file may be corrupted or tampered."
        )

    payload: dict[str, Any] = joblib.load(path)

    required_keys = {
        "scorer", "feature_columns", "schema_version", "model_version",
        "trained_at", "training_rows", "best_iter", "threshold",
        "operating_mode", "notes",
    }
    missing = required_keys - payload.keys()
    if missing:
        raise KeyError(f"Artifact payload missing required keys: {missing}")

    log.info(
        "Artifact loaded: version=%s schema_version=%d trained_at=%s rows=%d",
        payload["model_version"],
        payload["schema_version"],
        payload["trained_at"],
        payload["training_rows"],
    )

    return ModelArtifact(
        scorer=payload["scorer"],
        feature_columns=tuple(payload["feature_columns"]),
        schema_version=int(payload["schema_version"]),
        model_version=str(payload["model_version"]),
        trained_at=str(payload["trained_at"]),
        training_rows=int(payload["training_rows"]),
        best_iter=int(payload["best_iter"]),
        threshold=float(payload["threshold"]),
        operating_mode=str(payload["operating_mode"]),
        notes=str(payload["notes"]),
        artifact_path=path,
        checksum_sha256=actual,
    )


# ------------------------------------------------------------------ #
# Internal utilities                                                   #
# ------------------------------------------------------------------ #

def _sha256_file(path: Path) -> str:
    """Return the SHA-256 hex digest of *path*."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
