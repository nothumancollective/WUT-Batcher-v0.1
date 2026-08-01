"""Analyzer artifact registry and availability probes.

This module is intentionally lightweight in Phase 2:
- POLAR is fully supported (data loading/compute paths already exist).
- SPL/IMPEDANCE/PHASE_GD are scaffolds with availability probing only.
"""

from __future__ import annotations

from dataclasses import dataclass
import sqlite3
from typing import Any, Dict, Iterable, Mapping, Optional, Protocol


class AnalyzerArtifact(Protocol):
    artifact_type: str

    def is_available(
        self,
        *,
        conn: sqlite3.Connection,
        project_id: str,
        batch_id: str,
        run_id: Optional[str],
        version_id: str,
    ) -> bool: ...

    def load(
        self,
        *,
        conn: sqlite3.Connection,
        project_id: str,
        batch_id: str,
        run_id: Optional[str],
        version_id: str,
        plane: Optional[str],
        config: Mapping[str, Any],
    ) -> Dict[str, Any]: ...

    def compute_curves(
        self,
        *,
        payload: Mapping[str, Any],
        config: Mapping[str, Any],
    ) -> Dict[str, Any]: ...


@dataclass(frozen=True)
class ArtifactStatus:
    artifact_type: str
    available: bool
    message: str


class PolarArtifact:
    artifact_type = "POLAR"

    def is_available(
        self,
        *,
        conn: sqlite3.Connection,
        project_id: str,
        batch_id: str,
        run_id: Optional[str],
        version_id: str,
    ) -> bool:
        run_token = str(run_id or "").strip()
        row = conn.execute(
            """
            SELECT COUNT(*) AS count_value
            FROM polar_measurements
            WHERE project_id = ?
              AND batch_id = ?
              AND version_id = ?
              AND COALESCE(run_id, '') = ?
              AND (
                TRIM(COALESCE(data_level_type, '')) = ''
                OR LOWER(REPLACE(TRIM(data_level_type), ' ', '')) IN ('soundpressure', 'spl')
              )
            """,
            (str(project_id), str(batch_id), str(version_id), run_token),
        ).fetchone()
        count_value = int(row[0]) if row is not None else 0
        return bool(count_value > 0)

    def load(
        self,
        *,
        conn: sqlite3.Connection,
        project_id: str,
        batch_id: str,
        run_id: Optional[str],
        version_id: str,
        plane: Optional[str],
        config: Mapping[str, Any],
    ) -> Dict[str, Any]:
        # Real polar loading is handled by plot service / stage plot service.
        return {
            "artifact_type": self.artifact_type,
            "project_id": str(project_id),
            "batch_id": str(batch_id),
            "run_id": str(run_id or "").strip() or None,
            "version_id": str(version_id),
            "plane": str(plane or ""),
            "config": dict(config or {}),
        }

    def compute_curves(
        self,
        *,
        payload: Mapping[str, Any],
        config: Mapping[str, Any],
    ) -> Dict[str, Any]:
        # Curves are computed in stage_plot_engine for polar payloads.
        return {"artifact_type": self.artifact_type, "curves": {}}


class _GraphKindScaffoldArtifact:
    artifact_type = "UNKNOWN"
    graph_kind_tokens: tuple[str, ...] = tuple()
    message_when_missing = "Artifact data not available."

    def is_available(
        self,
        *,
        conn: sqlite3.Connection,
        project_id: str,
        batch_id: str,
        run_id: Optional[str],
        version_id: str,
    ) -> bool:
        if not self.graph_kind_tokens:
            return False
        run_token = str(run_id or "").strip()
        rows = conn.execute(
            """
            SELECT COALESCE(graph_kind, '') AS graph_kind,
                   COALESCE(y_axis, '') AS y_axis,
                   COALESCE(variant, '') AS variant
            FROM graphs
            WHERE project_id = ?
              AND batch_id = ?
              AND version_id = ?
              AND COALESCE(run_id, '') = ?
            """,
            (str(project_id), str(batch_id), str(version_id), run_token),
        ).fetchall()
        if not rows:
            return False
        tokens = tuple(token.lower() for token in self.graph_kind_tokens)
        for row in rows:
            text = " ".join(
                [
                    str(row[0] or "").lower(),
                    str(row[1] or "").lower(),
                    str(row[2] or "").lower(),
                ]
            )
            if any(token in text for token in tokens):
                return True
        return False

    def load(
        self,
        *,
        conn: sqlite3.Connection,
        project_id: str,
        batch_id: str,
        run_id: Optional[str],
        version_id: str,
        plane: Optional[str],
        config: Mapping[str, Any],
    ) -> Dict[str, Any]:
        return {
            "artifact_type": self.artifact_type,
            "available": self.is_available(
                conn=conn,
                project_id=project_id,
                batch_id=batch_id,
                run_id=run_id,
                version_id=version_id,
            ),
            "message": self.message_when_missing,
        }

    def compute_curves(
        self,
        *,
        payload: Mapping[str, Any],
        config: Mapping[str, Any],
    ) -> Dict[str, Any]:
        return {
            "artifact_type": self.artifact_type,
            "available": bool(payload.get("available")),
            "curves": {},
            "message": str(payload.get("message") or self.message_when_missing),
        }


class SplFrArtifact(_GraphKindScaffoldArtifact):
    artifact_type = "SPL_FR"
    graph_kind_tokens = ("spl", "fr", "frequency_response")
    message_when_missing = "SPL/FR artifact missing for this Batch/Version."


class ImpedanceArtifact(_GraphKindScaffoldArtifact):
    artifact_type = "IMPEDANCE"
    graph_kind_tokens = ("impedance", "z_in", "zrad", "z_rad")
    message_when_missing = "Impedance/loading artifact missing for this Batch/Version."


class PhaseGdArtifact(_GraphKindScaffoldArtifact):
    artifact_type = "PHASE_GD"
    graph_kind_tokens = ("phase", "group_delay", "gd")
    message_when_missing = "Phase/group-delay artifact missing for this Batch/Version."


ARTIFACT_REGISTRY: Dict[str, AnalyzerArtifact] = {
    "POLAR": PolarArtifact(),
    "SPL_FR": SplFrArtifact(),
    "IMPEDANCE": ImpedanceArtifact(),
    "PHASE_GD": PhaseGdArtifact(),
}


def available_artifact_statuses(
    *,
    conn: sqlite3.Connection,
    project_id: str,
    batch_id: str,
    run_id: Optional[str],
    version_id: str,
    artifact_types: Optional[Iterable[str]] = None,
) -> Dict[str, Dict[str, Any]]:
    requested = [str(item).upper() for item in list(artifact_types or ARTIFACT_REGISTRY.keys()) if str(item).strip()]
    statuses: Dict[str, Dict[str, Any]] = {}
    for token in requested:
        artifact = ARTIFACT_REGISTRY.get(token)
        if artifact is None:
            continue
        available = bool(
            artifact.is_available(
                conn=conn,
                project_id=project_id,
                batch_id=batch_id,
                run_id=run_id,
                version_id=version_id,
            )
        )
        message = ""
        if not available:
            message = getattr(artifact, "message_when_missing", "Artifact not available.")
        statuses[token] = {
            "artifact_type": token,
            "available": available,
            "message": message,
        }
    return statuses
