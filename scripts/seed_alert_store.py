"""
AlertIQ — Alert Store Seed Script (Milestone 6)

Populates the investigation SQLite database from the AML simulation data.

What this script does
---------------------
1. Loads models/1.0.0/model.joblib directly (same artifact the API serves).
2. Reads data/simulation/alerts.csv and data/simulation/transactions.csv.
3. Scores every alert to produce a ranked risk_score and queue_position.
4. Selects a representative sample of ~500 alerts across five risk bands
   so the demo workspace contains a varied, interesting queue.
5. Loads the corresponding transaction records for each selected account.
6. Writes everything to data/alert_store.db using alert_store.upsert_alert /
   upsert_transaction.

Usage
-----
    python scripts/seed_alert_store.py                          # default paths
    python scripts/seed_alert_store.py --alerts-csv data/simulation/alerts.csv
    python scripts/seed_alert_store.py --target-count 300
    python scripts/seed_alert_store.py --clear                  # wipe before seeding

Security notes
--------------
- true_sar labels are passed to upsert_alert so they are stored in the DB,
  but alert_store / alert_routes NEVER expose them via any API endpoint.
- No external service is called; scoring is purely local.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

# Ensure the alertiq package is importable when run from the project root.
_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from alertiq.serving import alert_store as _store
from alertiq.serving.registry import ModelRegistry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("seed_alert_store")

# ------------------------------------------------------------------ #
# Risk-band sampling configuration                                     #
# ------------------------------------------------------------------ #

# Five bands, each with a target proportion of the final sample.
# The demo queue should have plenty of high-risk alerts (analyst focus)
# and a tail of medium/low to exercise all UI states.
_RISK_BANDS = [
    {"name": "critical",  "lo": 0.80, "hi": 1.01, "frac": 0.30},
    {"name": "high",      "lo": 0.60, "hi": 0.80, "frac": 0.25},
    {"name": "medium",    "lo": 0.40, "hi": 0.60, "frac": 0.25},
    {"name": "low",       "lo": 0.20, "hi": 0.40, "frac": 0.12},
    {"name": "minimal",   "lo": 0.00, "hi": 0.20, "frac": 0.08},
]

# Feature column names expected by the model (f01–f24 in order).
_FEATURE_COLS = [f"f{i:02d}_{n}" for i, n in enumerate([
    "vol_7d_log", "vol_30d_log", "vol_ratio_7_30", "max_txn_log",
    "vol_vs_revenue", "txn_count_7d", "txn_count_30d", "velocity_ratio",
    "recency_gap_days", "account_age_days", "cash_fraction_30d",
    "structuring_count_30d", "round_amount_count_30d",
    "digital_channel_fraction", "night_fraction_30d", "intl_fraction_30d",
    "distinct_jurisdictions_30d", "very_high_jur_flag",
    "shell_counterparty_fraction", "pep_flag", "adverse_media_flag",
    "high_risk_industry", "prior_alerts_90d", "account_jurisdiction_score",
], start=1)]


def _load_model(registry_path: Path) -> tuple:
    """Load champion model artifact. Returns (scorer, feature_columns, threshold, model_version)."""
    log.info("Loading champion model from %s", registry_path)
    registry = ModelRegistry(registry_path)
    artifact = registry.get_champion()
    log.info(
        "Loaded: version=%s  schema=%d  threshold=%.4f",
        artifact.model_version, artifact.schema_version, artifact.threshold,
    )
    return artifact.scorer, list(artifact.feature_columns), artifact.threshold, artifact.model_version


def _score_alerts(df: pd.DataFrame, scorer, feature_cols: list[str]) -> np.ndarray:
    """Score all alerts and return a float array of probabilities.

    TriageScorer wraps the underlying sklearn estimator; we access its
    internal model to obtain calibrated probabilities directly.
    """
    X = df[feature_cols].fillna(0).to_numpy(dtype=np.float64)
    probs = scorer._model.predict_proba(X)[:, 1]
    return probs


def _quality_flags(row: pd.Series, feature_cols: list[str]) -> dict:
    """Compute data quality flags for a single alert row."""
    vals = row[feature_cols]
    zero_names = [c for c in feature_cols if vals[c] == 0.0]
    extreme_names = [
        c for c in feature_cols
        if abs(vals[c]) > 10.0 and vals[c] != 0.0
    ]
    return {
        "has_zeroed_features": len(zero_names) > 0,
        "zero_feature_names": zero_names,
        "has_extreme_values": len(extreme_names) > 0,
        "extreme_feature_names": extreme_names,
        "quality_warning": len(zero_names) > 3 or len(extreme_names) > 0,
    }


def _sample_alerts(df: pd.DataFrame, target_count: int, rng: np.random.Generator) -> pd.DataFrame:
    """Return a stratified sample across risk bands."""
    parts = []
    for band in _RISK_BANDS:
        mask = (df["risk_score"] >= band["lo"]) & (df["risk_score"] < band["hi"])
        pool = df[mask]
        n = max(1, round(target_count * band["frac"]))
        n = min(n, len(pool))
        if n > 0:
            sampled = pool.sample(n=n, random_state=int(rng.integers(10_000)))
            parts.append(sampled)
            log.info(
                "  Band %-10s  lo=%.2f hi=%.2f  pool=%5d  sampled=%3d",
                band["name"], band["lo"], band["hi"], len(pool), n,
            )
        else:
            log.warning("  Band %-10s  pool is empty — skipping", band["name"])
    result = pd.concat(parts, ignore_index=True)
    # Sort by risk_score descending so queue_position reflects rank.
    result = result.sort_values("risk_score", ascending=False).reset_index(drop=True)
    log.info("Total sampled: %d alerts", len(result))
    return result


def _seed_alerts(
    sampled: pd.DataFrame,
    feature_cols: list[str],
    model_version: str,
    scored_at_str: str,
) -> None:
    """Write all sampled alerts into the investigation store."""
    n = len(sampled)
    for i, (_, row) in enumerate(sampled.iterrows()):
        features = {c: float(row[c]) for c in feature_cols}
        qf = _quality_flags(row, feature_cols)
        _store.upsert_alert(
            alert_id=str(row["alert_id"]),
            account_id=str(row["account_id"]),
            rule_id=str(row["rule_id"]),
            rule_name=str(row["rule_name"]),
            severity=str(row["severity"]),
            alert_date=str(row["alert_date"]),
            risk_score=float(row["risk_score"]),
            queue_position=int(i + 1),
            features=features,
            quality_flags=qf,
            model_version=model_version,
            schema_version=1,
            scored_at=scored_at_str,
            true_sar=int(row.get("true_sar", 0)),
        )
        if (i + 1) % 100 == 0 or (i + 1) == n:
            log.info("  Upserted %d / %d alerts", i + 1, n)


def _seed_transactions(
    sampled_accounts: set[str],
    txn_df: pd.DataFrame,
    sampled_df: pd.DataFrame,
) -> None:
    """Write pre-alert transaction records for all accounts in the sample.

    TEMPORAL INTEGRITY: Only transactions with txn_date <= the earliest alert_date
    for that account are seeded.  This mirrors the runtime enforcement in
    get_alert_transactions() and ensures no future-dated transactions enter the
    investigation store.

    The earliest alert_date per account is used as the cut-off so that all
    transactions pre-dating ANY alert for that account are available.
    """
    # Build earliest alert_date per account so we seed up to that point.
    earliest_alert = (
        sampled_df.groupby("account_id")["alert_date"]
        .min()
        .to_dict()
    )

    # Apply temporal filter: keep only transactions that pre-date or coincide
    # with the earliest alert for that account.
    def _within_temporal_window(r: pd.Series) -> bool:
        cutoff = earliest_alert.get(r["account_id"])
        return cutoff is not None and str(r["txn_date"]) <= str(cutoff)

    account_txns = txn_df[txn_df["account_id"].isin(sampled_accounts)]
    temporal_mask = account_txns.apply(_within_temporal_window, axis=1)
    account_txns = account_txns[temporal_mask]

    total = len(account_txns)
    log.info(
        "Loading %d transactions for %d accounts (temporal filter: txn_date <= earliest alert_date)",
        total, len(sampled_accounts),
    )
    for i, (_, row) in enumerate(account_txns.iterrows()):
        _store.upsert_transaction(
            txn_id=str(row["txn_id"]),
            account_id=str(row["account_id"]),
            txn_date=str(row["txn_date"]),
            txn_datetime=str(row["txn_datetime"]) if pd.notna(row.get("txn_datetime")) else str(row["txn_date"]),
            txn_type=str(row["txn_type"]) if pd.notna(row.get("txn_type")) else "unknown",
            channel=str(row["channel"]) if pd.notna(row.get("channel")) else "unknown",
            amount_eur=float(row["amount_eur"]) if pd.notna(row.get("amount_eur")) else 0.0,
            is_international=int(row["is_international"]) if pd.notna(row.get("is_international")) else 0,
            destination_jurisdiction=str(row["destination_jurisdiction"]) if pd.notna(row.get("destination_jurisdiction")) else None,
            counterparty_id=str(row["counterparty_id"]) if pd.notna(row.get("counterparty_id")) else None,
            counterparty_jurisdiction=str(row["counterparty_jurisdiction"]) if pd.notna(row.get("counterparty_jurisdiction")) else None,
            counterparty_is_shell=int(row["counterparty_is_shell"]) if pd.notna(row.get("counterparty_is_shell")) else 0,
            is_typology=int(row["is_typology"]) if pd.notna(row.get("is_typology")) else 0,
        )
        if (i + 1) % 1000 == 0 or (i + 1) == total:
            log.info("  Upserted %d / %d transactions", i + 1, total)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the AlertIQ investigation store")
    parser.add_argument(
        "--alerts-csv", default="data/simulation/alerts.csv",
        help="Path to alerts.csv (default: data/simulation/alerts.csv)",
    )
    parser.add_argument(
        "--transactions-csv", default="data/simulation/transactions.csv",
        help="Path to transactions.csv (default: data/simulation/transactions.csv)",
    )
    parser.add_argument(
        "--registry-path", default="models",
        help="Path to model registry directory (default: models)",
    )
    parser.add_argument(
        "--target-count", type=int, default=500,
        help="Approximate number of alerts to load (default: 500)",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for reproducible sampling (default: 42)",
    )
    parser.add_argument(
        "--clear", action="store_true",
        help="Delete existing alert_store.db before seeding",
    )
    args = parser.parse_args()

    db_path = os.environ.get("ALERTIQ_DB_PATH", "data/alert_store.db")

    if args.clear and Path(db_path).exists():
        log.info("Clearing existing database: %s", db_path)
        Path(db_path).unlink()

    # Set DB path so alert_store uses the correct file.
    os.environ.setdefault("ALERTIQ_DB_PATH", db_path)

    _store.init_db()

    # Load model.
    scorer, feature_cols, threshold, model_version = _load_model(Path(args.registry_path))

    # Load alerts CSV.
    log.info("Reading alerts: %s", args.alerts_csv)
    alerts_df = pd.read_csv(args.alerts_csv)
    log.info("  %d total alerts", len(alerts_df))

    # Normalise column name: alerts.csv uses 'triggered_date'; the store uses
    # 'alert_date'.  Rename so all downstream code is consistent.
    if "triggered_date" in alerts_df.columns and "alert_date" not in alerts_df.columns:
        alerts_df = alerts_df.rename(columns={"triggered_date": "alert_date"})

    # Score all alerts — use the artifact's scorer (sklearn Pipeline).
    log.info("Scoring %d alerts …", len(alerts_df))
    probs = _score_alerts(alerts_df, scorer, feature_cols)
    alerts_df["risk_score"] = probs

    # Assign global queue_position (rank by risk_score descending; used to
    # establish the top-20% capacity band across the full population).
    alerts_df["global_rank"] = alerts_df["risk_score"].rank(ascending=False, method="first").astype(int)

    # Print score distribution summary.
    log.info(
        "Score distribution: min=%.3f  p25=%.3f  p50=%.3f  p75=%.3f  max=%.3f",
        probs.min(), np.percentile(probs, 25), np.percentile(probs, 50),
        np.percentile(probs, 75), probs.max(),
    )
    above_threshold = (probs >= threshold).sum()
    log.info("Above threshold (%.4f): %d / %d (%.1f%%)",
             threshold, above_threshold, len(probs), 100 * above_threshold / len(probs))

    # Stratified sample.
    log.info("Sampling %d alerts across risk bands …", args.target_count)
    rng = np.random.default_rng(args.seed)
    sampled = _sample_alerts(alerts_df, args.target_count, rng)

    # Load transactions.
    log.info("Reading transactions: %s", args.transactions_csv)
    txn_df = pd.read_csv(args.transactions_csv)
    log.info("  %d total transactions", len(txn_df))

    # Seed.
    from datetime import datetime, timezone
    scored_at = datetime.now(timezone.utc).isoformat()

    log.info("Seeding %d alerts …", len(sampled))
    _seed_alerts(sampled, feature_cols, model_version, scored_at)

    sampled_accounts = set(sampled["account_id"].unique())
    _seed_transactions(sampled_accounts, txn_df, sampled)

    # Summary.
    stats = _store.get_queue_stats()
    log.info(
        "Done. DB=%s  alerts=%d  capacity_count=%d  capacity_fraction=%.0f%%",
        db_path, stats["total_alerts"], stats["capacity_count"],
        stats["capacity_fraction"] * 100,
    )


if __name__ == "__main__":
    main()
