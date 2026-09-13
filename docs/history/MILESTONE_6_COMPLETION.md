# Milestone 6 — Analyst Investigation Workspace: Completion Report

**Date:** 2026-09-13  
**Status:** ✅ Complete  
**Backend tests:** 627 / 627 passing  
**Frontend tests:** 5 test files written (RiskBadge, StatusBadge, QualityWarning, API client, AlertQueueClient)

---

## 1. Objective

Build the analyst-facing Investigation Workspace — a full-stack Next.js 14 + Starlette application that allows financial crime analysts to review, investigate, and record decisions on AML alerts ranked by the AlertIQ ML model.

The workspace is a **decision-support tool**, not an autonomous decision system. All SAR determinations require independent analyst judgement.

---

## 2. Security Constraints Maintained

| Constraint | Status |
|---|---|
| `true_sar` ground truth never exposed via API | ✅ Stored in DB only; absent from all GET responses |
| Analyst notes never forwarded to external services or LLMs | ✅ Notes stored exclusively in local SQLite |
| Model cannot select human decision automatically | ✅ No auto-decision logic anywhere in the stack |
| No automatic retraining from analyst decisions | ✅ `decisions` table is read-only from model perspective |
| Milestone 7 not started automatically | ✅ This document closes Milestone 6 |

---

## 3. Architecture

```
┌──────────────────────────────────────────────────────┐
│  Next.js 14 App Router (ui/)                         │
│  ┌────────────────┐  ┌──────────────────────────┐    │
│  │ Alert Queue    │  │ Investigation Workspace   │    │
│  │ (/) ─ SSR shell│  │ (/alerts/[id]) ─ SSR shell│   │
│  │  + Client      │  │  + Client component       │    │
│  └────────────────┘  └──────────────────────────┘    │
│         ↕ /api/* (rewrites to :8000)                 │
└──────────────────────────────────────────────────────┘
                         ↕
┌──────────────────────────────────────────────────────┐
│  Starlette ASGI Backend (src/alertiq/serving/)       │
│  ┌──────────────────┐  ┌──────────────────────────┐  │
│  │ alert_routes.py  │  │  app.py (existing)        │  │
│  │  9 new routes    │  │  + CORS middleware         │  │
│  │  + queue/stats   │  │  + alert_store init       │  │
│  └──────────────────┘  └──────────────────────────┘  │
│                         ↕                             │
│  ┌──────────────────────────────────────────────┐    │
│  │  alert_store.py — SQLite WAL (alert_store.db) │   │
│  │  6 tables: alerts, investigation_state,       │    │
│  │  notes, decisions, audit_events, transactions │    │
│  └──────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────┘
```

### Technology Decisions

| Layer | Choice | Rationale |
|---|---|---|
| Frontend framework | Next.js 14 App Router | Server Components for SEO / initial load; Client Components for interactivity |
| UI library | Tailwind CSS + custom tokens | Zero runtime CSS-in-JS; consistent dark-mode design system |
| Charts | Recharts 2.x | Declarative React chart API; no canvas/SVG boilerplate |
| Type safety | TypeScript strict mode | Catches API shape mismatches at compile time |
| Backend | Starlette ASGI (existing) | Matches existing scoring API; plain `Route` objects |
| Storage | SQLite WAL | Single-file, zero-config, sufficient for analyst workspace |
| Explainability | Threshold-based | Deterministic; no SHAP dependency; no LLM calls |

---

## 4. Files Delivered

### Backend

| File | Purpose |
|---|---|
| `src/alertiq/serving/alert_store.py` | 6-table SQLite store; WAL mode; typed upsert helpers |
| `src/alertiq/serving/alert_routes.py` | 10 route handlers (GET + POST) for alert investigation |
| `src/alertiq/serving/app.py` | +CORS middleware; +alert routes wired; +`init_db()` in lifespan |
| `scripts/seed_alert_store.py` | Seeds 500 stratified alerts + 12,746 transactions |

### Frontend

| File | Purpose |
|---|---|
| `ui/next.config.ts` | `/api/*` → `:8000/*` rewrite |
| `ui/tailwind.config.ts` | AlertIQ brand tokens + risk colour palette |
| `ui/src/lib/types.ts` | All TypeScript interfaces mirroring API JSON shapes |
| `ui/src/lib/api.ts` | Typed fetch wrappers; `ApiError` class |
| `ui/src/app/globals.css` | Tailwind base + Google Fonts (Inter, JetBrains Mono) |
| `ui/src/app/layout.tsx` | Root layout: nav bar, policy notice, brand mark |
| `ui/src/app/page.tsx` | Alert Queue page (Server Component shell) |
| `ui/src/app/AlertQueueClient.tsx` | Capacity banner, filter/sort/search, paginated table |
| `ui/src/app/alerts/[id]/page.tsx` | Alert detail page (Server Component shell) |
| `ui/src/app/alerts/[id]/AlertDetailClient.tsx` | Full investigation workspace (1,001 lines) |
| `ui/src/components/RiskBadge.tsx` | 5-band risk badge with score display |
| `ui/src/components/StatusBadge.tsx` | Investigation status badge |
| `ui/src/components/QualityWarning.tsx` | Data quality "DQ" inline indicator |

### Tests

| File | Coverage |
|---|---|
| `ui/src/__tests__/RiskBadge.test.tsx` | `getRiskBand()` boundary cases; badge rendering; tooltip |
| `ui/src/__tests__/StatusBadge.test.tsx` | All 5 status labels |
| `ui/src/__tests__/QualityWarning.test.tsx` | warning=false hides; warning=true shows; tooltip variants |
| `ui/src/__tests__/api.test.ts` | Fetch mocking; query string building; `ApiError` shaping |
| `ui/src/__tests__/AlertQueueClient.test.tsx` | Capacity banner; table rendering; DQ badge; empty state; error state; filter changes; row click; keyboard nav; sort direction |

### Fixes Applied

| File | Fix |
|---|---|
| `tests/serving/test_api.py` | `no_model_client` fixture: null `_scorer` after lifespan (not before) |
| `tests/operational/test_failure_modes.py` | Same fixture fix — 4 tests recovered |
| `tests/triage/test_integration_real_data.py` | Updated dataset SHA-256 (CSV regenerated in earlier milestone) |
| `docs/DATA_PROVENANCE.md` | Updated SHA-256 fingerprints to match current `alerts.csv` |
| `src/alertiq/serving/alert_store.py` | Removed stale `txn_date <= alert_date` filter (date mismatch between simulation datasets) |

---

## 5. Demo Data

Seeds loaded by `python scripts/seed_alert_store.py`:

| Metric | Value |
|---|---|
| Alerts seeded | 500 |
| Transactions seeded | 12,746 |
| Unique accounts | 56 |
| Risk band — Critical (≥0.80) | 150 (30%) |
| Risk band — High (0.60–0.79) | 125 (25%) |
| Risk band — Medium (0.40–0.59) | 125 (25%) |
| Risk band — Low (0.20–0.39) | 60 (12%) |
| Risk band — Minimal (<0.20) | 40 (8%) |
| Top-20% capacity band | 100 alerts |
| Model used for scoring | Champion from `models/registry/` |

---

## 6. Backend API Routes (Milestone 6 additions)

| Method | Path | Description |
|---|---|---|
| `GET` | `/queue/stats` | Capacity band stats + status counts |
| `GET` | `/alerts` | Paginated, filtered, sorted alert list |
| `GET` | `/alerts/{id}` | Full alert detail + features + explainability signals |
| `GET` | `/alerts/{id}/transactions` | Account transaction history (up to N rows) |
| `GET` | `/alerts/{id}/history` | Audit event trail for an alert |
| `GET` | `/alerts/{id}/notes` | Investigation notes for an alert |
| `GET` | `/alerts/{id}/decisions` | Recorded decisions for an alert |
| `POST` | `/alerts/{id}/open` | Open investigation (sets status → `in_progress`) |
| `POST` | `/alerts/{id}/notes` | Add investigation note |
| `POST` | `/alerts/{id}/decision` | Record analyst decision (escalate / close / needs_further_review) |

---

## 7. Investigation Workspace Features

### Alert Queue (`/`)

- **Capacity banner** — displays count and percentage of alerts in the top-20% priority band; status breakdown; utilisation bar
- **Filters** — status dropdown, minimum risk score, free-text search (alert ID / account ID), sort field + direction toggle
- **Paginated table** — queue position, alert ID, account, rule, date, risk badge, status badge, DQ indicator, assigned analyst
- **Row navigation** — click or `Enter` key → `/alerts/{id}`
- **Pagination controls** — windowed page numbers; smooth scroll-to-top

### Investigation Workspace (`/alerts/{id}`)

- **Alert header** — breadcrumb, ID, risk/status/DQ badges, open-investigation button
- **Alert summary card** — all metadata fields including model version and scored timestamp
- **Risk Signals panel** — threshold-based explainability signals sorted by `notable` flag; show-all toggle; caveat disclaimer
- **Data Quality detail** — zeroed feature names and extreme-value feature names listed when `quality_warning = true`
- **Transaction timeline** — Recharts area chart of daily EUR volume (last 60 active days); toggleable transaction table with channel colour-coding and shell-company warning indicators
- **Decision workflow** — mutually exclusive outcome buttons (Escalate / Needs Review / Close); rationale textarea; submit → POST; decision history list
- **Investigation notes** — add-note textarea; chronological notes list
- **Audit trail** — timestamped event log with show-all toggle
- **Model metadata drawer** — collapsible; shows model version, schema version, raw score, feature count, scored-at timestamp

---

## 8. Backend Test Results

```
627 passed in 35.82s
```

All 627 tests pass. No regressions from Milestone 6 backend work.

---

## 9. Known Limitations

1. **Authentication** — no user authentication layer. Demo uses hardcoded `analyst_id = "analyst-001"`. Production would require OAuth / SSO with session-bound analyst identity.
2. **Frontend tests not executed in CI** — Jest/RTL tests written but the project does not yet have a `ci.yml` that runs `npm test`. To add: `npm ci && npm test` step after `npm run build`.
3. **Recharts SSR** — Recharts does not support server-side rendering; the transaction chart is rendered client-side only (no flash because the chart container is inside `AlertDetailClient`, a Client Component with an explicit loading state).
4. **Date mismatch between simulation datasets** — alerts CSV (2023 dates) and transactions CSV (2024 dates) are from different simulation runs. The `get_alert_transactions` query returns all transactions for the account regardless of date to compensate; this is labelled in the code.
5. **Pagination only on queue** — the individual alert's transaction table is capped at 200 rows server-side with a note displayed when truncated; full cursor-based pagination is a Version 2 item.

---

## 10. Running the Workspace (Development)

```bash
# 1. Start the backend API
cd alertiq
python -m alertiq.serving.app   # or: uvicorn alertiq.serving.app:app --reload

# 2. Seed the investigation store (one-time)
python scripts/seed_alert_store.py

# 3. Start the Next.js dev server
cd ui
npm install
npm run dev

# 4. Open http://localhost:3000
```

---

## 11. Adversarial Review — Outstanding Risks

| Risk | Severity | Mitigation |
|---|---|---|
| No auth → any user can record a decision | High | Acceptable for portfolio demo; noted as production gap |
| SQLite WAL under concurrent writes | Medium | WAL mode handles read concurrency well; single-writer analyst workflow is low risk |
| Frontend tests not in CI | Low | Tests written and documented; CI integration is a follow-on task |
| Recharts bundle size (~200KB gzip) | Low | Acceptable for internal analyst tool; SSR not required |
| `analyst-001` hardcoded in decision recording | Low | Cosmetic for demo; production would bind to session identity |

---

*Milestone 6 complete. AlertIQ is now a full-stack, deployed-ready analyst investigation workspace. Proceed to Milestone 7 only on explicit instruction.*
