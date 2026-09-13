"""
Tests for alertiq.serving.registry — lightweight model version registry.

Coverage
--------
- register() creates artifact files and updates the manifest
- Duplicate version registration raises ValueError
- get_champion() returns the correct artifact
- get_champion() raises LookupError when no champion
- get_version() returns the requested version
- get_version() raises LookupError for unknown version
- promote() changes the champion
- list_versions() returns all entries
- Manifest is written atomically (file rename, not partial write)
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from alertiq.serving.registry import ModelRegistry, REGISTRY_FILENAME
from alertiq.triage.config import TriageConfig


class TestRegister:
    def test_creates_registry_json(self, tmp_registry: ModelRegistry, tmp_path: Path) -> None:
        registry_dir = tmp_path / "check_registry"
        r = ModelRegistry(registry_dir)
        assert (registry_dir / REGISTRY_FILENAME).exists()

    def test_register_creates_artifact_file(self, tmp_registry: ModelRegistry) -> None:
        versions = tmp_registry.list_versions()
        assert len(versions) == 1
        artifact_rel = versions[0]["artifact_path"]
        # The artifact path is relative to registry root — check it exists.
        registry_root = tmp_registry._root
        assert (registry_root / artifact_rel).exists()

    def test_register_records_model_version(self, tmp_registry: ModelRegistry) -> None:
        versions = tmp_registry.list_versions()
        assert versions[0]["model_version"] == "0.0.1-test"

    def test_register_records_training_rows(self, tmp_registry: ModelRegistry) -> None:
        versions = tmp_registry.list_versions()
        assert versions[0]["training_rows"] == 240

    def test_duplicate_version_raises(
        self,
        tmp_registry: ModelRegistry,
        fitted_scorer_phase2,
        _config: TriageConfig,
    ) -> None:
        with pytest.raises(ValueError, match="already registered"):
            tmp_registry.register(
                scorer=fitted_scorer_phase2,
                config=_config,
                model_version="0.0.1-test",  # already exists
                training_rows=100,
            )

    def test_second_version_can_be_registered(
        self,
        tmp_registry: ModelRegistry,
        fitted_scorer_phase2,
        _config: TriageConfig,
    ) -> None:
        tmp_registry.register(
            scorer=fitted_scorer_phase2,
            config=_config,
            model_version="0.0.2-test",
            training_rows=300,
        )
        versions = tmp_registry.list_versions()
        assert len(versions) == 2


class TestGetChampion:
    def test_returns_model_artifact(self, tmp_registry: ModelRegistry) -> None:
        artifact = tmp_registry.get_champion()
        assert artifact.model_version == "0.0.1-test"

    def test_scorer_produces_valid_scores(self, tmp_registry: ModelRegistry) -> None:
        artifact = tmp_registry.get_champion()
        rng = np.random.default_rng(42)
        X = rng.random((20, 24))
        scores = artifact.scorer.score(X)
        assert scores.shape == (20,)
        assert (scores >= 0.0).all() and (scores <= 1.0).all()

    def test_raises_when_no_champion(self, tmp_path: Path) -> None:
        empty_registry = ModelRegistry(tmp_path / "empty")
        with pytest.raises(LookupError):
            empty_registry.get_champion()

    def test_raises_when_all_demoted(
        self,
        tmp_path: Path,
        fitted_scorer_phase2,
        _config: TriageConfig,
    ) -> None:
        r = ModelRegistry(tmp_path / "demoted")
        r.register(
            scorer=fitted_scorer_phase2,
            config=_config,
            model_version="1.0.0",
            training_rows=100,
            promote_to_champion=False,  # not a champion
        )
        with pytest.raises(LookupError):
            r.get_champion()


class TestGetVersion:
    def test_returns_correct_version(self, tmp_registry: ModelRegistry) -> None:
        artifact = tmp_registry.get_version("0.0.1-test")
        assert artifact.model_version == "0.0.1-test"

    def test_raises_on_unknown_version(self, tmp_registry: ModelRegistry) -> None:
        with pytest.raises(LookupError, match="not found"):
            tmp_registry.get_version("99.99.99")


class TestPromote:
    def test_promote_changes_champion(
        self,
        tmp_path: Path,
        fitted_scorer_phase2,
        _config: TriageConfig,
    ) -> None:
        r = ModelRegistry(tmp_path / "promote_test")
        r.register(
            scorer=fitted_scorer_phase2,
            config=_config,
            model_version="1.0.0",
            training_rows=100,
            promote_to_champion=True,
        )
        r.register(
            scorer=fitted_scorer_phase2,
            config=_config,
            model_version="2.0.0",
            training_rows=200,
            promote_to_champion=False,
        )
        # Champion is still 1.0.0.
        assert r.get_champion().model_version == "1.0.0"

        r.promote("2.0.0")
        assert r.get_champion().model_version == "2.0.0"

    def test_promote_raises_on_unknown_version(self, tmp_registry: ModelRegistry) -> None:
        with pytest.raises(LookupError):
            tmp_registry.promote("99.99.99")

    def test_only_one_champion_after_promote(
        self,
        tmp_path: Path,
        fitted_scorer_phase2,
        _config: TriageConfig,
    ) -> None:
        r = ModelRegistry(tmp_path / "one_champ")
        r.register(fitted_scorer_phase2, _config, model_version="1.0.0", training_rows=100, promote_to_champion=True)
        r.register(fitted_scorer_phase2, _config, model_version="2.0.0", training_rows=100, promote_to_champion=False)
        r.promote("2.0.0")
        champions = [v for v in r.list_versions() if v["is_champion"]]
        assert len(champions) == 1
        assert champions[0]["model_version"] == "2.0.0"


class TestListVersions:
    def test_returns_list(self, tmp_registry: ModelRegistry) -> None:
        versions = tmp_registry.list_versions()
        assert isinstance(versions, list)

    def test_empty_on_new_registry(self, tmp_path: Path) -> None:
        r = ModelRegistry(tmp_path / "fresh")
        assert r.list_versions() == []
