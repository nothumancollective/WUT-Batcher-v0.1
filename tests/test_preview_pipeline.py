from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.models import Project
from app.models import ProjectConstraints
from app.services import (
    _build_preview_render_payload,
    _extract_not_visible_batch_keys,
    _missing_preview_policy_keys,
    _normalize_preview_render_parameters,
    _preview_seed_parameters,
)
from ui.stl_preview_widget import StlPreviewWidget

try:
    from PySide6.QtWidgets import QApplication
except ImportError:  # pragma: no cover
    QApplication = None  # type: ignore[assignment]


def _write_ascii_stl(path: Path) -> None:
    path.write_text(
        (
            "solid unit\n"
            "facet normal 0 0 1\n"
            " outer loop\n"
            "  vertex 0 0 0\n"
            "  vertex 1 0 0\n"
            "  vertex 0 1 0\n"
            " endloop\n"
            "endfacet\n"
            "endsolid unit\n"
        ),
        encoding="utf-8",
    )


@unittest.skipIf(QApplication is None, "PySide6 is required")
class PreviewPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_preview_seed_parameters_applies_required_fallbacks(self) -> None:
        constraints = ProjectConstraints(
            fixed_params={"Throat.Profile": 2},
            limits={},
            param_states=[],
        )
        payload = _preview_seed_parameters(constraints, {"GCurve.Type": 1})

        self.assertNotIn("Throat.Profile", payload)
        self.assertIn("R-OSSE", payload)
        self.assertEqual(float(payload["GCurve.Dist"]), 80.0)
        self.assertEqual(float(payload["GCurve.Width"]), 0.7)

    def test_preview_seed_parameters_adds_superformula_defaults_in_ath_minimal(self) -> None:
        constraints = ProjectConstraints(
            fixed_params={},
            limits={},
            param_states=[],
        )
        payload = _preview_seed_parameters(constraints, {"Length": 100.0, "GCurve.Type": 2})
        self.assertEqual(float(payload.get("GCurve.Dist", 0.0)), 80.0)
        self.assertEqual(float(payload.get("GCurve.Width", 0.0)), 0.7)
        for key in ("GCurve.SF.a", "GCurve.SF.b", "GCurve.SF.m1", "GCurve.SF.m2", "GCurve.SF.n1", "GCurve.SF.n2", "GCurve.SF.n3"):
            self.assertIn(key, payload)

    def test_extract_not_visible_batch_keys_parses_rule_issues(self) -> None:
        issue = type(
            "Issue",
            (),
            {
                "rule_id": "batch_param_not_visible",
                "message": "Batch parameter 'Mesh.InterfaceOffset' is not visible for current project constraints.",
            },
        )()
        keys = _extract_not_visible_batch_keys([issue])
        self.assertEqual(keys, ["Mesh.InterfaceOffset"])

    def test_normalize_preview_render_parameters_strips_internal_rosse_profile(self) -> None:
        normalized = _normalize_preview_render_parameters(
            {
                "Throat.Profile": 2,
                "R-OSSE": {"R": 150.0, "r0": 13.0},
                "Mesh.SubdomainSlices": [10, 20, 30],
                "Mesh.InterfaceOffset": [5.0],
            }
        )
        self.assertNotIn("Throat.Profile", normalized)
        self.assertIn("R-OSSE", normalized)
        rosse = dict(normalized.get("R-OSSE", {}) or {})
        self.assertEqual(float(rosse.get("R", 0.0)), 150.0)
        self.assertEqual(float(rosse.get("r0", 0.0)), 13.0)
        self.assertEqual(list(normalized.get("Mesh.InterfaceOffset", [])), [5.0, 0.0, 0.0])

    def test_preview_render_payload_ignores_none_selected_values(self) -> None:
        project = Project(
            project_id="P_PREVIEW_TEST",
            name="Preview",
            root_path=".",
            constraints=ProjectConstraints(
                project_id="P_PREVIEW_TEST",
                fixed_params={},
                limits={},
                param_states=[],
            ),
        )
        payload = _build_preview_render_payload(
            project=project,
            selected_params={
                "Throat.Profile": 2,
                "R-OSSE": {"R": 140.0, "r0": 12.7},
                "Length": 100.0,
                "Morph.TargetShape": 1,
                "Morph.TargetWidth": None,
            },
            sweep_mode="single",
        )
        render = dict(payload.get("render_parameters", {}) or {})
        self.assertNotIn("Throat.Profile", render)
        self.assertEqual(float(render.get("Length", 0.0)), 100.0)
        self.assertEqual(int(render.get("Morph.TargetShape", 0)), 1)
        self.assertIn("R-OSSE", render)
        self.assertEqual(str(payload.get("completion_tier")), "ath_minimal")
        self.assertTrue(isinstance(payload.get("policy_missing_keys", []), list))

    def test_missing_preview_policy_keys_reports_nonfatal_policy_gaps(self) -> None:
        missing = _missing_preview_policy_keys(
            {
                "Throat.Profile": 1,
                "Length": 100.0,
            }
        )
        self.assertIn("Term.s", missing)
        self.assertIn("Term.n", missing)
        self.assertIn("Term.q", missing)
        self.assertIn("OS.k", missing)
        self.assertIn("Mesh.ThroatResolution", missing)

    def test_missing_preview_policy_keys_for_superellipse_include_aspect_and_se_n(self) -> None:
        missing = _missing_preview_policy_keys(
            {
                "Length": 100.0,
                "GCurve.Type": 1,
                "GCurve.Dist": 80.0,
                "GCurve.Width": 0.7,
            }
        )
        self.assertIn("GCurve.AspectRatio", missing)
        self.assertIn("GCurve.SE.n", missing)
        self.assertNotIn("GCurve.Rot", missing)

    def test_missing_preview_policy_keys_for_superformula_include_sf_vector(self) -> None:
        missing = _missing_preview_policy_keys(
            {
                "Length": 100.0,
                "GCurve.Type": 2,
                "GCurve.Dist": 80.0,
                "GCurve.Width": 0.7,
                "GCurve.AspectRatio": 1.0,
            }
        )
        for key in ("GCurve.SF.a", "GCurve.SF.b", "GCurve.SF.m1", "GCurve.SF.m2", "GCurve.SF.n1", "GCurve.SF.n2", "GCurve.SF.n3"):
            self.assertIn(key, missing)
        self.assertNotIn("GCurve.Rot", missing)

    def test_preview_render_payload_keeps_policy_gaps_visible_while_using_ath_minimal_defaults(self) -> None:
        project = Project(
            project_id="P_PREVIEW_GCURVE",
            name="Preview",
            root_path=".",
            constraints=ProjectConstraints(
                project_id="P_PREVIEW_GCURVE",
                fixed_params={},
                limits={},
                param_states=[],
            ),
        )
        payload = _build_preview_render_payload(
            project=project,
            selected_params={"GCurve.Type": 2},
            sweep_mode="single",
        )
        render = dict(payload.get("render_parameters", {}) or {})
        self.assertIn("GCurve.SF.a", render)
        self.assertIn("GCurve.SF.n3", render)
        missing = set(payload.get("policy_missing_keys", []) or [])
        self.assertIn("GCurve.Dist", missing)
        self.assertIn("GCurve.Width", missing)
        self.assertIn("GCurve.AspectRatio", missing)
        self.assertIn("GCurve.SF.a", missing)

    def test_morph_targetshape_has_no_ath_minimal_extras_but_policy_marks_full_morph_set(self) -> None:
        project = Project(
            project_id="P_PREVIEW_MORPH",
            name="Preview",
            root_path=".",
            constraints=ProjectConstraints(
                project_id="P_PREVIEW_MORPH",
                fixed_params={},
                limits={},
                param_states=[],
            ),
        )
        payload = _build_preview_render_payload(
            project=project,
            selected_params={"Morph.TargetShape": 1},
            sweep_mode="single",
        )
        render = dict(payload.get("render_parameters", {}) or {})
        self.assertEqual(int(render.get("Morph.TargetShape", 0)), 1)
        self.assertNotIn("Morph.TargetWidth", render)
        self.assertNotIn("Morph.TargetHeight", render)
        missing = set(payload.get("policy_missing_keys", []) or [])
        self.assertIn("Morph.TargetWidth", missing)
        self.assertIn("Morph.TargetHeight", missing)
        self.assertIn("Morph.CornerRadius", missing)
        self.assertIn("Morph.FixedPart", missing)
        self.assertIn("Morph.Rate", missing)
        self.assertIn("Morph.AllowShrinkage", missing)

    def test_stl_preview_widget_renders_mesh_without_qt3d(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_preview_test_") as tmp:
            stl_path = Path(tmp) / "sample.stl"
            _write_ascii_stl(stl_path)

            widget = StlPreviewWidget()
            widget.resize(420, 300)
            widget.show()
            self.app.processEvents()

            widget.load_stl(stl_path)
            self.app.processEvents()

            software = getattr(widget, "_software_canvas", None)
            if software is not None:
                self.assertGreater(int(software.triangle_count()), 0)
            else:
                self.assertIsNotNone(getattr(widget, "_mesh_entity", None))
