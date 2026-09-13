"""
AlertIQ Investigation Store — SQLite-backed persistence for alert management.

Design decisions
----------------
1. SQLite is used for the portfolio deployment.  In a production AML
   deployment, this would be replaced with a durable, ACID-compliant
   database (PostgreSQL/Cloud SQL) with appropriate audit controls.

2. All write operations are synchronous.  FastAPI/Starlette handlers call
   these via standard def routes (not async def) to avoid blocking the event
   loop.  The operations are fast (single-table writes on an indexed SQLite
   file) and acceptable for a portfolio demo.

3. The alert store holds three concerns deliberately separate:
   a. Scored alert records  (immutable after creation — model evidence)
   b. Investigation state   (mutable — analyst status / decision)
   c. Audit events          (append-only — permanent investigation log)

4. Analyst identity is a pseudonymous placeholder ("ANL-01", etc.).
   In production, this would be replaced with a proper IAM/SSO identity.

5. The ``true_sar`` field from simulation ground truth is NEVER exposed
   through any API endpoint.  It exists only to support future model
   feedback evaluation by privileged maintainers.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Default store path relative to the working directory.
_DEFAULT_DB_PATH = "data/alert_store.db"


def _get_db_path() -> Path:
    return Path(os.environ.get("ALERTIQ_STORE_PATH", _DEFAULT_DB_PATH))


def _connect() -> sqlite3.Connection:
    """Open a thread-local SQLite connection with WAL mode and row_factory."""
    path = _get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Create all tables if they do not already exist."""
    conn = _connect()
    try:
        conn.executescript("""
        -- -------------------------------------------------------- --
        -- alerts: pre-scored, immutable after creation              --
        -- -------------------------------------------------------- --
        CREATE TABLE IF NOT EXISTS alerts (
            alert_id            TEXT PRIMARY KEY,
            account_id          TEXT NOT NULL,
            rule_id             TEXT NOT NULL,
            rule_name           TEXT NOT NULL,
            severity            TEXT NOT NULL,
            alert_date          TEXT NOT NULL,
            risk_score          REAL NOT NULL,
            queue_position      INTEGER NOT NULL,
            features_json       TEXT NOT NULL,
            quality_flags_json  TEXT NOT NULL,
            model_version       TEXT NOT NULL,
            schema_version      INTEGER NOT NULL,
            scored_at           TEXT NOT NULL,
            -- Ground truth from simulation — NEVER exposed via API
            true_sar            INTEGER NOT NULL DEFAULT 0,
            created_at          TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_alerts_risk_score ON alerts(risk_score DESC);
        CREATE INDEX IF NOT EXISTS idx_alerts_account_id ON alerts(account_id);
        CREATE INDEX IF NOT EXISTS idx_alerts_alert_date ON alerts(alert_date);

        -- -------------------------------------------------------- --
        -- investigation_state: mutable analyst status per alert     --
        -- -------------------------------------------------------- --
        CREATE TABLE IF NOT EXISTS investigation_state (
            alert_id        TEXT PRIMARY KEY REFERENCES alerts(alert_id),
            status          TEXT NOT NULL DEFAULT 'new',
            -- 'new' | 'in_progress' | 'escalated' | 'closed' | 'needs_further_review'
            assigned_to     TEXT,
            updated_at      TEXT NOT NULL
        );

        -- -------------------------------------------------------- --
        -- notes: analyst investigation notes (append-only)          --
        -- -------------------------------------------------------- --
        CREATE TABLE IF NOT EXISTS notes (
            note_id     TEXT PRIMARY KEY,
            alert_id    TEXT NOT NULL REFERENCES alerts(alert_id),
            analyst_id  TEXT NOT NULL,
            content     TEXT NOT NULL,
            created_at  TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_notes_alert_id ON notes(alert_id);

        -- -------------------------------------------------------- --
        -- decisions: analyst investigation decisions (append-only)  --
        -- -------------------------------------------------------- --
        CREATE TABLE IF NOT EXISTS decisions (
            decision_id       TEXT PRIMARY KEY,
            alert_id          TEXT NOT NULL REFERENCES alerts(alert_id),
            analyst_id        TEXT NOT NULL,
            outcome           TEXT NOT NULL,
            -- 'escalate' | 'close' | 'needs_further_review'
            rationale         TEXT,
            previous_status   TEXT NOT NULL,
            decided_at        TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_decisions_alert_id ON decisions(alert_id);

        -- -------------------------------------------------------- --
        -- audit_events: every meaningful investigation action        --
        -- -------------------------------------------------------- --
        CREATE TABLE IF NOT EXISTS audit_events (
            event_id    TEXT PRIMARY KEY,
            alert_id    TEXT NOT NULL REFERENCES alerts(alert_id),
            event_type  TEXT NOT NULL,
            analyst_id  TEXT NOT NULL,
            details_json TEXT NOT NULL,
            occurred_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_audit_alert_id ON audit_events(alert_id);
        CREATE INDEX IF NOT EXISTS idx_audit_occurred_at ON audit_events(occurred_at);

        -- -------------------------------------------------------- --
        -- transactions: account transaction timeline                 --
        -- -------------------------------------------------------- --
        CREATE TABLE IF NOT EXISTS transactions (
            txn_id                  TEXT PRIMARY KEY,
            account_id              TEXT NOT NULL,
            txn_date                TEXT NOT NULL,
            txn_datetime            TEXT,
            txn_type                TEXT NOT NULL,
            channel                 TEXT NOT NULL,
            amount_eur              REAL NOT NULL,
            is_international        INTEGER NOT NULL DEFAULT 0,
            destination_jurisdiction TEXT,
            counterparty_id         TEXT,
            counterparty_jurisdiction TEXT,
            counterparty_is_shell   INTEGER NOT NULL DEFAULT 0,
            is_typology             INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_txn_account_id ON transactions(account_id);
        CREATE INDEX IF NOT EXISTS idx_txn_date ON transactions(txn_date);
        """)
        conn.commit()
    finally:
        conn.close()


# ------------------------------------------------------------------ #
# Alert ingestion (used by seed script)                               #
# ------------------------------------------------------------------ #

def upsert_alert(
    alert_id: str,
    account_id: str,
    rule_id: str,
    rule_name: str,
    severity: str,
    alert_date: str,
    risk_score: float,
    queue_position: int,
    features: dict[str, Any],
    quality_flags: dict[str, Any],
    model_version: str,
    schema_version: int,
    scored_at: str,
    true_sar: int = 0,
) -> None:
    now = _now()
    conn = _connect()
    try:
        conn.execute("""
            INSERT OR REPLACE INTO alerts
            (alert_id, account_id, rule_id, rule_name, severity, alert_date,
             risk_score, queue_position, features_json, quality_flags_json,
             model_version, schema_version, scored_at, true_sar, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            alert_id, account_id, rule_id, rule_name, severity, alert_date,
            risk_score, queue_position, json.dumps(features), json.dumps(quality_flags),
            model_version, schema_version, scored_at, true_sar, now,
        ))
        # Initialise investigation state as 'new'
        conn.execute("""
            INSERT OR IGNORE INTO investigation_state (alert_id, status, updated_at)
            VALUES (?, 'new', ?)
        """, (alert_id, now))
        conn.commit()
    finally:
        conn.close()


def upsert_transaction(
    txn_id: str,
    account_id: str,
    txn_date: str,
    txn_datetime: str | None,
    txn_type: str,
    channel: str,
    amount_eur: float,
    is_international: int,
    destination_jurisdiction: str | None,
    counterparty_id: str | None,
    counterparty_jurisdiction: str | None,
    counterparty_is_shell: int,
    is_typology: int,
) -> None:
    conn = _connect()
    try:
        conn.execute("""
            INSERT OR IGNORE INTO transactions
            (txn_id, account_id, txn_date, txn_datetime, txn_type, channel,
             amount_eur, is_international, destination_jurisdiction,
             counterparty_id, counterparty_jurisdiction, counterparty_is_shell, is_typology)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            txn_id, account_id, txn_date, txn_datetime, txn_type, channel,
            amount_eur, is_international, destination_jurisdiction,
            counterparty_id, counterparty_jurisdiction, counterparty_is_shell, is_typology,
        ))
        conn.commit()
    finally:
        conn.close()


# ------------------------------------------------------------------ #
# Queue queries                                                        #
# ------------------------------------------------------------------ #

def get_queue_stats() -> dict[str, Any]:
    """Return capacity/queue statistics for the analyst banner."""
    conn = _connect()
    try:
        total = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
        new_count = conn.execute(
            "SELECT COUNT(*) FROM investigation_state WHERE status = 'new'"
        ).fetchone()[0]
        in_progress = conn.execute(
            "SELECT COUNT(*) FROM investigation_state WHERE status = 'in_progress'"
        ).fetchone()[0]
        escalated = conn.execute(
            "SELECT COUNT(*) FROM investigation_state WHERE status = 'escalated'"
        ).fetchone()[0]
        closed = conn.execute(
            "SELECT COUNT(*) FROM investigation_state WHERE status IN ('closed', 'needs_further_review')"
        ).fetchone()[0]
        # Top 20% by risk score = the "capacity" queue
        capacity_count = max(1, round(total * 0.20))
        return {
            "total_alerts": total,
            "capacity_fraction": 0.20,
            "capacity_count": capacity_count,
            "status_counts": {
                "new": new_count,
                "in_progress": in_progress,
                "escalated": escalated,
                "closed": closed,
            },
        }
    finally:
        conn.close()


def list_alerts(
    status: str | None = None,
    rule_id: str | None = None,
    min_score: float | None = None,
    search: str | None = None,
    sort_by: str = "risk_score",
    sort_dir: str = "desc",
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    """Return a paginated, filtered alert list joined with investigation state."""
    allowed_sort = {"risk_score", "alert_date", "severity", "queue_position"}
    if sort_by not in allowed_sort:
        sort_by = "risk_score"
    sort_dir = "DESC" if sort_dir.lower() == "desc" else "ASC"

    where_clauses: list[str] = []
    params: list[Any] = []

    if status:
        where_clauses.append("ist.status = ?")
        params.append(status)
    if rule_id:
        where_clauses.append("a.rule_id = ?")
        params.append(rule_id)
    if min_score is not None:
        where_clauses.append("a.risk_score >= ?")
        params.append(min_score)
    if search:
        where_clauses.append("(a.alert_id LIKE ? OR a.account_id LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    base_query = f"""
        SELECT a.alert_id, a.account_id, a.rule_id, a.rule_name, a.severity,
               a.alert_date, a.risk_score, a.queue_position,
               a.quality_flags_json, a.model_version, a.scored_at,
               ist.status
        FROM alerts a
        JOIN investigation_state ist ON a.alert_id = ist.alert_id
        {where_sql}
    """

    conn = _connect()
    try:
        total = conn.execute(
            f"SELECT COUNT(*) FROM ({base_query})", params
        ).fetchone()[0]

        offset = (page - 1) * page_size
        rows = conn.execute(
            f"{base_query} ORDER BY a.{sort_by} {sort_dir} LIMIT ? OFFSET ?",
            params + [page_size, offset],
        ).fetchall()

        items = []
        for r in rows:
            qf = json.loads(r["quality_flags_json"])
            items.append({
                "alert_id": r["alert_id"],
                "account_id": r["account_id"],
                "rule_id": r["rule_id"],
                "rule_name": r["rule_name"],
                "severity": r["severity"],
                "alert_date": r["alert_date"],
                "risk_score": r["risk_score"],
                "queue_position": r["queue_position"],
                "status": r["status"],
                "quality_warning": qf.get("quality_warning", False),
                "model_version": r["model_version"],
                "scored_at": r["scored_at"],
            })

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": items,
        }
    finally:
        conn.close()


# ------------------------------------------------------------------ #
# Alert detail                                                         #
# ------------------------------------------------------------------ #

def get_alert(alert_id: str) -> dict[str, Any] | None:
    """Return full alert detail including features and investigation state."""
    conn = _connect()
    try:
        row = conn.execute("""
            SELECT a.*, ist.status, ist.assigned_to, ist.updated_at as state_updated_at
            FROM alerts a
            JOIN investigation_state ist ON a.alert_id = ist.alert_id
            WHERE a.alert_id = ?
        """, (alert_id,)).fetchone()

        if row is None:
            return None

        features = json.loads(row["features_json"])
        quality_flags = json.loads(row["quality_flags_json"])

        # Build deterministic explainability signals from feature values
        signals = _compute_explainability_signals(features, quality_flags)

        return {
            "alert_id": row["alert_id"],
            "account_id": row["account_id"],
            "rule_id": row["rule_id"],
            "rule_name": row["rule_name"],
            "severity": row["severity"],
            "alert_date": row["alert_date"],
            "risk_score": row["risk_score"],
            "queue_position": row["queue_position"],
            "model_version": row["model_version"],
            "schema_version": row["schema_version"],
            "scored_at": row["scored_at"],
            "status": row["status"],
            "assigned_to": row["assigned_to"],
            "features": features,
            "quality_flags": quality_flags,
            "explainability_signals": signals,
        }
    finally:
        conn.close()


def get_alert_transactions(alert_id: str, limit: int = 100) -> list[dict[str, Any]]:
    """Return pre-alert transactions for the account associated with this alert.

    TEMPORAL INTEGRITY: Only transactions with txn_date <= alert_date are returned.
    This enforces the investigation evidence constraint that an analyst must only
    see information that was available at or before the alert was generated.
    Future-dated transactions are never shown as evidence for a historical alert.
    """
    conn = _connect()
    try:
        # Get the account_id and alert_date for this alert
        row = conn.execute(
            "SELECT account_id, alert_date FROM alerts WHERE alert_id = ?",
            (alert_id,)
        ).fetchone()
        if row is None:
            return []

        account_id = row["account_id"]
        alert_date = row["alert_date"]  # ISO date string, e.g. "2023-03-15"

        # TEMPORAL INTEGRITY GATE: only transactions that pre-date or coincide
        # with the alert date may appear as investigation evidence.
        # txn_date <= alert_date ensures no future-data leakage.
        rows = conn.execute("""
            SELECT txn_id, account_id, txn_date, txn_datetime, txn_type, channel,
                   amount_eur, is_international, destination_jurisdiction,
                   counterparty_id, counterparty_jurisdiction,
                   counterparty_is_shell, is_typology
            FROM transactions
            WHERE account_id = ?
              AND txn_date <= ?
            ORDER BY txn_date DESC, txn_datetime DESC
            LIMIT ?
        """, (account_id, alert_date, limit)).fetchall()

        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_alert_history(alert_id: str) -> list[dict[str, Any]]:
    """Return full audit event log for an alert, oldest first."""
    conn = _connect()
    try:
        rows = conn.execute("""
            SELECT event_id, event_type, analyst_id, details_json, occurred_at
            FROM audit_events
            WHERE alert_id = ?
            ORDER BY occurred_at ASC
        """, (alert_id,)).fetchall()

        return [
            {
                "event_id": r["event_id"],
                "event_type": r["event_type"],
                "analyst_id": r["analyst_id"],
                "details": json.loads(r["details_json"]),
                "occurred_at": r["occurred_at"],
            }
            for r in rows
        ]
    finally:
        conn.close()


def get_alert_notes(alert_id: str) -> list[dict[str, Any]]:
    conn = _connect()
    try:
        rows = conn.execute("""
            SELECT note_id, analyst_id, content, created_at
            FROM notes WHERE alert_id = ? ORDER BY created_at ASC
        """, (alert_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_alert_decisions(alert_id: str) -> list[dict[str, Any]]:
    conn = _connect()
    try:
        rows = conn.execute("""
            SELECT decision_id, analyst_id, outcome, rationale,
                   previous_status, decided_at
            FROM decisions WHERE alert_id = ? ORDER BY decided_at ASC
        """, (alert_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ------------------------------------------------------------------ #
# Analyst write operations                                             #
# ------------------------------------------------------------------ #

def open_alert(alert_id: str, analyst_id: str) -> bool:
    """Record that an analyst opened this alert for investigation.

    Transitions status from 'new' → 'in_progress' (idempotent if already open).
    Returns True if alert exists.
    """
    now = _now()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT status FROM investigation_state WHERE alert_id = ?",
            (alert_id,)
        ).fetchone()
        if row is None:
            return False

        previous_status = row["status"]
        if previous_status == "new":
            conn.execute("""
                UPDATE investigation_state SET status = 'in_progress', updated_at = ?
                WHERE alert_id = ?
            """, (now, alert_id))

        _write_audit_event(conn, alert_id, "alert_opened", analyst_id, {
            "previous_status": previous_status,
        }, now)
        conn.commit()
        return True
    finally:
        conn.close()


def add_note(alert_id: str, analyst_id: str, content: str) -> dict[str, Any] | None:
    """Add an investigation note. Returns the created note or None if alert missing."""
    if not content.strip():
        return None

    now = _now()
    note_id = str(uuid.uuid4())

    conn = _connect()
    try:
        exists = conn.execute(
            "SELECT 1 FROM alerts WHERE alert_id = ?", (alert_id,)
        ).fetchone()
        if not exists:
            return None

        conn.execute("""
            INSERT INTO notes (note_id, alert_id, analyst_id, content, created_at)
            VALUES (?,?,?,?,?)
        """, (note_id, alert_id, analyst_id, content.strip(), now))

        _write_audit_event(conn, alert_id, "note_added", analyst_id, {
            "note_id": note_id,
            "content_length": len(content.strip()),
        }, now)
        conn.commit()

        return {
            "note_id": note_id,
            "alert_id": alert_id,
            "analyst_id": analyst_id,
            "content": content.strip(),
            "created_at": now,
        }
    finally:
        conn.close()


VALID_OUTCOMES = frozenset({"escalate", "close", "needs_further_review"})


def record_decision(
    alert_id: str,
    analyst_id: str,
    outcome: str,
    rationale: str | None = None,
) -> dict[str, Any] | None:
    """Record an investigation decision and update alert status."""
    if outcome not in VALID_OUTCOMES:
        return None

    now = _now()
    decision_id = str(uuid.uuid4())

    status_map = {
        "escalate": "escalated",
        "close": "closed",
        "needs_further_review": "needs_further_review",
    }
    new_status = status_map[outcome]

    conn = _connect()
    try:
        row = conn.execute(
            "SELECT status FROM investigation_state WHERE alert_id = ?",
            (alert_id,)
        ).fetchone()
        if row is None:
            return None

        previous_status = row["status"]

        conn.execute("""
            INSERT INTO decisions
            (decision_id, alert_id, analyst_id, outcome, rationale, previous_status, decided_at)
            VALUES (?,?,?,?,?,?,?)
        """, (decision_id, alert_id, analyst_id, outcome, rationale, previous_status, now))

        conn.execute("""
            UPDATE investigation_state SET status = ?, updated_at = ?
            WHERE alert_id = ?
        """, (new_status, now, alert_id))

        _write_audit_event(conn, alert_id, "decision_recorded", analyst_id, {
            "decision_id": decision_id,
            "outcome": outcome,
            "previous_status": previous_status,
            "new_status": new_status,
            "rationale_provided": bool(rationale),
        }, now)
        conn.commit()

        return {
            "decision_id": decision_id,
            "alert_id": alert_id,
            "analyst_id": analyst_id,
            "outcome": outcome,
            "rationale": rationale,
            "previous_status": previous_status,
            "new_status": new_status,
            "decided_at": now,
        }
    finally:
        conn.close()


# ------------------------------------------------------------------ #
# Deterministic explainability (no LLM)                               #
# ------------------------------------------------------------------ #

# Population reference statistics derived from simulation training data.
# These thresholds define "notable" behaviour for analyst communication.
# They are deterministic — not inferred from an LLM.
_FEATURE_THRESHOLDS = {
    "f11_cash_fraction_30d":      {"label": "Cash proportion (30-day)",               "high": 0.60, "unit": "%", "scale": 100, "fmt": ".0f"},
    "f12_structuring_count_30d":  {"label": "Structuring transactions (30-day)",       "high": 3,    "unit": "",  "scale": 1,   "fmt": ".0f"},
    "f13_round_amount_count_30d": {"label": "Round-value transactions (30-day)",       "high": 5,    "unit": "",  "scale": 1,   "fmt": ".0f"},
    "f08_velocity_ratio":         {"label": "Transaction velocity ratio (7d/30d)",     "high": 3.0,  "unit": "×", "scale": 1,   "fmt": ".1f"},
    "f03_vol_ratio_7_30":         {"label": "Volume spike ratio (7d vs 30d average)",  "high": 2.5,  "unit": "×", "scale": 1,   "fmt": ".1f"},
    "f16_intl_fraction_30d":      {"label": "International transaction fraction",      "high": 0.50, "unit": "%", "scale": 100, "fmt": ".0f"},
    "f19_shell_counterparty_fraction": {"label": "Shell-entity counterparty fraction","high": 0.10, "unit": "%", "scale": 100, "fmt": ".0f"},
    "f15_night_fraction_30d":     {"label": "Night-time transaction fraction",         "high": 0.40, "unit": "%", "scale": 100, "fmt": ".0f"},
    "f23_prior_alerts_90d":       {"label": "Prior alerts (90-day)",                  "high": 2,    "unit": "",  "scale": 1,   "fmt": ".0f"},
    "f07_txn_count_30d":          {"label": "Transaction count (30-day)",              "high": 40,   "unit": "",  "scale": 1,   "fmt": ".0f"},
    "f17_distinct_jurisdictions_30d": {"label": "Distinct jurisdictions (30-day)",    "high": 3,    "unit": "",  "scale": 1,   "fmt": ".0f"},
    "f18_very_high_jur_flag":     {"label": "High-risk jurisdiction counterparty",    "high": 0.5,  "unit": "",  "scale": 1,   "fmt": ".0f"},
    "f20_pep_flag":               {"label": "Politically Exposed Person flag",        "high": 0.5,  "unit": "",  "scale": 1,   "fmt": ".0f"},
    "f21_adverse_media_flag":     {"label": "Adverse media flag",                     "high": 0.5,  "unit": "",  "scale": 1,   "fmt": ".0f"},
    "f22_high_risk_industry":     {"label": "High-risk industry classification",      "high": 0.5,  "unit": "",  "scale": 1,   "fmt": ".0f"},
}

_FLAG_FEATURES = {"f18_very_high_jur_flag", "f20_pep_flag", "f21_adverse_media_flag", "f22_high_risk_industry"}


def _compute_explainability_signals(
    features: dict[str, float],
    quality_flags: dict[str, Any],
) -> list[dict[str, Any]]:
    """Produce deterministic, analyst-readable signals from feature values.

    Returns a list of signals ordered from most notable to least notable.
    Each signal has:
      - feature: internal feature name
      - label: analyst-readable label
      - value: raw feature value
      - display_value: formatted value with unit
      - notable: whether the value exceeds the notable threshold
      - flag: whether this is a binary flag (shown differently in UI)
    """
    signals = []
    for feat, cfg in _FEATURE_THRESHOLDS.items():
        val = features.get(feat)
        if val is None:
            continue

        is_flag = feat in _FLAG_FEATURES
        notable = bool(val >= cfg["high"]) if not is_flag else bool(val >= 1)

        if is_flag:
            display_val = "Yes" if val >= 1 else "No"
        else:
            scaled = val * cfg["scale"]
            fmt = cfg["fmt"]
            display_val = f"{scaled:{fmt}}{cfg['unit']}"

        signals.append({
            "feature": feat,
            "label": cfg["label"],
            "value": val,
            "display_value": display_val,
            "notable": notable,
            "flag": is_flag,
        })

    # Sort: notable first, then flags, then by value descending within group
    signals.sort(key=lambda s: (not s["notable"], not s["flag"], -s["value"]))
    return signals


# ------------------------------------------------------------------ #
# Internal helpers                                                     #
# ------------------------------------------------------------------ #

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_audit_event(
    conn: sqlite3.Connection,
    alert_id: str,
    event_type: str,
    analyst_id: str,
    details: dict[str, Any],
    occurred_at: str,
) -> None:
    conn.execute("""
        INSERT INTO audit_events (event_id, alert_id, event_type, analyst_id, details_json, occurred_at)
        VALUES (?,?,?,?,?,?)
    """, (str(uuid.uuid4()), alert_id, event_type, analyst_id, json.dumps(details), occurred_at))
