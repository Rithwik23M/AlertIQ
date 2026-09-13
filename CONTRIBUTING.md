# Contributing to AlertIQ

Thank you for your interest in AlertIQ. This document explains how to set up a development environment, the branching and commit conventions, testing requirements, and the pull request process.

---

## Development Setup

### Prerequisites

- Python 3.11 or later
- Node.js 18 or later (frontend only)
- Git

### Backend

```bash
# Clone and enter the repository
git clone https://github.com/rithwikm7/alertiq.git
cd alertiq

# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate

# Install the package in editable mode with dev dependencies
pip install -e ".[dev]"

# Verify the installation
pytest --collect-only | tail -5
```

### Frontend

```bash
cd ui
npm install
npm run dev          # Development server at http://localhost:3000
npm run build        # Production build
npm run lint         # ESLint
```

### Environment Variables

Copy `.env.example` to `.env` and fill in required values. Required for local development:

```
ALERTIQ_STORE_PATH=data/alert_store.db
ALERTIQ_MODEL_REGISTRY=models/registry.json
ALERTIQ_LOG_LEVEL=INFO
```

---

## Branching Convention

| Branch | Purpose |
|---|---|
| `main` | Stable, deployable code. Merges require passing CI. |
| `feat/<short-description>` | New feature work |
| `fix/<short-description>` | Bug fixes |
| `docs/<short-description>` | Documentation-only changes |
| `refactor/<short-description>` | Refactoring with no behaviour change |
| `test/<short-description>` | Test additions without source changes |

Keep branches short-lived. Rebase onto `main` before opening a PR.

---

## Code Style

AlertIQ uses **ruff** for linting and **black** for formatting. Both are enforced in CI.

```bash
# Format
black src/ tests/ scripts/

# Lint
ruff check src/ tests/ scripts/

# Type check
mypy src/alertiq/

# All in one pass
black src/ tests/ scripts/ && ruff check src/ tests/ scripts/ && mypy src/alertiq/
```

Configuration is in `pyproject.toml`. Do not bypass linting with `# noqa` or `# type: ignore` unless the suppression includes a comment explaining why.

---

## Testing Requirements

Tests live in `tests/` and are run with pytest.

```bash
# Full test suite (excluding integration tests)
pytest

# With coverage — must stay above 70%
pytest --cov=alertiq --cov-report=term-missing

# Integration tests (require data/simulation/alerts.csv)
pytest -m integration -v

# Single module
pytest tests/serving/ -v
```

### Rules for new tests

1. Every new source function must have at least one corresponding test.
2. API route changes require updates to `tests/serving/test_api.py`.
3. Any change to the serving layer that could affect temporal evidence integrity must be accompanied by a test in `tests/serving/test_temporal_integrity.py`.
4. Do not add `# type: ignore` to silence test failures.
5. Integration tests that require real data must be decorated with `@pytest.mark.integration` and guarded with a `skipif` on the data file's existence.

---

## Data and Model Artefacts

- **Never commit real customer data.** All data must be synthetic.
- **Never commit model weights to version history** unless they fit in `models/` with a corresponding registry entry and SHA-256 verification file.
- **Never change `data/simulation/alerts.csv` without updating `DATA_PROVENANCE.md`** and the SHA-256 constant in `tests/triage/test_integration_real_data.py`.
- **Never expose `true_sar` via any API endpoint.** This is a security control.
- **Never forward analyst notes to any external service.** This is a security control.

---

## Pull Request Requirements

Before opening a PR:

1. All tests pass (`pytest`).
2. Coverage is at or above 70% (`pytest --cov=alertiq --cov-fail-under=70`).
3. Linting passes (`ruff check src/ tests/`).
4. Formatting is clean (`black --check src/ tests/`).
5. The PR description explains **what** changed and **why**, not just **how**.
6. If the change affects data, model, or temporal integrity controls, the PR description must include an explicit security review note.

PRs are squash-merged into `main`. Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/) style:

```
feat: add jurisdiction entropy feature to triage config
fix: restore temporal filter in get_alert_transactions
docs: update DATA_PROVENANCE for alerts.csv v3
refactor: extract InvestigationRepository ABC
test: add temporal integrity E2E journey tests
```

---

## Reporting Issues

Use GitHub Issues. Include:

- **What you expected** to happen
- **What actually happened** (error message, log output)
- **Steps to reproduce**
- Python version, OS

For security issues, see [SECURITY.md](SECURITY.md).
