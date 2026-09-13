# AlertIQ — Serving Architecture (Milestone 4)

> **Operating policy** — AlertIQ scores are a *relative alert prioritisation
> indicator* for analyst review only. They are not a compliance determination
> and do not constitute a SAR filing decision. Human analysts review all flagged
> alerts and make all SAR filing decisions.

---

## Table of contents

1. [Overview](#1-overview)
2. [Request lifecycle](#2-request-lifecycle)
3. [Component map](#3-component-map)
4. [Module reference](#4-module-reference)
5. [Capacity-ranking policy](#5-capacity-ranking-policy)
6. [Schema versioning](#6-schema-versioning)
7. [Data quality flags](#7-data-quality-flags)
8. [Model registry](#8-model-registry)
9. [Audit logging](#9-audit-logging)
10. [Security controls](#10-security-controls)
11. [Configuration reference](#11-configuration-reference)
12. [Deployment](#12-deployment)
13. [Running the test suite](#13-running-the-test-suite)
14. [Architecture decision log](#14-architecture-decision-log)

---

## 1. Overview

The AlertIQ serving layer exposes a JSON REST API that accepts 24-feature
financial-alert vectors and returns a **risk score** in \[0, 1\].  The score
represents relative investigative priority — higher scores should be reviewed
first — but it is never interpreted as a binary classification or a compliance
finding.

The stack is intentionally thin:

| Layer | Technology |
|-------|-----------|
| ASGI framework | Starlette 1.0 (no FastAPI overhead) |
| Server | uvicorn (single worker, scale via replicas) |
| Schema validation | Pydantic v2 |
| Inference | scikit-learn HistGradientBoostingClassifier (via `TriageScorer`) |
| Serialisation | joblib + SHA-256 checksum |
| Registry | Lightweight JSON manifest (no MLflow) |
| Audit | Append-only newline-delimited JSON |
| Container | Multi-stage Docker image, non-root user |

---

## 2. Request lifecycle

```
Client
  │
  ▼
PayloadSizeLimitMiddleware          ← rejects >10 MB bodies (413)
  │
RequestIDMiddleware                 ← attaches UUID to request.state + response header
  │
  ▼
Route handler  (/score or /score/batch)
  │
  ├─ Read body → json.loads()
  │
  ├─ Pydantic validation (ScoreRequest / BatchScoreRequest)
  │     • all 24 features present
  │     • domain bounds enforced (fractions ∈ [0,1], binary flags ∈ {0,1}, etc.)
  │     • extra fields rejected
  │     • returns 422 on failure
  │
  ├─ InferenceScorer.score_single() / score_batch()
  │     │
  │     ├─ Schema version validation
  │     │     • unsupported version → SchemaVersionMismatchError → 422
  │     │
  │     ├─ check_data_quality(features)
  │     │     • SHOULD_BE_POSITIVE check (zero flag)
  │     │     • EXTREME_VALUE_THRESHOLDS check (extreme flag)
  │     │     • flags are returned in response; do NOT block inference
  │     │
  │     ├─ AlertFeatures.to_array() → (1, 24) float64 numpy array
  │     │
  │     └─ TriageScorer.score(X) → probability ∈ [0, 1]
  │           (TriageScorer.predict() is NEVER called — see §5)
  │
  ├─ Build ScoreResponse / BatchScoreResponse
  │     • risk_score (float ∈ [0,1])
  │     • operating_mode = "capacity_ranking"
  │     • data_quality_flags
  │     • disclaimer (human-in-the-loop statement)
  │     • NO SAR language, NO binary labels
  │
  ├─ AuditLogger.record_score() / record_batch_score()
  │     • structured JSON record, no raw feature values
  │
  └─ JSONResponse  →  Client
```

---

## 3. Component map

```
alertiq/serving/
├── __init__.py          package init; documents operating policy
├── app.py               Starlette ASGI application, routes, middleware
├── schema.py            Pydantic request / response models; DISCLAIMER constant
├── quality.py           Data quality checks (SHOULD_BE_POSITIVE, thresholds)
├── scorer.py            InferenceScorer; SchemaVersionMismatchError
├── artifact.py          save_artifact / load_artifact; SHA-256 verification
├── registry.py          ModelRegistry; JSON manifest; atomic writes
└── audit.py             AuditLogger; newline-delimited JSON records
```

---

## 4. Module reference

### `app.py` — API application

**Endpoints**

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/health` | Liveness + readiness. `status="ok"` when model loaded; `status="degraded"` otherwise. Always 200. |
| `GET`  | `/model/info` | Model metadata, feature schema, policy statement. 503 if no model. |
| `POST` | `/score` | Score a single alert. Returns `ScoreResponse`. |
| `POST` | `/score/batch` | Score up to 500 alerts. Returns `BatchScoreResponse`. |

**Module-level singletons**

```python
_scorer: InferenceScorer | None   # loaded at startup
_audit:  AuditLogger | None       # opened at startup, closed at shutdown
```

**Middleware (in order)**

1. `PayloadSizeLimitMiddleware` — rejects oversized bodies (HTTP 413)
2. `RequestIDMiddleware` — attaches `X-AlertIQ-Request-ID` UUID header

**Startup / shutdown**

Starlette 1.0 lifecycle is managed by `_lifespan(app)` — an
`asynccontextmanager`.  On startup it:

1. Opens `AuditLogger`
2. Loads model from `ALERTIQ_MODEL_PATH` (direct artifact) or
   `ALERTIQ_REGISTRY_PATH` champion (registry)
3. Sets `_scorer = InferenceScorer(artifact)`

On shutdown it closes the audit log file handle.  If no model is found the
API starts in **degraded mode**: `/health` returns `status="degraded"` and
all scoring endpoints return HTTP 503.

---

### `schema.py` — Request / response schemas

**Feature contract**

`AlertFeatures` is a Pydantic v2 model with `extra="forbid"`.  All 24 fields
are individually typed:

| Type alias | Constraint | Example features |
|------------|-----------|-----------------|
| `LogPosFloat` | `≥ 0.0` | f01, f02, f04 |
| `Fraction` | `[0.0, 1.0]` | f11, f14, f15, f16, f19 |
| `BinaryFlag` | `{0, 1}` | f18, f20, f21, f22 |
| `PosInt` | `≥ 0` | f06, f07, f12, f13, f17, f23 |
| `NonNegFloat` | `≥ 0.0` | f03, f05, f08, f09, f10 |

`AlertFeatures.to_array()` returns features in the canonical order defined by
`TriageConfig.feature_columns` (f01 → f24, positions 0–23).

**DISCLAIMER constant**

```
AlertIQ scores are a relative alert prioritisation indicator for analyst review
only.  They are not a compliance determination and do not constitute a SAR
filing decision.  Human analysts review all flagged alerts.
```

This string is embedded in every `ScoreResponse` and `BatchScoreResponse`.

---

### `quality.py` — Data quality checks

Two sets of thresholds are applied per request.  Flags are **informational
only** — they annotate the response and appear in the audit log but do not
block inference.  A score returned alongside a `quality_warning=True` flag
should be interpreted with additional caution by the downstream analyst
workflow.

**`SHOULD_BE_POSITIVE`** — features that should never be exactly zero in a
valid production alert.  Zero values suggest upstream feature engineering
failures (no activity recorded when there should be):

```python
{"f01_vol_7d_log", "f02_vol_30d_log", "f04_max_txn_log",
 "f06_txn_count_7d", "f07_txn_count_30d", "f10_account_age_days"}
```

**`EXTREME_VALUE_THRESHOLDS`** — upper bounds based on plausible domain
ranges.  Values exceeding the threshold are flagged as extreme:

| Feature | Threshold |
|---------|-----------|
| f01_vol_7d_log | 20.0 |
| f02_vol_30d_log | 23.0 |
| f04_max_txn_log | 18.0 |
| f06_txn_count_7d | 5000 |
| f07_txn_count_30d | 15000 |
| f10_account_age_days | 36500 |

*Motivation*: Milestone 3 stress tests showed that deliberately zeroing
volume features reduced Recall@20% from 0.960 to 0.907 (near the 0.90
acceptance threshold).  The quality layer surfaces this risk without silently
degrading inference.

---

### `scorer.py` — Inference wrapper

`InferenceScorer` wraps a loaded `ModelArtifact`.

```python
score_single(schema_version, features) -> (risk_score, DataQualityFlags, latency_ms)
score_batch(schema_version, features_list) -> (np.ndarray, list[DataQualityFlags], latency_ms)
```

`SchemaVersionMismatchError` is raised (and caught in `app.py` → HTTP 422)
when the client's `schema_version` is not in `SUPPORTED_SCHEMA_VERSIONS` or
does not match the loaded artifact's version.

---

### `artifact.py` — Model serialisation

```python
save_artifact(scorer, config, *, model_version, path, training_rows, notes="") -> Path
load_artifact(path) -> ModelArtifact
```

The `.joblib` file is accompanied by a `.joblib.sha256` sidecar containing
the hex SHA-256 digest.  `load_artifact` verifies the digest before
deserialising — any byte-level corruption or tampering raises `ValueError`.

`ModelArtifact` is a frozen dataclass holding:

- `scorer` — fitted `TriageScorer`
- `feature_columns` — canonical feature name tuple
- `schema_version` — int (currently 1)
- `model_version` — semver string
- `trained_at` — ISO-8601 UTC timestamp
- `training_rows` — int
- `best_iter` — early-stopping iteration from phase 1
- `threshold` — F1-optimal classification threshold (supplementary; not used in
  capacity-ranking mode)
- `operating_mode` — always `"capacity_ranking"`
- `notes` — free-text provenance string

---

### `registry.py` — Model version registry

`ModelRegistry(root)` manages a JSON manifest (`registry.json`) in `root/`.

```python
registry.register(scorer, config, *, model_version, training_rows,
                  notes="", promote_to_champion=False) -> Path
registry.get_champion() -> ModelArtifact   # raises LookupError if none
registry.get_version(model_version)        # raises LookupError if not found
registry.promote(model_version)            # raises LookupError if not found
registry.list_versions() -> list[dict]
```

**Atomic writes**: the manifest is written to a temporary file (`registry.json.tmp`)
then `os.replace()`d into place.  A crash mid-write leaves the old manifest
intact.

**Artifact naming**: `{model_version}.joblib` under `root/`.

---

### `audit.py` — Audit logger

Controlled by `ALERTIQ_AUDIT_LOG_PATH`:

| Value | Destination |
|-------|------------|
| `"-"` | stdout |
| `"path/to/audit.jsonl"` | append-only file |
| *(unset)* | Python `logging` at INFO level |

**Audit record fields (single-score event)**

```json
{
  "event":            "score",
  "request_id":       "uuid4",
  "alert_id":         "ALT-001",
  "batch_id":         null,
  "model_version":    "1.0.0",
  "schema_version":   1,
  "scored_at":        "2026-01-01T12:00:00+00:00",
  "operating_mode":   "capacity_ranking",
  "risk_score":       0.712341,
  "quality_warning":  false,
  "zero_features":    [],
  "extreme_features": [],
  "status":           "scored",
  "error":            null,
  "latency_ms":       3.241
}
```

**Raw feature values are never logged** — they may contain sensitive
financial transaction data.

---

## 5. Capacity-ranking policy

The AlertIQ model was evaluated across walk-forward validation windows.  The
F1-optimal classification threshold ranged from **0.056 to 0.253** across
windows (range = 0.198).  Hard-coding any single threshold would produce
unreliable binary outputs as the score distribution shifts with portfolio
changes.

Therefore:

- `InferenceScorer` calls **`TriageScorer.score(X)`** exclusively.
- **`TriageScorer.predict(X)` is never called** from the serving layer.
- The raw probability estimate from `predict_proba` (clamped to \[0, 1\]) is
  the API output.
- Downstream analyst systems are expected to rank alerts by `risk_score`
  descending and review the top-K per available analyst capacity.

This is enforced and verified by `tests/serving/test_scorer.py::
TestScoreSingle::test_score_method_called_not_predict`.

---

## 6. Schema versioning

`SUPPORTED_SCHEMA_VERSIONS = frozenset({1})` (schema.py)

Every `ScoreRequest` and `BatchScoreRequest` carries an integer
`schema_version`.  If the version is not in `SUPPORTED_SCHEMA_VERSIONS`,
the API returns HTTP 422 immediately — no silent downgrade.

When the feature contract changes (e.g. a new feature is added), the schema
version is incremented and the artifact stores its version.  Old clients
must update before they can score against a new artifact.

---

## 7. Data quality flags

`DataQualityFlags` is embedded in every `ScoreResponse`:

```json
{
  "has_zeroed_features": false,
  "zero_feature_names":  [],
  "has_extreme_values":  false,
  "extreme_feature_names": [],
  "quality_warning":     false
}
```

A `quality_warning=true` response should trigger a review of the upstream
feature pipeline.  The score is still returned and can still be used, but
the analyst workflow should weight it accordingly.

---

## 8. Model registry

The registry is a flat directory structure:

```
models/
├── registry.json          ← manifest (atomic write)
├── 1.0.0.joblib           ← artifact
├── 1.0.0.joblib.sha256    ← SHA-256 sidecar
├── 1.1.0.joblib
└── 1.1.0.joblib.sha256
```

**Promoting a new champion**

```bash
python scripts/train_and_serialize.py \
    --version 1.1.0 \
    --promote \
    --registry-path models/ \
    --notes "Re-trained on Q4 data"
```

Then restart the API container (or trigger a rolling restart) to load the
new champion.  The API does not hot-reload models.

---

## 9. Audit logging

**Container deployments** — set `ALERTIQ_AUDIT_LOG_PATH=-` to emit records
to stdout, then collect with your container logging driver (CloudWatch Logs,
Datadog Agent, Fluentd, etc.).

**File deployments** — set `ALERTIQ_AUDIT_LOG_PATH=/var/log/alertiq/audit.jsonl`
and configure logrotate.  The AuditLogger opens the file in append mode with
`buffering=1` (line-buffered).

**SIEM integration** — the newline-delimited JSON format is directly
consumable by Splunk, Elastic, and most SIEMs.  Key fields for alert
correlation: `request_id`, `alert_id`, `model_version`, `scored_at`.

---

## 10. Security controls

| Control | Implementation |
|---------|---------------|
| No raw features in logs | `AuditLogger` records only metadata |
| No arbitrary model paths | Only `ALERTIQ_MODEL_PATH` or `ALERTIQ_REGISTRY_PATH` env vars accepted |
| Checksum verification | SHA-256 verified on every `load_artifact()` call |
| Payload size limit | `PayloadSizeLimitMiddleware` (default 10 MB) |
| Input validation | Pydantic v2 with per-field bounds; `extra="forbid"` |
| No retrain on request | Model is immutable after startup |
| Non-root container | `USER alertiq` (UID 1001) in Dockerfile |
| Schema version enforcement | Mismatched version → HTTP 422, never silent downgrade |
| No SAR language in responses | `disclaimer` field; no binary labels |

---

## 11. Configuration reference

| Environment variable | Default | Description |
|---------------------|---------|-------------|
| `ALERTIQ_MODEL_PATH` | *(unset)* | Absolute path to a specific `.joblib` artifact. Overrides registry. |
| `ALERTIQ_REGISTRY_PATH` | `models/` | Path to the model registry directory. Champion model is loaded. |
| `ALERTIQ_AUDIT_LOG_PATH` | *(unset → Python logging)* | `"-"` for stdout; a file path for append-only JSONL. |
| `ALERTIQ_MAX_PAYLOAD_BYTES` | `10485760` (10 MB) | Maximum request body size in bytes. |

---

## 12. Deployment

### Local development

```bash
# Train and register a model first
python scripts/train_and_serialize.py \
    --version 0.1.0-dev \
    --promote \
    --registry-path models/

# Start the API
ALERTIQ_REGISTRY_PATH=models/ \
ALERTIQ_AUDIT_LOG_PATH=- \
uvicorn alertiq.serving.app:app --host 0.0.0.0 --port 8080 --reload
```

### Docker

```bash
# Build
docker build -t alertiq-api:latest .

# Run (bind-mount a pre-populated registry)
docker run -p 8080:8080 \
  -v /path/to/registry:/models:ro \
  -e ALERTIQ_REGISTRY_PATH=/models \
  -e ALERTIQ_AUDIT_LOG_PATH=- \
  alertiq-api:latest
```

### Scale-out

The application is **stateless after startup** (the model is loaded into
process memory once, then all requests are read-only).  Scale horizontally
by running multiple container replicas behind a load balancer.  Each replica
loads its own copy of the model from the shared (read-only) registry mount.

Avoid multiple uvicorn workers within a single container — each worker would
load a separate model copy, wasting memory.  Use replicas instead.

### Health check

```bash
curl -s http://localhost:8080/health | python -m json.tool
```

Expected response when ready:

```json
{
  "status": "ok",
  "model_loaded": true,
  "model_version": "1.0.0",
  "schema_version": 1,
  "checked_at": "2026-01-01T12:00:00+00:00"
}
```

---

## 13. Running the test suite

```bash
# All serving tests (158 tests as of M4)
python -m pytest tests/serving/ -v

# Individual test modules
python -m pytest tests/serving/test_artifact.py   # serialisation (21 tests)
python -m pytest tests/serving/test_registry.py   # registry (17 tests)
python -m pytest tests/serving/test_schema.py     # schema validation (19 tests)
python -m pytest tests/serving/test_quality.py    # data quality (17 tests)
python -m pytest tests/serving/test_scorer.py     # InferenceScorer (31 tests)
python -m pytest tests/serving/test_api.py        # API endpoints (53 tests)
```

Tests use only the installed packages (no external services, no network).
The `test_client` fixture patches the module-level singletons directly, so
no environment variables are needed to run the test suite.

---

## 14. Architecture decision log

### ADR-M4-01: Starlette instead of FastAPI

**Context**: The execution environment does not have access to PyPI (egress
policy blocks `pypi.org`).  FastAPI was not pre-installed.

**Decision**: Use Starlette 1.0 directly.  FastAPI is a thin wrapper over
Starlette; the API contract is identical.  JSON serialisation, routing,
middleware, and error handling are all available in Starlette itself.

**Trade-off**: No automatic OpenAPI / Swagger UI generation.  Acceptable at
this milestone — the schema is documented here and in `schema.py` docstrings.

---

### ADR-M4-02: Lightweight JSON registry instead of MLflow

**Context**: MLflow was considered for model lifecycle management.

**Decision**: Implement a lightweight JSON-manifest registry (`registry.py`).
MLflow introduces a PostgreSQL or SQLite backend, a tracking server process,
and additional Python dependencies — none of which are justified for a single
model serving a single schema version.

**Trade-off**: No experiment tracking or metrics history in the registry.
Those concerns belong to the training pipeline (Milestone 3), not the serving
layer.  If model count grows beyond ~50 versions, migrating to a proper model
store would be appropriate.

---

### ADR-M4-03: Single uvicorn worker, scale via replicas

**Context**: uvicorn supports `--workers N` for multi-process serving.

**Decision**: Use `--workers 1`.  The model artifact (~10–50 MB) is loaded
into process memory at startup.  Multiple workers would each load a separate
copy, multiplying memory use for no throughput benefit (the model inference
itself is CPU-bound, not I/O-bound, so async workers don't help).

**Trade-off**: A container restart is required to roll out a new model
version.  This is acceptable — champion promotion is a deliberate, supervised
action, not a hot-path operation.

---

### ADR-M4-04: Capacity-ranking, no fixed threshold

**Context**: M3 walk-forward evaluation showed threshold instability (0.056 –
0.253 range across windows).

**Decision**: The API returns `risk_score ∈ [0, 1]` only.  No binary
label is derived.  `TriageScorer.predict()` is never called.

**Trade-off**: Downstream analyst systems must implement their own ranking /
review-queue logic.  This is correct — the appropriate threshold depends on
analyst headcount and regulatory review-rate targets, which the model cannot
know.

---

### ADR-M4-05: No retraining during scoring

**Constraint**: The model must not be retrained during API startup or during
request handling.

**Reason**: Online retraining would make scoring non-deterministic, could
degrade the model if triggered on adversarial inputs, and would make audit
records non-reproducible.  Model updates are handled off-path by
`train_and_serialize.py` and require a container restart.
