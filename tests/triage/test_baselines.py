"""Tests for RandomScorer and SeverityScorer baselines."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from alertiq.triage.baseline import RandomScorer, SeverityScorer
from alertiq.triage.config import TriageConfig


@pytest.fixture
def config():
    return TriageConfig()


def _make_df(n: int = 100, seed: int = 0) -> tuple[np.ndarray, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    severities = rng.choice(["critical", "high", "medium", "low"], size=n)
    df = pd.DataFrame({"severity": severities, "alert_id": [f"A{i}" for i in range(n)]})
    X = rng.standard_normal((n, 24))
    return X, df


class TestRandomScorer:
    def test_score_range_is_zero_to_one(self, config):
        X, df = _make_df()
        scorer = RandomScorer(config)
        scores = scorer.score(X, df)
        assert np.all(scores >= 0.0)
        assert np.all(scores <= 1.0)

    def test_score_length_matches_input(self, config):
        X, df = _make_df(77)
        scorer = RandomScorer(config)
        assert len(scorer.score(X, df)) == 77

    def test_same_seed_produces_same_scores(self):
        X, df = _make_df()
        s1 = RandomScorer(TriageConfig()).score(X, df)
        s2 = RandomScorer(TriageConfig()).score(X, df)
        np.testing.assert_array_equal(s1, s2)

    def test_different_seeds_produce_different_scores(self):
        X, df = _make_df(100)
        s1 = RandomScorer(TriageConfig(seed=1)).score(X, df)
        s2 = RandomScorer(TriageConfig(seed=2)).score(X, df)
        assert not np.allclose(s1, s2)

    def test_name_is_baseline_random(self, config):
        assert RandomScorer(config).name == "baseline_random"

    def test_scores_are_uniformly_distributed(self, config):
        """Kolmogorov-Smirnov test: random scores should look uniform."""
        from scipy.stats import kstest
        X, df = _make_df(5000, seed=7)
        scores = RandomScorer(config).score(X, df)
        stat, p_value = kstest(scores, "uniform")
        assert p_value > 0.01, f"Random scores not uniformly distributed (p={p_value:.4f})"


class TestSeverityScorer:
    def test_critical_scores_above_high(self, config):
        df = pd.DataFrame({
            "severity": ["critical", "high", "medium", "low"],
            "alert_id": ["A", "B", "C", "D"],
        })
        X = np.zeros((4, 24))
        scorer = SeverityScorer(config)
        scores = scorer.score(X, df)
        # Ignore tiny noise: critical > high > medium > low
        assert scores[0] > scores[1] > scores[2] > scores[3]

    def test_same_seed_produces_deterministic_scores(self):
        X, df = _make_df(50, seed=5)
        s1 = SeverityScorer(TriageConfig()).score(X, df)
        s2 = SeverityScorer(TriageConfig()).score(X, df)
        np.testing.assert_array_equal(s1, s2)

    def test_missing_severity_column_raises(self, config):
        X, df = _make_df()
        df_no_sev = df.drop(columns=["severity"])
        scorer = SeverityScorer(config)
        with pytest.raises(ValueError, match="severity"):
            scorer.score(X, df_no_sev)

    def test_unknown_severity_maps_to_zero(self, config):
        df = pd.DataFrame({
            "severity": ["unknown_tier"],
            "alert_id": ["X"],
        })
        X = np.zeros((1, 24))
        scorer = SeverityScorer(config)
        scores = scorer.score(X, df)
        # Should be close to 0 (mapped via fillna(0.0)), plus tiny noise
        assert scores[0] < 0.01

    def test_name_is_baseline_severity(self, config):
        assert SeverityScorer(config).name == "baseline_severity"

    def test_score_length_matches_input(self, config):
        X, df = _make_df(123)
        scorer = SeverityScorer(config)
        assert len(scorer.score(X, df)) == 123
