# AlertIQ  -  Persistence Architecture & InvestigationRepository Design

**Document type:** Architecture decision record + design specification  
**Milestone:** M6.1 Investigation Integrity Hardening  
**Created:** 2026-09-13

---

## 1. Current State

The investigation store is implemented as a module of procedural functions in `src/alertiq/serving/alert_store.py`. It uses **SQLite WAL** as the backing engine, accessed via a connection factory (`_connect()`).

### Tables

| Table | Type | Purpose |
|-------|------|---------|
| `alerts` | Immutable-after-create | Scored alert record; model risk score, features, explainability snapshot |
| `investigation_state` | Mutable | Analyst workflow state (status, assigned_to) |
| `notes` | Append-only | Free-text investigation notes |
| `decisions` | Append-only | Recorded analyst decisions (escalate/close/needs_further_review) |
| `audit_events` | Append-only | System-level audit trail (opens, status changes, decision timestamps) |
| `transactions` | Immutable-after-create | Pre-alert transaction history for each account |

### Public API (current)

| Function | Operation |
|----------|-----------|
| `init_db()` | DDL  -  create tables |
| `upsert_alert(...)` | Write scored alert |
| `upsert_transaction(...)` | Write transaction record |
| `get_queue_stats()` | Aggregate capacity/status stats |
| `list_alerts(...)` | Paginated, filtered alert list |
| `get_alert(alert_id)` | Full alert detail + explainability |
| `get_alert_transactions(alert_id)` | Pre-alert transaction history (temporal filter enforced) |
| `get_alert_history(alert_id)` | Audit trail |
| `get_alert_notes(alert_id)` | Investigation notes |
| `get_alert_decisions(alert_id)` | Recorded decisions |
| `open_alert(alert_id, analyst_id)` | State transition: new → in_progress |
| `add_note(alert_id, analyst_id, content)` | Append note |
| `record_decision(alert_id, analyst_id, ...)` | Append decision; update state |

---

## 2. Deployment Label

> **⚠️ DEVELOPMENT / DEMO DEPLOYMENT ONLY**
>
> The current SQLite-based persistence is suitable for a portfolio demonstration on a single server with a single analyst. It is **not** suitable for production AML use. See Section 4 for production requirements.

This label must appear in:
- The module docstring in `alert_store.py` (already present as a prose note)
- The `DEPLOYMENT.md` operations section
- The `MILESTONE_6_1_COMPLETION.md` known limitations

---

## 3. Cloud Run Limitation

AlertIQ's CD pipeline deploys to Google Cloud Run. Cloud Run containers:

1. **Have no persistent local disk.** The SQLite file (`data/alert_store.db`) lives on the container's ephemeral filesystem. When a new revision is deployed, the database is wiped.
2. **Scale horizontally.** Under load, Cloud Run may spin up multiple container instances. SQLite WAL supports concurrent reads but a single writer. Multiple writer instances would corrupt the database.
3. **Cannot guarantee availability.** Cloud Run scales to zero after periods of inactivity, destroying the SQLite state.

**Consequence for the demo:** The investigation store must be re-seeded (`python scripts/seed_alert_store.py`) after every deployment. Analyst decisions made in one session are lost when the container is replaced.

**This is acceptable for a portfolio demo** because:
- No real analyst decisions are being made
- The seed script is idempotent and fast (~10 seconds)
- The limitation is explicitly documented

---

## 4. InvestigationRepository: Interface Design

To make the persistence layer production-upgradeable, the store should be refactored behind a repository interface. The following design requires **no changes to any route handler**  -  only the interface implementation changes.

```python
# src/alertiq/serving/repository.py
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any

class InvestigationRepository(ABC):
    """
    Abstract persistence boundary for the AlertIQ investigation workspace.

    All methods that can fail due to a missing alert return None rather than
    raising  -  route handlers treat None as HTTP 404.

    Implementations must preserve these invariants:
    - Scored alert records are immutable after create (upsert is idempotent for
      the same alert_id; risk_score and model metadata are never modified by
      investigation actions).
    - Notes and audit_events are append-only; no delete or update is exposed.
    - true_sar is never returned by any read method.
    """

    @abstractmethod
    def init(self) -> None:
        """Initialise storage (create tables, apply migrations)."""

    # --- Write ---

    @abstractmethod
    def upsert_alert(self, alert_id: str, **kwargs: Any) -> None:
        """Idempotent write of a scored alert record."""

    @abstractmethod
    def upsert_transaction(self, txn_id: str, **kwargs: Any) -> None:
        """Idempotent write of a transaction record."""

    @abstractmethod
    def open_alert(self, alert_id: str, analyst_id: str) -> bool:
        """Transition alert to in_progress. Returns False if alert not found."""

    @abstractmethod
    def add_note(self, alert_id: str, analyst_id: str, content: str) -> dict[str, Any] | None:
        """Append a note. Returns the note record or None if alert not found."""

    @abstractmethod
    def record_decision(
        self,
        alert_id: str,
        analyst_id: str,
        decision: str,
        rationale: str,
    ) -> dict[str, Any] | None:
        """Append a decision. Returns the decision record or None if alert not found."""

    # --- Read ---

    @abstractmethod
    def get_queue_stats(self) -> dict[str, Any]:
        """Capacity band statistics and status counts."""

    @abstractmethod
    def list_alerts(self, **filters: Any) -> dict[str, Any]:
        """Paginated, filtered alert list."""

    @abstractmethod
    def get_alert(self, alert_id: str) -> dict[str, Any] | None:
        """Full alert detail with features and explainability. None if not found."""

    @abstractmethod
    def get_alert_transactions(self, alert_id: str, limit: int = 100) -> list[dict[str, Any]]:
        """Pre-alert transactions (temporal filter: txn_date <= alert_date)."""

    @abstractmethod
    def get_alert_history(self, alert_id: str) -> list[dict[str, Any]]:
        """Audit event trail."""

    @abstractmethod
    def get_alert_notes(self, alert_id: str) -> list[dict[str, Any]]:
        """Investigation notes in chronological order."""

    @abstractmethod
    def get_alert_decisions(self, alert_id: str) -> list[dict[str, Any]]:
        """Recorded decisions in chronological order."""
```

### 4.1 SQLiteInvestigationRepository (current)

The current `alert_store.py` functions become the body of `SQLiteInvestigationRepository`, which implements the above interface. This is a refactoring task (no behaviour change).

```python
class SQLiteInvestigationRepository(InvestigationRepository):
    """SQLite WAL implementation  -  suitable for single-server demo only."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or os.environ.get("ALERTIQ_DB_PATH", "data/alert_store.db")

    # ... delegate to existing alert_store functions
```

### 4.2 PostgreSQLInvestigationRepository (production path)

For production, replace with a PostgreSQL implementation using the same interface:

```python
class PostgreSQLInvestigationRepository(InvestigationRepository):
    """
    PostgreSQL implementation for production AML deployment.

    Requires:
    - ALERTIQ_DB_URL environment variable (PostgreSQL DSN)
    - Database schema migration (Alembic recommended)
    - Row-level locking for state transitions
    - Encryption-at-rest for the notes and decisions tables (PII)
    - Audit table as immutable append-only (Postgres: INSERT only, no UPDATE/DELETE grants)
    - Connection pooling (psycopg3 + asyncpg for async routes)
    """
    ...
```

---

## 5. Smallest Defensible Production Path

For production AML deployment, the minimum viable storage upgrade from the current state is:

| Step | Action | Why |
|------|--------|-----|
| **1. Move to Cloud SQL (PostgreSQL)** | Replace SQLite file with a managed PostgreSQL instance | Durable, concurrent-write safe, Cloud Run compatible |
| **2. Mount Cloud SQL via Unix socket** | Cloud SQL Auth Proxy (sidecar or Cloud Run native connector) | Zero-credential connection from Cloud Run |
| **3. Add Alembic migrations** | Replace `CREATE TABLE IF NOT EXISTS` with versioned migrations | Allows schema evolution without data loss |
| **4. Encrypt PII columns** | `notes.content` and `decisions.rationale` encrypted at column level | Analyst investigation notes contain PII by nature |
| **5. Revoke UPDATE/DELETE on audit tables** | Postgres GRANT INSERT-only on `audit_events` | Immutable audit trail, even for privileged users |
| **6. Add analyst authentication** | Replace hardcoded `analyst-001` with JWT/OAuth2 identity | Required for any real analyst accountability |
| **7. Implement InvestigationRepository interface** | Route handlers reference the interface; swap implementations via DI | No route code changes needed when switching backends |

**Estimated engineering effort:** 2–3 days for a developer already familiar with the codebase.

---

## 6. Decision Record

| Decision | Rationale |
|----------|-----------|
| SQLite for M6/M6.1 | Single file, zero infrastructure, sufficient for one-analyst portfolio demo |
| WAL mode | Allows concurrent reads during the investigation session |
| No InvestigationRepository interface in M6 | Out-of-scope for milestone; procedural functions are simpler and sufficient for a single implementation |
| Interface designed in M6.1 (not implemented) | Documents the production upgrade path without gold-plating the demo |
| PostgreSQL as production target | Managed, durable, supports row-level security, Cloud SQL connects natively to Cloud Run |

---

*This document supersedes the informal SQLite notes in `alert_store.py`. When the InvestigationRepository interface is implemented, update this document to reflect the active implementation.*
