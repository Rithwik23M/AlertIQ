"""
Shared fixtures for alertiq.serving tests.

Fixtures
--------
minimal_features_dict
    A valid feature dict for schema_version=1 with all 24 features present
    and within valid ranges.  Use this as the baseline for positive tests.

fitted_scorer / fitted_scorer_phase2
    A TriageScorer fitted on a small synthetic dataset.  Phase-2 scorer is
    the one that would be serialised to a production artifact.

tmp_artifact_path
    A temporary directory with a saved ModelArtifact (.joblib + .sha256).

tmp_registry
    A temporary ModelRegistry populated with one registered (champion) version.

test_client
    A Starlette TestClient wired to the alertiq.serving.app application,
    with the module-level _scorer and _audit singletons pre-loaded.
"""

from __future__ import annotations

import importlib
import os
from pathlib import Path

import numpy as np
import pytest

from alertiq.triage.config import TriageConfig
from alertiq.triage.scorer import TriageScorer


# ------------------------------------------------------------------ #
# Synthetic dataset helpers                                            #
# ------------------------------------------------------------------ #

_N_FEATURES = 24
_RNG = np.random.default_rng(seed=0)


def _make_X(n_rows: int = 200) -> np.ndarray:
    """Synthetic feature matrix: uniform noise in [0, 1] for all 24 features."""
    return _RNG.random((n_rows, _N_FEATURES))


def _make_y(n_rows: int = 200, sar_rate: float = 0.09) -> np.ndarray:
    """Binary label with ~9% SAR rate (matches AlertIQ simulator)."""
    return (_RNG.random(n_rows) < sar_rate).astype(int)


# ------------------------------------------------------------------ #
# Feature dict fixture                                                 #
# ------------------------------------------------------------------ #

@pytest.fixture()
def minimal_features_dict() -> dict:
    """Valid feature dict for schema_version=1."""
    return {
        "f01_vol_7d_log": 8.5,
        "f02_vol_30d_log": 10.2,
        "f03_vol_ratio_7_30": 0.85,
        "f04_max_txn_log": 7.1,
        "f05_vol_vs_revenue": 1.2,
        "f06_txn_count_7d": 12,
        "f07_txn_count_30d": 45,
        "f08_velocity_ratio": 1.1,
        "f09_recency_gap_days": 3.0,
        "f10_account_age_days": 720.0,
        "f11_cash_fraction_30d": 0.15,
        "f12_structuring_count_30d": 0,
        "f13_round_amount_count_30d": 3,
        "f14_digital_channel_fraction": 0.8,
        "f15_night_fraction_30d": 0.1,
        "f16_intl_fraction_30d": 0.05,
        "f17_distinct_jurisdictions_30d": 2,
        "f18_very_high_jur_flag": 0,
        "f19_shell_counterparty_fraction": 0.0,
        "f20_pep_flag": 0,
        "f21_adverse_media_flag": 0,
        "f22_high_risk_industry": 0,
        "f23_prior_alerts_90d": 1,
        "f24_account_jurisdiction_score": 0.3,
    }


# ------------------------------------------------------------------ #
# Fitted scorer fixtures                                               #
# ------------------------------------------------------------------ #

@pytest.fixture(scope="session")
def _config() -> TriageConfig:
    return TriageConfig()


@pytest.fixture(scope="session")
def fitted_scorer(_config: TriageConfig) -> TriageScorer:
    """TriageScorer fitted on a small synthetic dataset (phase 1 only)."""
    n = 300
    X = _make_X(n)
    y = _make_y(n)
    split = int(n * 0.7)
    scorer = TriageScorer(_config)
    scorer.fit_phase1(X[:split], y[:split], X[split:], y[split:])
    return scorer


@pytest.fixture(scope="session")
def fitted_scorer_phase2(_config: TriageConfig, fitted_scorer: TriageScorer) -> TriageScorer:
    """TriageScorer re-fitted on train+val (phase 2) — this is the production artifact."""
    n = 300
    X = _make_X(n)
    y = _make_y(n)
    val_end = int(n * 0.8)
    phase2 = TriageScorer(_config)
    phase2.fit_phase1(X[:int(n * 0.6)], y[:int(n * 0.6)], X[int(n * 0.6):val_end], y[int(n * 0.6):val_end])
    phase2.fit_phase2(X[:val_end], y[:val_end])
    return phase2


# ------------------------------------------------------------------ #
# Artifact fixtures                                                    #
# ------------------------------------------------------------------ #

@pytest.fixture()
def tmp_artifact_path(tmp_path: Path, fitted_scorer_phase2: TriageScorer, _config: TriageConfig) -> Path:
    """Save a ModelArtifact to tmp_path and return the .joblib path."""
    from alertiq.serving.artifact import save_artifact
    artifact_path = tmp_path / "model.joblib"
    save_artifact(
        scorer=fitted_scorer_phase2,
        config=_config,
        model_version="0.0.1-test",
        path=artifact_path,
        training_rows=240,
        notes="pytest fixture artifact",
    )
    return artifact_path


@pytest.fixture()
def tmp_registry(tmp_path: Path, fitted_scorer_phase2: TriageScorer, _config: TriageConfig):
    """A ModelRegistry with one registered champion version."""
    from alertiq.serving.registry import ModelRegistry
    registry = ModelRegistry(tmp_path / "registry")
    registry.register(
        scorer=fitted_scorer_phase2,
        config=_config,
        model_version="0.0.1-test",
        training_rows=240,
        notes="pytest fixture",
        promote_to_champion=True,
    )
    return registry


# ------------------------------------------------------------------ #
# Test client fixture                                                  #
# ------------------------------------------------------------------ #

@pytest.fixture()
def test_client(tmp_artifact_path: Path, fitted_scorer_phase2: TriageScorer, _config: TriageConfig):
    """Starlette TestClient with the serving app pre-loaded with a scorer.

    We patch the module-level _scorer and _audit singletons directly so
    tests do not depend on the lifespan event (which loads from disk /
    registry) or environment variables.
    """
    from starlette.testclient import TestClient
    import alertiq.serving.app as app_module
    from alertiq.serving.artifact import load_artifact
    from alertiq.serving.audit import AuditLogger
    from alertiq.serving.scorer import InferenceScorer

    artifact = load_artifact(tmp_artifact_path)
    scorer = InferenceScorer(artifact)
    audit = AuditLogger()  # logs to Python logging (no ALERTIQ_AUDIT_LOG_PATH set)

    # Patch singletons.
    old_scorer = app_module._scorer
    old_audit = app_module._audit
    app_module._scorer = scorer
    app_module._audit = audit

    with TestClient(app_module.app, raise_server_exceptions=True) as client:
        yield client

    # Restore (important for test isolation).
    app_module._scorer = old_scorer
    app_module._audit = old_audit
