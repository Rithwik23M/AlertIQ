"""
ModelRegistry — lightweight local model version registry.

Structure
---------
    <registry_root>/
        registry.json          # manifest listing all registered versions
        <model_version>/
            model.joblib       # serialised ModelArtifact
            model.joblib.sha256

registry.json schema
--------------------
    {
        "versions": [
            {
                "model_version":  "1.0.0",
                "artifact_path":  "1.0.0/model.joblib",   # relative to root
                "trained_at":     "2026-09-12T10:00:00Z",
                "training_rows":  42000,
                "schema_version": 1,
                "notes":          "...",
                "registered_at":  "2026-09-12T10:05:00Z",
                "is_champion":    true
            },
            ...
        ]
    }

Only one version may be marked ``is_champion`` at a time.
``get_champion()`` returns the champion artifact; ``list_versions()``
returns all registered entries.

Design rationale
----------------
A database or MLflow server would be overkill for a single-model AML
engine running on a single host.  A JSON manifest file is append-friendly,
human-readable, auditable with ``git diff``, and trivially backed up.
The manifest is rewritten atomically (write-to-temp then rename) to avoid
partial-write corruption.  File locking is NOT implemented; concurrent
writers must be serialised at the process level (e.g. by running
``train_and_serialize.py`` as a single process).
"""

from __future__ import annotations

import json
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from alertiq.serving.artifact import load_artifact, save_artifact, ModelArtifact, CURRENT_SCHEMA_VERSION
from alertiq.triage.config import TriageConfig
from alertiq.triage.scorer import TriageScorer

log = logging.getLogger(__name__)

REGISTRY_FILENAME = "registry.json"


class ModelRegistry:
    """Lightweight local registry for trained model versions.

    Parameters
    ----------
    root:
        Directory that will contain the registry manifest and all versioned
        model artefacts.  Created automatically if it does not exist.
    """

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._manifest_path = self._root / REGISTRY_FILENAME
        if not self._manifest_path.exists():
            self._write_manifest({"versions": []})

    # ------------------------------------------------------------------ #
    # Registration                                                         #
    # ------------------------------------------------------------------ #

    def register(
        self,
        scorer: TriageScorer,
        config: TriageConfig,
        *,
        model_version: str,
        training_rows: int,
        notes: str = "",
        promote_to_champion: bool = False,
    ) -> Path:
        """Serialise a fitted scorer and register it in the manifest.

        Parameters
        ----------
        scorer:
            Fitted TriageScorer (phase 2 preferred).
        config:
            The TriageConfig used during training.
        model_version:
            Semver string, e.g. ``"1.0.0"``.  Must be unique in this registry.
        training_rows:
            Number of rows used in the final fit.
        notes:
            Optional provenance string.
        promote_to_champion:
            If True, mark this version as the new champion and demote the
            previous champion.

        Returns
        -------
        Path
            The path to the saved ``.joblib`` file.

        Raises
        ------
        ValueError
            If *model_version* is already registered.
        """
        manifest = self._read_manifest()
        existing = [v["model_version"] for v in manifest["versions"]]
        if model_version in existing:
            raise ValueError(
                f"Model version '{model_version}' is already registered. "
                "Use a new version string for a new release."
            )

        artifact_dir = self._root / model_version
        artifact_path = artifact_dir / "model.joblib"

        save_artifact(
            scorer=scorer,
            config=config,
            model_version=model_version,
            path=artifact_path,
            training_rows=training_rows,
            notes=notes,
        )

        if promote_to_champion:
            for v in manifest["versions"]:
                v["is_champion"] = False

        entry: dict[str, Any] = {
            "model_version": model_version,
            "artifact_path": str(artifact_path.relative_to(self._root)),
            "trained_at": _utcnow(),
            "training_rows": training_rows,
            "schema_version": CURRENT_SCHEMA_VERSION,
            "notes": notes,
            "registered_at": _utcnow(),
            "is_champion": promote_to_champion,
        }
        # schema_version is sourced from CURRENT_SCHEMA_VERSION (not hardcoded)
        # so the manifest stays correct when the schema is incremented.
        manifest["versions"].append(entry)
        self._write_manifest(manifest)

        log.info(
            "Registered: version=%s champion=%s path=%s",
            model_version,
            promote_to_champion,
            artifact_path,
        )
        return artifact_path

    # ------------------------------------------------------------------ #
    # Retrieval                                                            #
    # ------------------------------------------------------------------ #

    def get_champion(self) -> ModelArtifact:
        """Load and return the current champion model artifact.

        Raises
        ------
        LookupError
            If no champion is registered.
        """
        manifest = self._read_manifest()
        champions = [v for v in manifest["versions"] if v.get("is_champion")]
        if not champions:
            raise LookupError(
                "No champion model registered in the registry. "
                "Run train_and_serialize.py --promote to register one."
            )
        champion = champions[-1]  # last champion wins if duplicates exist
        artifact_path = self._root / champion["artifact_path"]
        return load_artifact(artifact_path)

    def get_version(self, model_version: str) -> ModelArtifact:
        """Load and return a specific model version by version string.

        Raises
        ------
        LookupError
            If the version is not registered.
        """
        manifest = self._read_manifest()
        for v in manifest["versions"]:
            if v["model_version"] == model_version:
                artifact_path = self._root / v["artifact_path"]
                return load_artifact(artifact_path)
        raise LookupError(f"Model version '{model_version}' not found in registry.")

    def list_versions(self) -> list[dict[str, Any]]:
        """Return all registered version entries from the manifest."""
        manifest = self._read_manifest()
        return list(manifest["versions"])

    def promote(self, model_version: str) -> None:
        """Promote *model_version* to champion, demoting the current champion.

        Raises
        ------
        LookupError
            If *model_version* is not registered.
        """
        manifest = self._read_manifest()
        found = False
        for v in manifest["versions"]:
            if v["model_version"] == model_version:
                found = True
            v["is_champion"] = v["model_version"] == model_version
        if not found:
            raise LookupError(f"Model version '{model_version}' not found in registry.")
        self._write_manifest(manifest)
        log.info("Promoted to champion: version=%s", model_version)

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _read_manifest(self) -> dict[str, Any]:
        return json.loads(self._manifest_path.read_text(encoding="utf-8"))

    def _write_manifest(self, manifest: dict[str, Any]) -> None:
        """Write the manifest atomically (temp file + rename)."""
        text = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
        tmp = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self._root,
            suffix=".tmp",
            delete=False,
        )
        try:
            tmp.write(text)
            tmp.flush()
            tmp.close()
            Path(tmp.name).replace(self._manifest_path)
        except Exception:
            Path(tmp.name).unlink(missing_ok=True)
            raise


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()
