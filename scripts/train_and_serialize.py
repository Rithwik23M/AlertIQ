"""
train_and_serialize.py — train the final AlertIQ triage model and register
it in the local model registry.

Usage
-----
    python scripts/train_and_serialize.py [--version VERSION] [--promote]
                                          [--registry-path PATH]
                                          [--alerts-csv PATH]
                                          [--notes TEXT]

Arguments
---------
--version VERSION
    Semver model version string, e.g. "1.0.0".  Required.

--promote
    Promote this version to champion after registration.  The current
    champion (if any) is demoted.  Use this flag when you are satisfied
    with validation metrics and want the API to start serving this model.

--registry-path PATH
    Path to the local model registry directory.  Default: models/

--alerts-csv PATH
    Path to the alert simulation CSV file.  Default: data/simulation/alerts.csv

--notes TEXT
    Free-text provenance notes stored in the artifact (e.g. git commit
    hash, experiment ID).

Training protocol (reproduces Milestone 3 two-phase fit)
---------------------------------------------------------
Phase 1: fit on train split with early stopping.
         Threshold selected on validation split to maximise F1.
Phase 2: re-fit on train+val with fixed iteration count from phase 1.
         No early stopping.  Threshold carried over from phase 1.

The serialised artifact contains the phase-2 model, which is the model
the API serves.

Important constraints
---------------------
- This script does NOT retrain at API startup.
- This script does NOT retrain during scoring.
- Client-controlled model paths are NOT accepted by the API.
- Training uses the full train+val split (60% + 20% = 80% of data).
  The holdout (20%) is reserved for evaluation and is never used here.

Exit codes
----------
0 — success
1 — data or configuration error
2 — training error
3 — registry error
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Ensure the package root is on the path when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from alertiq.triage.config import TriageConfig
from alertiq.triage.scorer import TriageScorer
from alertiq.serving.registry import ModelRegistry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("train_and_serialize")


# ------------------------------------------------------------------ #
# Data loading                                                         #
# ------------------------------------------------------------------ #

def load_and_split(
    alerts_csv: str,
    config: TriageConfig,
) -> tuple[
    np.ndarray, np.ndarray,   # X_train, y_train
    np.ndarray, np.ndarray,   # X_val,   y_val
    np.ndarray, np.ndarray,   # X_train_val, y_train_val  (for phase 2)
    int,                       # total rows (for provenance)
]:
    """Load alerts.csv and produce temporal train / val splits.

    Returns X/y arrays for phase-1 (train, val) and phase-2 (train+val)
    training.  The holdout split is computed and discarded — this script
    trains the FINAL model and does not evaluate on holdout.

    The holdout set evaluation is the responsibility of the evaluation
    scripts (run_triage_experiment.py / run_robustness_experiment.py).
    """
    log.info("Loading alerts from %s", alerts_csv)
    df = pd.read_csv(alerts_csv)
    log.info("Loaded %d rows, %d columns", len(df), len(df.columns))

    if "triggered_date" not in df.columns:
        log.error("alerts.csv must contain a 'triggered_date' column for temporal splitting")
        sys.exit(1)

    df = df.sort_values("triggered_date").reset_index(drop=True)
    n = len(df)

    train_end = int(n * config.split.train_frac)
    val_end = int(n * (config.split.train_frac + config.split.val_frac))

    feature_cols = list(config.feature_columns)
    label_col = "true_sar"

    if label_col not in df.columns:
        log.error("alerts.csv must contain a 'true_sar' column (binary label)")
        sys.exit(1)

    missing_features = [f for f in feature_cols if f not in df.columns]
    if missing_features:
        log.error("Missing feature columns in alerts.csv: %s", missing_features)
        sys.exit(1)

    X_train = df.iloc[:train_end][feature_cols].to_numpy(dtype=np.float64)
    y_train = df.iloc[:train_end][label_col].to_numpy(dtype=int)

    X_val = df.iloc[train_end:val_end][feature_cols].to_numpy(dtype=np.float64)
    y_val = df.iloc[train_end:val_end][label_col].to_numpy(dtype=int)

    X_train_val = df.iloc[:val_end][feature_cols].to_numpy(dtype=np.float64)
    y_train_val = df.iloc[:val_end][label_col].to_numpy(dtype=int)

    log.info(
        "Split: train=%d  val=%d  holdout=%d  train+val=%d",
        len(y_train), len(y_val), n - val_end, len(y_train_val),
    )
    log.info(
        "SAR rate: train=%.3f  val=%.3f  train+val=%.3f",
        y_train.mean(), y_val.mean(), y_train_val.mean(),
    )

    return X_train, y_train, X_val, y_val, X_train_val, y_train_val, n


# ------------------------------------------------------------------ #
# Training                                                             #
# ------------------------------------------------------------------ #

def train_model(
    config: TriageConfig,
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_val: np.ndarray,
    y_val: np.ndarray,
    X_train_val: np.ndarray,
    y_train_val: np.ndarray,
) -> TriageScorer:
    """Execute the two-phase training protocol."""
    scorer = TriageScorer(config)

    log.info("Phase 1: training on train split with early stopping…")
    scorer.fit_phase1(X_train, y_train, X_val, y_val)
    log.info(
        "Phase 1 complete: best_iter=%d  threshold=%.4f",
        scorer.best_iter,
        scorer.threshold,
    )

    log.info("Phase 2: re-training on train+val with best_iter=%d…", scorer.best_iter)
    scorer.fit_phase2(X_train_val, y_train_val)
    log.info("Phase 2 complete")

    return scorer


# ------------------------------------------------------------------ #
# Validation metrics (lightweight pre-serialisation check)            #
# ------------------------------------------------------------------ #

def quick_val_metrics(
    scorer: TriageScorer,
    X_val: np.ndarray,
    y_val: np.ndarray,
) -> None:
    """Log Recall@20% and AUC-ROC on the validation split as a sanity check.

    These metrics are informational only — the definitive evaluation uses
    the holdout split in the robustness experiment.  We do not use these
    numbers to gate serialisation because the phase-2 model was fitted on
    train+val, which includes the validation split, making in-sample
    validation metrics unreliable.

    This check is purely to catch gross failures (model that scores
    everything ≈ 0, training data error, etc.).
    """
    from sklearn.metrics import roc_auc_score
    import warnings

    probs = scorer.score(X_val)
    try:
        auc = roc_auc_score(y_val, probs)
    except ValueError:
        auc = float("nan")
        warnings.warn("AUC-ROC could not be computed — check label distribution")

    # Recall@20%: sort by score descending, take top 20%
    k = max(1, int(len(y_val) * 0.20))
    sorted_idx = np.argsort(probs)[::-1]
    top_k_labels = y_val[sorted_idx[:k]]
    total_positives = y_val.sum()
    recall_at_20 = (top_k_labels.sum() / total_positives) if total_positives > 0 else 0.0

    log.info(
        "Validation sanity check (phase-2 model on val split — in-sample): "
        "AUC-ROC=%.3f  Recall@20%%=%.3f",
        auc,
        recall_at_20,
    )

    # Soft warning if metrics look implausible; do not exit.
    if auc < 0.60:
        log.warning(
            "AUC-ROC=%.3f is below 0.60 — check training data and features.",
            auc,
        )
    if recall_at_20 < 0.50:
        log.warning(
            "Recall@20%%=%.3f is unusually low for the training distribution. "
            "Inspect training data before promoting this model.",
            recall_at_20,
        )


# ------------------------------------------------------------------ #
# CLI                                                                  #
# ------------------------------------------------------------------ #

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train and serialise the AlertIQ triage model.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--version",
        required=True,
        help="Semver model version string, e.g. 1.0.0",
    )
    parser.add_argument(
        "--promote",
        action="store_true",
        default=False,
        help="Promote this version to champion after registration",
    )
    parser.add_argument(
        "--registry-path",
        default="models",
        help="Path to the local model registry directory (default: models/)",
    )
    parser.add_argument(
        "--alerts-csv",
        default="data/simulation/alerts.csv",
        help="Path to the alert simulation CSV (default: data/simulation/alerts.csv)",
    )
    parser.add_argument(
        "--notes",
        default="",
        help="Free-text provenance notes (e.g. git commit hash)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = TriageConfig(alerts_csv=args.alerts_csv)

    log.info(
        "Training run: version=%s  promote=%s  registry=%s  csv=%s",
        args.version,
        args.promote,
        args.registry_path,
        args.alerts_csv,
    )

    # 1. Load and split data
    try:
        (
            X_train, y_train,
            X_val, y_val,
            X_train_val, y_train_val,
            total_rows,
        ) = load_and_split(args.alerts_csv, config)
    except SystemExit:
        raise
    except Exception as exc:
        log.error("Data loading failed: %s", exc)
        sys.exit(1)

    # 2. Train
    try:
        scorer = train_model(
            config, X_train, y_train, X_val, y_val, X_train_val, y_train_val
        )
    except Exception as exc:
        log.error("Training failed: %s", exc)
        sys.exit(2)

    # 3. Quick validation sanity check
    quick_val_metrics(scorer, X_val, y_val)

    # 4. Register
    try:
        registry = ModelRegistry(Path(args.registry_path))
        artifact_path = registry.register(
            scorer=scorer,
            config=config,
            model_version=args.version,
            training_rows=len(y_train_val),
            notes=args.notes or f"Trained on {len(y_train_val)} rows (train+val)",
            promote_to_champion=args.promote,
        )
        log.info("Registered: %s", artifact_path)
        if args.promote:
            log.info("Promoted to champion: version=%s", args.version)
        else:
            log.info(
                "NOT promoted to champion. "
                "Run with --promote to serve this model, or promote via "
                "ModelRegistry.promote('%s').",
                args.version,
            )
    except ValueError as exc:
        # Version already exists
        log.error("Registration failed: %s", exc)
        sys.exit(3)
    except Exception as exc:
        log.error("Registry error: %s", exc)
        sys.exit(3)

    log.info("train_and_serialize.py complete.")


if __name__ == "__main__":
    main()
