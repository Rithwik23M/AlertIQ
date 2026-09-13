"""
alertiq.serving — production model serving layer.

Provides:
    - artifact.py   : model serialisation (save / load with checksum)
    - registry.py   : lightweight local model version registry
    - schema.py     : Pydantic request / response schemas
    - quality.py    : pre-inference data quality checks
    - audit.py      : structured append-only audit log
    - scorer.py     : stateless inference wrapper
    - app.py        : FastAPI application (GET /health, GET /model/info,
                      POST /score, POST /score/batch)

Operating policy
----------------
AlertIQ is a CAPACITY-RANKING system.  Every ``risk_score`` value returned
by the API is a relative priority indicator for analyst review, NOT a binary
SAR/non-SAR classification and NOT a compliance determination.

Human analysts make all SAR filing decisions.
"""

from alertiq.serving.artifact import ModelArtifact, save_artifact, load_artifact
from alertiq.serving.registry import ModelRegistry

__all__ = [
    "ModelArtifact",
    "save_artifact",
    "load_artifact",
    "ModelRegistry",
]
