from __future__ import annotations

import os
from pathlib import Path
import random
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.constants import DEFAULT_RUNNER_MODE
from app.gui import MainWindow
from app.models import Project, ProjectConstraints
from app.services import OrchestratorService
from app.settings_store import SettingsStore, UserSettings

try:
    from PySide6.QtWidgets import QApplication, QWidget
except ImportError:  # pragma: no cover
    QApplication = None  # type: ignore[assignment]
    QWidget = None  # type: ignore[assignment]


@unittest.skipIf(QApplication is None, "PySide6 is required")
class BatchValidationAlignmentFuzzTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _build_window_and_project(
        self,
        service: OrchestratorService,
        *,
        project_name: str,
        fixed_params: dict | None = None,
        limits: dict | None = None,
        param_states: list | None = None,
    ) -> tuple[MainWindow, Project]:
        project = service.create_project(
            project_name,
            {
                "fixed_params": dict(fixed_params or {}),
                "limits": dict(limits or {}),
                "param_states": list(param_states or []),
                "runner_mode": DEFAULT_RUNNER_MODE,
            },
        )
        window = MainWindow(service)
        window.service.estimate_batch_runtime = lambda **_kwargs: {  # type: ignore[assignment]
            "version_count_preview": 0,
            "eta_seconds": None,
            "median_seconds_per_version": None,
            "sample_count": 0,
        }
        window.load_project(project)
        window.show_batch()
        window.batch_page.batch_name.setText("Fuzz Batch")
        window._on_batch_draft_changed(window.batch_page._payload(include_name=False))
        return window, project

    @staticmethod
    def _base_editor_enabled(row: object) -> bool:
        editor = getattr(row, "base_editor", None)
        if editor is None:
            return False
        if hasattr(editor, "value_widget"):
            widget = editor.value_widget()  # type: ignore[attr-defined]
            if QWidget is not None and isinstance(widget, QWidget):
                return bool(widget.isEnabled())
        if QWidget is not None and isinstance(editor, QWidget):
            return bool(editor.isEnabled())
        return True

    @staticmethod
    def _random_value_for_row(row: object, *, rng: random.Random):
        field = getattr(row, "field")
        key = str(getattr(field, "key", ""))
        kind = str(getattr(field, "widget_kind", ""))
        if kind == "enum":
            values = [opt.value for opt in list(getattr(field, "enum_options", []) or [])]
            return rng.choice(values + [None])
        if kind == "bool":
            return rng.choice([None, True, False])
        if kind == "object":
            if key == "R-OSSE":
                props = [str(item.key).rsplit(".", 1)[-1] for item in list(getattr(field, "object_properties", []) or [])]
                if not props:
                    return None
                sample_size = min(len(props), rng.choice([1, 2, 3]))
                chosen = rng.sample(props, k=sample_size)
                return {name: float(rng.choice([8, 12, 18, 24, 36, 50, 80])) for name in chosen}
            return rng.choice([None, 0, 1, True, False])
        if kind == "int":
            return int(rng.choice([0, 1, 2, 4, 8, 16, 32, 64, 120, 200]))
        if kind == "float":
            return float(rng.choice([0, 1.5, 3.0, 6.0, 12.0, 24.0, 45.0, 80.0, 120.0, 240.0]))
        if kind == "list":
            return rng.choice([None, "1,2,3", "5,10,15"])
        if kind == "ex":
            return rng.choice([None, "180", "220", "300+0*p"])
        return rng.choice([None, 10, 20, 40, 80, 120])

    def _try_mutate_row(self, window: MainWindow, *, rng: random.Random) -> None:
        form = window.batch_page.parameter_form
        visible_rows = [
            (key, row)
            for key, row in dict(getattr(form, "_rows", {}) or {}).items()
            if row is not None and not row.container.isHidden() and self._base_editor_enabled(row)
        ]
        if not visible_rows:
            return
        key, row = rng.choice(visible_rows)
        value = self._random_value_for_row(row, rng=rng)
        form._set_editor_value(row, value)  # type: ignore[attr-defined]
        form._on_field_edited(str(key))  # type: ignore[attr-defined]

    @staticmethod
    def _try_mutate_sweep(window: MainWindow, *, rng: random.Random) -> None:
        form = window.batch_page.parameter_form
        candidates = []
        for key, row in dict(getattr(form, "_rows", {}) or {}).items():
            if row is None or row.container.isHidden():
                continue
            if row.sweep_toggle.isHidden() or not row.sweep_toggle.isEnabled():
                continue
            candidates.append((str(key), row))
        if not candidates:
            return
        key, row = rng.choice(candidates)
        target = rng.choice([True, False, not bool(row.sweep_toggle.isChecked())])
        row.sweep_toggle.setChecked(bool(target))
        if not row.sweep_toggle.isChecked():
            return
        inputs = form.sweep_inputs_for_key(key)
        if not isinstance(inputs, dict):
            return
        start = float(rng.choice([5, 10, 20, 30, 60, 100]))
        end = float(start + rng.choice([0, 5, 10, 20, 40]))
        steps = int(rng.choice([2, 3, 4, 5, 8]))
        inputs["start"].setText(str(start))
        inputs["end"].setText(str(end))
        inputs["steps"].setText(str(steps))

    @staticmethod
    def _mutate_export_controls(window: MainWindow, *, rng: random.Random) -> None:
        panel = window.batch_page.export_panel
        panel.set_sweep_mode(rng.choice(["single", "combined"]))
        panel.freq_start.setText(str(float(rng.choice([100, 250, 500, 800]))))
        panel.freq_end.setText(str(float(rng.choice([8000, 10000, 15000, 20000]))))
        panel.num_points.setText(str(int(rng.choice([8, 16, 24, 32, 48]))))
        panel.mesh_frequency.setText(rng.choice(["", "1500", "2200", "3000"]))
        panel.preset_spl.setChecked(bool(rng.choice([True, False])))
        panel.preset_impedance.setChecked(bool(rng.choice([True, False])))

    def _assert_batch_alignment(self, window: MainWindow, project: Project) -> None:
        payload = window.batch_page._payload(include_name=False)
        selected = dict(payload.get("selected_params", {}) or {})
        sweeps = dict(payload.get("sweeps", {}) or {})
        sweep_mode = str(payload.get("sweep_mode", "single"))
        state = window.service.evaluate_batch_definition(
            project_id=project.project_id,
            selected_params=selected,
            sweeps=sweeps,
            sweep_mode=sweep_mode,
        )
        issues = [item for item in list(state.get("issues", []) or []) if isinstance(item, dict)]
        issue_rule_ids = {str(item.get("rule_id", "")).strip() for item in issues}

        blocked_rules = {"batch_param_not_visible", "sweep_not_allowed", "sweep_fixed_param_blocked"}
        self.assertTrue(issue_rule_ids.isdisjoint(blocked_rules))

        visible_keys = {str(item) for item in list(state.get("visible_keys", []) or []) if str(item).strip()}
        sweepable_keys = {str(item) for item in list(state.get("sweepable_keys", []) or []) if str(item).strip()}
        for key in selected.keys():
            self.assertIn(str(key), visible_keys)
        for key in sweeps.keys():
            self.assertIn(str(key), visible_keys)
            self.assertIn(str(key), sweepable_keys)

        ui_issues = [dict(item) for item in list(getattr(window.batch_page, "_latest_field_issues", []) or []) if isinstance(item, dict)]
        ui_normative_rule_ids = {
            str(item.get("rule_id", "")).strip()
            for item in ui_issues
            if str(item.get("source", "")).strip().lower() != "experiment"
        }
        self.assertTrue(ui_normative_rule_ids.issubset(issue_rule_ids))
        self.assertNotIn("batch_param_not_visible", ui_normative_rule_ids)

        if "Length" in selected and selected.get("Length") is not None:
            self.assertNotIn("validity_length_required", issue_rule_ids)
            self.assertNotIn("validity_length_required", ui_normative_rule_ids)

    def test_batch_ui_alignment_under_random_variable_combinations(self) -> None:
        rng = random.Random(20260217)
        with tempfile.TemporaryDirectory() as tmp_dir:
            library_root = Path(tmp_dir) / "library"
            settings_path = Path(tmp_dir) / "settings.json"
            store = SettingsStore(settings_path)
            store.save(UserSettings(library_root=str(library_root)))
            service = OrchestratorService(settings_store=store)

            scenarios = [
                {
                    "project_name": "Batch Fuzz A",
                    "fixed_params": {},
                    "limits": {},
                    "param_states": [],
                    "steps": 90,
                },
                {
                    "project_name": "Batch Fuzz B",
                    "fixed_params": {"Length": 220.0, "Throat.Profile": 2},
                    "limits": {},
                    "param_states": [
                        {"param_name": "Length", "is_set": 1, "value": 220.0},
                        {"param_name": "Throat.Profile", "is_set": 1, "value": 2},
                    ],
                    "steps": 80,
                },
                {
                    "project_name": "Batch Fuzz C",
                    "fixed_params": {"Length": 180.0, "Morph.TargetShape": 1, "GCurve.Type": 1},
                    "limits": {},
                    "param_states": [
                        {"param_name": "Length", "is_set": 1, "value": 180.0},
                        {"param_name": "Morph.TargetShape", "is_set": 1, "value": 1},
                        {"param_name": "GCurve.Type", "is_set": 1, "value": 1},
                    ],
                    "steps": 80,
                },
            ]

            for index, scenario in enumerate(scenarios, start=1):
                window, project = self._build_window_and_project(
                    service,
                    project_name=str(scenario["project_name"]),
                    fixed_params=dict(scenario["fixed_params"]),
                    limits=dict(scenario["limits"]),
                    param_states=list(scenario["param_states"]),
                )
                try:
                    steps = int(scenario["steps"])
                    for _step in range(steps):
                        op = rng.choice(["field", "field", "field", "sweep", "export"])
                        if op == "field":
                            self._try_mutate_row(window, rng=rng)
                        elif op == "sweep":
                            self._try_mutate_sweep(window, rng=rng)
                        else:
                            self._mutate_export_controls(window, rng=rng)

                        payload = window.batch_page._payload(include_name=False)
                        window._on_batch_draft_changed(payload)
                        self._assert_batch_alignment(window, project)
                finally:
                    window.close()


if __name__ == "__main__":
    unittest.main()
