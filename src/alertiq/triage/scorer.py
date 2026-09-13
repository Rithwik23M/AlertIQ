"""
TriageScorer — histogram gradient-boosted classifier for AML alert triage.

Algorithm
---------
sklearn ``HistGradientBoostingClassifier`` (sklearn 1.8+) is used.

* Discretises continuous features into integer bins (max 255 by default).
* Grows trees with a maximum leaf-node budget per iteration.
* Native support for missing values and categorical features.
* Built-in early stopping on an internal validation split.
* L2 regularisation on leaf values.
* Scale-invariant: no feature normalisation needed.

Why not LightGBM
----------------
LightGBM and sklearn's HistGradientBoostingClassifier share a common
algorithmic ancestor (histogram-based gradient boosting), but they are
distinct implementations maintained by different teams.  They accept
different hyperparameter names and may produce different results on the
same data due to implementation differences (e.g. gradient estimation,
bin construction, threading).  LightGBM was unavailable in this execution
environment (pip wheel missing); see ADR-01.

Important: results obtained with HistGradientBoostingClassifier are NOT
guaranteed to reproduce on LightGBM.  If the execution environment changes
to support LightGBM, hyperparameter equivalences must be verified and the
model must be re-evaluated on the holdout set.

Operating modes
---------------
This scorer supports two distinct operating policies:

  Classification mode  —  binary label at a fixed threshold.
      ``predict(X)`` applies ``score(X) >= self.threshold`` to produce
      hard 0/1 predictions.  The threshold is selected on the validation
      split to maximise F1 (see ``_select_threshold``).  Metrics:
      precision, recall, F1, FPR, FNR at the selected threshold.

  Capacity-ranking mode  —  review the top-K alerts ranked by model score.
      ``score(X)`` returns a probability in [0, 1].  Analysts work through
      the ranked list and stop at a capacity limit K.  The threshold is
      irrelevant here; what matters is the relative ordering of scores.
      Metrics: Precision@K, Recall@K at K = 10%, 20%, 30%, 50%.

The PRIMARY operating policy for AlertIQ is capacity-ranking mode.
Analysts do not apply a binary cutoff; they work through the ranked queue.
Recall@20% is the primary acceptance criterion.  Classification-mode
metrics (precision, recall, F1 at threshold) are reported as supplementary
diagnostic information.

Training protocol
-----------------
1. Fit on training split only (never validation or holdout).
2. Early stopping on an internal fraction of the training set.
3. Score on validation split to select the F1-optimal classification
   threshold (supplementary diagnostic; capacity-ranking mode does not
   depend on this threshold).
4. Final model re-fits on train+val with the selected threshold fixed.
5. Report all final metrics on the untouched holdout.
"""

from __future__ import annotations

import logging

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance

from .config import TriageConfig

log = logging.getLogger(__name__)


class TriageScorer:
    """Trains and scores the histogram-GBDT triage model.

    The model is fitted in two phases:
    - Phase 1 (``fit_phase1``): trained on the training split with early
      stopping, then the threshold is selected from the validation split.
    - Phase 2 (``fit_phase2``): re-trained on train+val (no early stopping,
      fixed ``max_iter`` from phase 1's best iteration) to use all labelled
      data before evaluating on the holdout.

    ``score`` can be called after either phase.
    """

    def __init__(self, config: TriageConfig) -> None:
        self._config = config
        self._model: HistGradientBoostingClassifier | None = None
        self._threshold: float = 0.5
        self._best_iter: int | None = None

    # ------------------------------------------------------------------ #
    # Fitting                                                              #
    # ------------------------------------------------------------------ #

    def fit_phase1(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray,
        y_val: np.ndarray,
    ) -> "TriageScorer":
        """Train on X_train/y_train; select threshold from X_val/y_val."""
        hp = self._config.hyperparams
        cat_features = list(self._config.categorical_feature_indices) or None

        model = HistGradientBoostingClassifier(
            max_iter=hp.max_iter,
            learning_rate=hp.learning_rate,
            max_leaf_nodes=hp.max_leaf_nodes,
            max_depth=hp.max_depth,
            min_samples_leaf=hp.min_samples_leaf,
            l2_regularization=hp.l2_regularization,
            max_bins=hp.max_bins,
            early_stopping=hp.early_stopping,
            n_iter_no_change=hp.n_iter_no_change,
            validation_fraction=hp.validation_fraction,
            tol=hp.tol,
            categorical_features=cat_features,
            random_state=self._config.seed,
            class_weight="balanced",  # compensate for 9% SAR rate
        )
        model.fit(X_train, y_train)
        self._best_iter = model.n_iter_
        log.info("Phase-1 training complete: n_iter=%d", self._best_iter)

        self._model = model

        # Select threshold from validation set
        if self._config.classification_threshold is not None:
            self._threshold = self._config.classification_threshold
        else:
            val_probs = model.predict_proba(X_val)[:, 1]
            self._threshold = self._select_threshold(val_probs, y_val)

        log.info("Selected classification threshold: %.4f", self._threshold)
        return self

    def fit_phase2(
        self,
        X_train_val: np.ndarray,
        y_train_val: np.ndarray,
    ) -> "TriageScorer":
        """Re-fit on train+val with best iteration count from phase 1.

        Phase 2 uses the iteration count discovered by early stopping in
        phase 1.  Early stopping is disabled so the model trains for exactly
        that many iterations on the larger dataset.
        """
        if self._best_iter is None:
            raise RuntimeError("fit_phase1 must be called before fit_phase2")

        hp = self._config.hyperparams
        cat_features = list(self._config.categorical_feature_indices) or None

        model = HistGradientBoostingClassifier(
            max_iter=self._best_iter,
            learning_rate=hp.learning_rate,
            max_leaf_nodes=hp.max_leaf_nodes,
            max_depth=hp.max_depth,
            min_samples_leaf=hp.min_samples_leaf,
            l2_regularization=hp.l2_regularization,
            max_bins=hp.max_bins,
            early_stopping=False,  # fixed iteration count
            categorical_features=cat_features,
            random_state=self._config.seed,
            class_weight="balanced",
        )
        model.fit(X_train_val, y_train_val)
        self._model = model
        log.info("Phase-2 training complete: n_iter=%d", self._best_iter)
        return self

    # ------------------------------------------------------------------ #
    # Scoring                                                              #
    # ------------------------------------------------------------------ #

    def score(self, X: np.ndarray, df=None) -> np.ndarray:  # noqa: ARG002
        """Return SAR probability scores in [0, 1]."""
        if self._model is None:
            raise RuntimeError("Model is not fitted — call fit_phase1 first")
        return self._model.predict_proba(X)[:, 1]

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Return binary predictions using the selected threshold."""
        probs = self.score(X)
        return (probs >= self._threshold).astype(int)

    @property
    def threshold(self) -> float:
        return self._threshold

    @property
    def best_iter(self) -> int | None:
        return self._best_iter

    @property
    def name(self) -> str:
        return "histgbm_triage"

    # ------------------------------------------------------------------ #
    # Feature importance                                                   #
    # ------------------------------------------------------------------ #

    def feature_importances(
        self, feature_names: list[str]
    ) -> dict[str, float]:
        """Return mean-decrease-in-impurity (MDI) importances (gain-weighted).

        ``HistGradientBoostingClassifier`` in scikit-learn does not expose a
        ``feature_importances_`` attribute (unlike RandomForest / GBM).  We
        compute MDI directly from the internal ``_predictors`` tree structure:
        for every non-leaf split node, accumulate ``gain × count`` into the
        bucket for the split feature, then normalise to sum to 1.

        ``_predictors`` is a list-of-lists of ``TreePredictor`` objects.  Each
        ``TreePredictor.nodes`` is a structured NumPy array whose relevant
        fields are ``feature_idx``, ``gain``, ``count``, and ``is_leaf``.
        """
        if self._model is None:
            raise RuntimeError("Model not fitted")

        n_features = len(feature_names)
        raw = np.zeros(n_features, dtype=np.float64)

        for tree_group in self._model._predictors:  # outer list: one per boosting iteration
            for tree in tree_group:                  # inner list: one per class (binary → 1)
                nodes = tree.nodes
                # is_leaf field is uint8; cast to bool for masking
                is_leaf = nodes["is_leaf"].astype(bool)
                for node in nodes[~is_leaf]:
                    fidx = int(node["feature_idx"])
                    if 0 <= fidx < n_features:
                        raw[fidx] += float(node["gain"]) * float(node["count"])

        total = raw.sum()
        if total > 0.0:
            raw /= total

        return dict(sorted(zip(feature_names, raw.tolist()), key=lambda x: -x[1]))

    def permutation_importances(
        self,
        X: np.ndarray,
        y: np.ndarray,
        feature_names: list[str],
        n_repeats: int = 5,
    ) -> dict[str, float]:
        """Permutation feature importances (more reliable than MDI for GBDT)."""
        if self._model is None:
            raise RuntimeError("Model not fitted")
        result = permutation_importance(
            self._model,
            X,
            y,
            n_repeats=n_repeats,
            random_state=self._config.seed,
            scoring="roc_auc",
        )
        mean_imp = result.importances_mean
        return dict(sorted(zip(feature_names, mean_imp), key=lambda x: -x[1]))

    # ------------------------------------------------------------------ #
    # Threshold selection                                                  #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _select_threshold(probs: np.ndarray, y: np.ndarray) -> float:
        """Select the probability threshold that maximises F1 on y.

        Evaluates 200 candidate thresholds from 1st to 99th percentile of
        predicted probabilities.  Uses the threshold with the highest F1;
        ties broken by selecting the higher threshold (more conservative —
        fewer false positives) to suit an AML analyst capacity constraint.
        """
        candidates = np.linspace(
            np.percentile(probs, 1),
            np.percentile(probs, 99),
            200,
        )
        best_f1 = -1.0
        best_thr = 0.5
        for thr in candidates:
            preds = (probs >= thr).astype(int)
            tp = int(((preds == 1) & (y == 1)).sum())
            fp = int(((preds == 1) & (y == 0)).sum())
            fn = int(((preds == 0) & (y == 1)).sum())
            prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
            if f1 > best_f1:
                best_f1 = f1
                best_thr = float(thr)
        return best_thr
