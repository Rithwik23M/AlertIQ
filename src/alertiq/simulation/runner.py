"""
Simulation orchestrator.

Coordinates the full simulation pipeline:
  1. Generate account population
  2. For each simulation day:
     a. Generate routine + typology transactions
     b. Update account state (last_txn_date, cumulative_volume)
     c. Evaluate all 15 TMS rules per account
  3. Assign ground truth labels
  4. Compute 24 alert features
  5. Write output CSVs
  6. Return SimulationResult

Calling the runner twice with the same SimulationConfig produces
structurally identical output (determinism guarantee): the same accounts,
transactions, SAR labels, and feature values are generated.  Alert and
transaction IDs are random UUIDs (not seeded) and will differ between runs,
but all content-bearing fields are reproducible.

Usage:
    from alertiq.simulation.runner import run_simulation
    from alertiq.simulation.config import SimulationConfig

    result = run_simulation(SimulationConfig(seed=42, n_accounts=500))
"""

from __future__ import annotations

import csv
import datetime
import logging
from collections import defaultdict
from pathlib import Path

from .config import SimulationConfig
from .entities import (
    Account,
    Alert,
    AlertSeverity,
    SimulationResult,
    Transaction,
    new_id,
)
from .features import FEATURE_NAMES, compute_alert_features
from .ground_truth import assign_ground_truth, verify_ground_truth_integrity
from .population import generate_account_population
from .tms import ALL_RULES, configure_thresholds
from .transactions import generate_daily_transactions, iter_simulation_days

log = logging.getLogger(__name__)

# Rolling look-back window for TMS rule evaluation (days)
# Rules use this window unless they maintain their own logic
_TMS_WINDOW_DAYS = 30


class SimulationError(Exception):
    """Raised when the simulation enters an invalid state."""


def _build_account_index(accounts: list[Account]) -> dict[str, int]:
    """Map account_id → index in accounts list."""
    return {acc.account_id: idx for idx, acc in enumerate(accounts)}


def _update_account_state(account: Account, txns: list[Transaction]) -> None:
    """Update mutable account state from new transactions."""
    if not txns:
        return
    latest_date = max(t.txn_date for t in txns)
    if account.last_txn_date is None or latest_date > account.last_txn_date:
        account.last_txn_date = latest_date
    account.cumulative_volume_eur += sum(t.amount_eur for t in txns)
    account.txn_count += len(txns)


def _evaluate_rules_for_account(
    account: Account,
    all_account_txns: list[Transaction],
    sim_date: datetime.date,
) -> list[Alert]:
    """Run all 15 TMS rules for one account on the current date."""
    cutoff = sim_date - datetime.timedelta(days=_TMS_WINDOW_DAYS)
    window_txns = [
        t for t in all_account_txns
        if cutoff <= t.txn_date <= sim_date
    ]

    # Deduplicate alerts by rule_id per account per day
    seen_rules: set[str] = set()
    alerts: list[Alert] = []

    for rule in ALL_RULES:
        new_alerts = rule.evaluate(account, window_txns, all_account_txns)
        for alert in new_alerts:
            key = f"{rule.metadata.rule_id}:{alert.triggered_date}"
            if key not in seen_rules:
                seen_rules.add(key)
                alerts.append(alert)

    return alerts


def _write_accounts_csv(accounts: list[Account], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "account_id", "account_type", "risk_category",
            "jurisdiction", "onboard_date",
            "declared_annual_revenue", "expected_monthly_volume",
            "has_pep_link", "has_adverse_media", "is_high_risk_industry",
            "assigned_typology",
        ])
        for acc in accounts:
            writer.writerow([
                acc.account_id,
                acc.account_type.value,
                acc.risk_category.value,
                acc.jurisdiction.value,
                acc.onboard_date.isoformat(),
                acc.declared_annual_revenue,
                acc.expected_monthly_volume,
                int(acc.has_pep_link),
                int(acc.has_adverse_media),
                int(acc.is_high_risk_industry),
                acc.assigned_typology.value if acc.assigned_typology else "",
            ])


def _write_transactions_csv(txns: list[Transaction], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "txn_id", "account_id", "txn_date", "txn_datetime",
            "txn_type", "channel", "amount_eur",
            "is_typology", "typology_type",
            "is_international", "destination_jurisdiction",
            "counterparty_id", "counterparty_jurisdiction",
            "counterparty_is_shell", "counterparty_is_crypto",
        ])
        for t in txns:
            cp = t.counterparty
            writer.writerow([
                t.txn_id,
                t.account_id,
                t.txn_date.isoformat(),
                t.txn_datetime.isoformat(),
                t.txn_type.value,
                t.channel.value,
                t.amount_eur,
                int(t.is_typology),
                t.typology_type.value if t.typology_type else "",
                int(t.is_international),
                t.destination_jurisdiction.value if t.destination_jurisdiction else "",
                cp.counterparty_id if cp else "",
                cp.jurisdiction.value if cp else "",
                int(cp.is_shell) if cp else "",
                int(cp.is_crypto) if cp else "",
            ])


def _write_alerts_csv(alerts: list[Alert], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="") as f:
        writer = csv.writer(f)
        feature_cols = FEATURE_NAMES
        writer.writerow([
            "alert_id", "account_id", "triggered_date",
            "rule_id", "rule_name", "severity", "status",
            "true_sar", "triggered_by_typology_txn",
        ] + feature_cols)
        for alert in alerts:
            feature_vals = [alert.features.get(fn, "") for fn in feature_cols]
            writer.writerow([
                alert.alert_id,
                alert.account_id,
                alert.triggered_date.isoformat(),
                alert.rule_id,
                alert.rule_name,
                alert.severity.value,
                alert.status.value,
                int(alert.true_sar) if alert.true_sar is not None else "",
                int(alert.triggered_by_typology_txn),
            ] + feature_vals)


def run_simulation(config: SimulationConfig) -> SimulationResult:
    """Run a complete simulation and return the result.

    Args:
        config: Frozen SimulationConfig.  Same config + same seed = same output.

    Returns:
        SimulationResult with all accounts, transactions, and alerts populated.

    Raises:
        SimulationError: If ground truth integrity checks fail.
    """
    log.info("Starting simulation: seed=%d, n_accounts=%d, period=%s→%s",
             config.seed, config.n_accounts, config.start_date, config.end_date)

    # Step 1: Configure TMS rule thresholds
    configure_thresholds(config)

    # Step 2: Generate account population
    accounts = generate_account_population(config)
    account_index = _build_account_index(accounts)
    account_map: dict[str, Account] = {acc.account_id: acc for acc in accounts}

    log.info("Generated %d accounts", len(accounts))

    # Step 3: Per-account transaction history buffer (for rule evaluation)
    # Maps account_id → list of all transactions so far
    account_txns: dict[str, list[Transaction]] = {
        acc.account_id: [] for acc in accounts
    }

    # Track alert counts per account for F23 feature
    account_alert_count: dict[str, int] = defaultdict(int)

    # Global deduplication: prevent the same (account, rule, triggered_date)
    # tuple from generating more than one alert across the entire simulation.
    # Without this, transaction-based rules (e.g. R06) re-fire for the same
    # transaction every day it remains inside the rolling 30-day window.
    seen_alert_keys: set[tuple[str, str, datetime.date]] = set()

    all_transactions: list[Transaction] = []
    all_alerts: list[Alert] = []

    typology_txn_counts: dict[str, int] = defaultdict(int)
    rule_trigger_counts: dict[str, int] = defaultdict(int)

    start_date = datetime.date.fromisoformat(config.start_date)

    # Step 4: Day-by-day simulation
    for day_idx, sim_date in iter_simulation_days(config):
        if day_idx % 30 == 0:
            log.debug("Simulating day %d / %d: %s", day_idx, config.simulation_days(), sim_date)

        # 4a: Generate transactions
        day_txns = generate_daily_transactions(
            accounts, sim_date, day_idx, config, account_index
        )

        # 4b: Index today's transactions by account
        day_txns_by_account: dict[str, list[Transaction]] = defaultdict(list)
        for txn in day_txns:
            day_txns_by_account[txn.account_id].append(txn)
            if txn.is_typology and txn.typology_type:
                typology_txn_counts[txn.typology_type.value] += 1

        # 4c: Extend history so rules see today's transactions.
        #     IMPORTANT: update account_txns (read-only history used by rules)
        #     BEFORE calling evaluate, but update account.last_txn_date AFTER
        #     rule evaluation so that R05 (Dormant Account) can compare the
        #     pre-today last_txn_date against today's batch.
        for acc_id, acc_txns_today in day_txns_by_account.items():
            account_txns[acc_id].extend(acc_txns_today)

        all_transactions.extend(day_txns)

        # 4d: Evaluate TMS rules per account (before state update preserves
        #     account.last_txn_date from the previous day for dormancy checks)
        for account in accounts:
            acc_all_txns = account_txns[account.account_id]
            if not acc_all_txns:
                continue

            day_alerts = _evaluate_rules_for_account(
                account, acc_all_txns, sim_date
            )

            for alert in day_alerts:
                # Global deduplication: skip if (account, rule, date) already fired.
                # This prevents transaction-based rules from re-alerting every day
                # a triggering transaction stays inside the rolling window.
                alert_key = (alert.account_id, alert.rule_id, alert.triggered_date)
                if alert_key in seen_alert_keys:
                    continue
                seen_alert_keys.add(alert_key)

                # Set F23 (prior alerts) before adding this alert to history
                alert.features["f23_prior_alerts_90d"] = float(
                    account_alert_count[account.account_id]
                )
                account_alert_count[account.account_id] += 1
                rule_trigger_counts[alert.rule_id] += 1
                all_alerts.append(alert)

        # 4e: Update account mutable state (last_txn_date, cumulative_volume,
        #     txn_count) AFTER rule evaluation so dormancy checks are correct.
        for acc_id, acc_txns_today in day_txns_by_account.items():
            _update_account_state(account_map[acc_id], acc_txns_today)

    log.info("Generated %d transactions, %d alerts",
             len(all_transactions), len(all_alerts))

    # Step 5: Assign ground truth SAR labels
    assign_ground_truth(all_alerts, account_map)

    # Step 6: Integrity verification
    integrity_errors = verify_ground_truth_integrity(all_alerts, account_map)
    if integrity_errors:
        error_summary = "\n".join(integrity_errors[:10])
        raise SimulationError(
            f"Ground truth integrity check failed ({len(integrity_errors)} errors):\n"
            f"{error_summary}"
        )

    # Step 7: Compute features for all alerts
    for alert in all_alerts:
        account = account_map[alert.account_id]
        acc_txns_to_date = [
            t for t in account_txns[alert.account_id]
            if t.txn_date <= alert.triggered_date
        ]
        features = compute_alert_features(alert, account, acc_txns_to_date)
        # Preserve F23 which was set before feature computation
        prior_alerts = alert.features.get("f23_prior_alerts_90d", 0.0)
        alert.features = features
        alert.features["f23_prior_alerts_90d"] = prior_alerts

    # Step 8: Build summary result
    n_active_ml = sum(
        1 for acc in accounts
        if acc.risk_category.value == "active_ml"
    )
    n_true_sar = sum(1 for a in all_alerts if a.true_sar is True)

    result = SimulationResult(
        config_seed=config.seed,
        start_date=datetime.date.fromisoformat(config.start_date),
        end_date=datetime.date.fromisoformat(config.end_date),
        accounts=accounts,
        transactions=all_transactions,
        alerts=all_alerts,
        n_accounts=len(accounts),
        n_transactions=len(all_transactions),
        n_alerts=len(all_alerts),
        n_true_sar=n_true_sar,
        n_active_ml_accounts=n_active_ml,
        typology_txn_counts=dict(typology_txn_counts),
        rule_trigger_counts=dict(rule_trigger_counts),
    )

    log.info(
        "Simulation complete: %d accounts, %d txns, %d alerts, %d true_sar (%.1f%%)",
        result.n_accounts,
        result.n_transactions,
        result.n_alerts,
        result.n_true_sar,
        result.sar_rate * 100,
    )

    # Step 9: Write output files
    if any([config.write_accounts, config.write_transactions, config.write_alerts]):
        output_dir = config.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        if config.write_accounts:
            _write_accounts_csv(accounts, output_dir / "accounts.csv")
            log.info("Wrote accounts.csv")

        if config.write_transactions:
            _write_transactions_csv(all_transactions, output_dir / "transactions.csv")
            log.info("Wrote transactions.csv")

        if config.write_alerts:
            _write_alerts_csv(all_alerts, output_dir / "alerts.csv")
            log.info("Wrote alerts.csv")

    return result
