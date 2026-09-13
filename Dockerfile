# ============================================================================ #
# AlertIQ — AML Alert Triage Engine  ·  Scoring API
# ============================================================================ #
#
# Multi-stage build:
#   builder  — installs Python deps into a virtual env under /opt/venv
#   runtime  — lean image that copies /opt/venv + package source only
#
# Serving layer: Starlette 1.0 + uvicorn (ASGI, async)
#
# Environment variables (all optional at build time; required at runtime
# if you want inference to work):
#
#   ALERTIQ_MODEL_PATH        Absolute path to a specific .joblib artifact.
#                             Takes precedence over ALERTIQ_REGISTRY_PATH.
#
#   ALERTIQ_REGISTRY_PATH     Path to the model registry directory.
#                             Default: /models  (bind-mount your registry here)
#
#   ALERTIQ_AUDIT_LOG_PATH    Destination for structured JSON audit records.
#                             "-" → stdout  |  unset → Python logging
#
#   ALERTIQ_MAX_PAYLOAD_BYTES Maximum request body in bytes. Default: 10485760 (10 MB)
#
# Example run:
#
#   docker run -p 8080:8080 \
#     -v /host/models:/models:ro \
#     -e ALERTIQ_REGISTRY_PATH=/models \
#     -e ALERTIQ_AUDIT_LOG_PATH=- \
#     alertiq-api:latest
#
# ============================================================================ #

# ---------------------------------------------------------------------------- #
# Stage 1 — dependency builder                                                  #
# ---------------------------------------------------------------------------- #
FROM python:3.11-slim AS builder

# Metadata
LABEL org.opencontainers.image.title="AlertIQ Scoring API" \
      org.opencontainers.image.description="AML alert triage engine — relative risk prioritisation for analyst review" \
      org.opencontainers.image.source="https://github.com/rithwikm7/alertiq"

# System deps needed to compile scikit-learn / scipy wheels (if any are not
# available as pre-built binaries from PyPI).
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        g++ \
    && rm -rf /var/lib/apt/lists/*

# Isolated virtual environment — keeps the runtime stage clean.
ENV VIRTUAL_ENV=/opt/venv
RUN python -m venv "$VIRTUAL_ENV"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Upgrade pip inside the venv first.
RUN pip install --no-cache-dir --upgrade pip

# Copy only the dependency specification first so Docker can cache this layer.
COPY pyproject.toml /build/pyproject.toml
WORKDIR /build

# Install runtime dependencies (no dev extras).
# We install the package in editable mode from the source tree in the next
# stage; here we only pull in third-party deps.
RUN pip install --no-cache-dir \
        "pydantic>=2.5" \
        "numpy>=1.26" \
        "pandas>=2.1" \
        "scipy>=1.11" \
        "scikit-learn>=1.3" \
        "starlette>=0.27" \
        "uvicorn[standard]>=0.27" \
        "joblib>=1.3"


# ---------------------------------------------------------------------------- #
# Stage 2 — runtime image                                                       #
# ---------------------------------------------------------------------------- #
FROM python:3.11-slim AS runtime

# Create a non-root user for the process.
RUN groupadd --gid 1001 alertiq \
    && useradd --uid 1001 --gid alertiq --shell /bin/bash --create-home alertiq

# Copy the pre-built virtual environment from the builder stage.
COPY --from=builder /opt/venv /opt/venv
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Copy the alertiq package source.
WORKDIR /app
COPY src/ /app/src/

# Install the alertiq package itself (no deps — already in venv).
RUN pip install --no-cache-dir --no-deps -e /app/src/../.  2>/dev/null || \
    pip install --no-cache-dir --no-deps /app/src

# Directory for the model registry (bind-mount at runtime; do NOT bake models
# into the image — they must be promoted through the registry lifecycle).
RUN mkdir -p /models && chown alertiq:alertiq /models

# Drop privileges.
USER alertiq

# Expose the API port.
EXPOSE 8080

# Runtime environment defaults.
ENV ALERTIQ_REGISTRY_PATH=/models \
    ALERTIQ_AUDIT_LOG_PATH=- \
    ALERTIQ_MAX_PAYLOAD_BYTES=10485760 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Health-check: poll GET /health every 30 s; start after 15 s warm-up.
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c \
        "import urllib.request, sys; \
         r = urllib.request.urlopen('http://localhost:8080/health', timeout=8); \
         sys.exit(0 if r.status == 200 else 1)"

# Entrypoint: uvicorn serving the Starlette app.
# Workers are intentionally kept at 1 — the model artifact is loaded into
# process memory at startup; multiple workers would each load a separate copy.
# Scale horizontally via container replicas behind a load balancer instead.
CMD ["uvicorn", "alertiq.serving.app:app", \
     "--host", "0.0.0.0", \
     "--port", "8080", \
     "--workers", "1", \
     "--access-log", \
     "--log-level", "info"]
