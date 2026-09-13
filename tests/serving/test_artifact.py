"""
Tests for alertiq.serving.artifact — model serialisation.

Coverage
--------
- save_artifact creates .joblib + .sha256 files
- load_artifact returns a ModelArtifact with correct metadata
- save/load roundtrip: scores are identical before and after
- Checksum mismatch detection (tampered file)
- Missing checksum file raises FileNotFoundError
- Missing artifact file raises FileNotFoundError
- Unfitted scorer raises RuntimeError on save
- Empty model_version raises ValueError
- Missing payload key raises KeyError
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest

from alertiq.serving.artifact import (
    CURRENT_SCHEMA_VERSION,
    ModelArtifact,
    _sha256_file,
    load_artifact,
    save_artifact,
)
from alertiq.triage.config import TriageConfig
from alertiq.triage.scorer import TriageScorer


class TestSaveArtifact:
    """Tests for save_artifact()."""

    def test_creates_joblib_file(self, tmp_artifact_path: Path) -> None:
        assert tmp_artifact_path.exists()

    def test_creates_checksum_file(self, tmp_artifact_path: Path) -> None:
        checksum_path = tmp_artifact_path.with_suffix(".joblib.sha256")
        assert checksum_path.exists()

    def test_checksum_is_sha256_hex(self, tmp_artifact_path: Path) -> None:
        checksum_path = tmp_artifact_path.with_suffix(".joblib.sha256")
        text = checksum_path.read_text(encoding="utf-8").strip()
        assert len(text) == 64
        int(text, 16)  # must be valid hex

    def test_checksum_matches_file(self, tmp_artifact_path: Path) -> None:
        checksum_path = tmp_artifact_path.with_suffix(".joblib.sha256")
        expected = checksum_path.read_text(encoding="utf-8").strip()
        actual = _sha256_file(tmp_artifact_path)
        assert actual == expected

    def test_creates_parent_dirs(
        self, tmp_path: Path, fitted_scorer_phase2, _config: TriageConfig
    ) -> None:
        deep_path = tmp_path / "a" / "b" / "c" / "model.joblib"
        save_artifact(
            scorer=fitted_scorer_phase2,
            config=_config,
            model_version="1.0.0",
            path=deep_path,
            training_rows=100,
        )
        assert deep_path.exists()

    def test_raises_on_empty_version(
        self, tmp_path: Path, fitted_scorer_phase2, _config: TriageConfig
    ) -> None:
        with pytest.raises(ValueError, match="model_version"):
            save_artifact(
                scorer=fitted_scorer_phase2,
                config=_config,
                model_version="",
                path=tmp_path / "model.joblib",
                training_rows=100,
            )

    def test_raises_on_unfitted_scorer(
        self, tmp_path: Path, _config: TriageConfig
    ) -> None:
        unfitted = TriageScorer(_config)
        with pytest.raises(RuntimeError, match="fitted"):
            save_artifact(
                scorer=unfitted,
                config=_config,
                model_version="1.0.0",
                path=tmp_path / "model.joblib",
                training_rows=100,
            )


class TestLoadArtifact:
    """Tests for load_artifact()."""

    def test_returns_model_artifact(self, tmp_artifact_path: Path) -> None:
        artifact = load_artifact(tmp_artifact_path)
        assert isinstance(artifact, ModelArtifact)

    def test_model_version_matches(self, tmp_artifact_path: Path) -> None:
        artifact = load_artifact(tmp_artifact_path)
        assert artifact.model_version == "0.0.1-test"

    def test_feature_columns_are_24(self, tmp_artifact_path: Path) -> None:
        artifact = load_artifact(tmp_artifact_path)
        assert len(artifact.feature_columns) == 24

    def test_feature_columns_match_config(
        self, tmp_artifact_path: Path, _config: TriageConfig
    ) -> None:
        artifact = load_artifact(tmp_artifact_path)
        assert artifact.feature_columns == _config.feature_columns

    def test_schema_version_is_current(self, tmp_artifact_path: Path) -> None:
        artifact = load_artifact(tmp_artifact_path)
        assert artifact.schema_version == CURRENT_SCHEMA_VERSION

    def test_operating_mode_is_capacity_ranking(self, tmp_artifact_path: Path) -> None:
        artifact = load_artifact(tmp_artifact_path)
        assert artifact.operating_mode == "capacity_ranking"

    def test_artifact_path_is_set(self, tmp_artifact_path: Path) -> None:
        artifact = load_artifact(tmp_artifact_path)
        assert artifact.artifact_path == tmp_artifact_path

    def test_checksum_is_set(self, tmp_artifact_path: Path) -> None:
        artifact = load_artifact(tmp_artifact_path)
        assert len(artifact.checksum_sha256) == 64

    def test_raises_on_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_artifact(tmp_path / "nonexistent.joblib")

    def test_raises_on_missing_checksum_file(
        self, tmp_artifact_path: Path
    ) -> None:
        checksum_path = tmp_artifact_path.with_suffix(".joblib.sha256")
        checksum_path.unlink()
        with pytest.raises(FileNotFoundError, match="sha256"):
            load_artifact(tmp_artifact_path)

    def test_raises_on_checksum_mismatch(self, tmp_artifact_path: Path) -> None:
        """Tamper with the .joblib file — load_artifact must detect it."""
        with open(tmp_artifact_path, "ab") as f:
            f.write(b"\x00\xff")  # corrupt the file
        with pytest.raises(ValueError, match="checksum mismatch"):
            load_artifact(tmp_artifact_path)

    def test_raises_on_missing_payload_key(
        self, tmp_path: Path, _config: TriageConfig, fitted_scorer_phase2
    ) -> None:
        """Save a corrupted payload (missing 'notes') and expect KeyError."""
        import joblib
        path = tmp_path / "bad.joblib"
        # Build a payload missing the 'notes' key.
        payload = {
            "scorer": fitted_scorer_phase2,
            "feature_columns": _config.feature_columns,
            "schema_version": 1,
            "model_version": "1.0.0",
            "trained_at": "2026-01-01T00:00:00Z",
            "training_rows": 100,
            "best_iter": 50,
            "threshold": 0.5,
            "operating_mode": "capacity_ranking",
            # 'notes' deliberately omitted
        }
        joblib.dump(payload, path, compress=3)
        # Write a valid checksum so the checksum check passes.
        checksum_path = path.with_suffix(".joblib.sha256")
        checksum_path.write_text(_sha256_file(path) + "\n")
        with pytest.raises(KeyError):
            load_artifact(path)


class TestRoundtrip:
    """Save then load: scores must be deterministic."""

    def test_scores_are_identical_before_and_after(
        self,
        tmp_artifact_path: Path,
        fitted_scorer_phase2,
    ) -> None:
        rng = np.random.default_rng(seed=99)
        X = rng.random((50, 24))
        scores_before = fitted_scorer_phase2.score(X)

        artifact = load_artifact(tmp_artifact_path)
        scores_after = artifact.scorer.score(X)

        np.testing.assert_allclose(scores_before, scores_after, rtol=1e-10)

    def test_scores_in_unit_interval(self, tmp_artifact_path: Path) -> None:
        rng = np.random.default_rng(seed=42)
        X = rng.random((100, 24))
        artifact = load_artifact(tmp_artifact_path)
        scores = artifact.scorer.score(X)
        assert (scores >= 0.0).all()
        assert (scores <= 1.0).all()
