from __future__ import annotations

from app.compatibility_service import CompatibilityService
from app.constants import DEFAULT_RUNNER_MODE
from ui.compat_ui_adapter import CompatUiAdapter
from ui.form_schema import build_project_form_schema


def test_batch_ui_adapter_uses_project_constraints_for_blocked_options() -> None:
    service = CompatibilityService()
    adapter = CompatUiAdapter(build_project_form_schema())
    constraints = {
        "project_id": "P001",
        "fixed_params": {"Length": 200.0, "Throat.Profile": 1, "Term.s": 0.4},
        "limits": {},
        "param_states": [
            {"param_name": "Throat.Profile", "is_set": 1, "value": 1},
            {"param_name": "Term.s", "is_set": 1, "value": 0.4},
        ],
        "runner_mode": DEFAULT_RUNNER_MODE,
    }
    state = service.evaluate_batch_definition(
        constraints,
        selected_params={},
        sweeps={},
        sweep_mode="single",
    )
    ui_state = adapter.compute_batch_ui_state(
        selected_params={},
        sweeps={},
        sweep_mode="single",
        compat_state=state,
        project_constraints=constraints,
        evaluate_batch=lambda sel, sw, mode: service.evaluate_batch_definition(
            constraints,
            selected_params=sel,
            sweeps=sw,
            sweep_mode=mode,
        ),
    )
    blocked = dict(ui_state.get("blocked_options", {}).get("Throat.Profile", {}) or {})
    assert blocked
    assert any(token in blocked for token in ("2", "3"))


def test_batch_ui_adapter_hides_controller_when_all_active_modes_are_blocked() -> None:
    adapter = CompatUiAdapter(build_project_form_schema())
    base_state = {
        "visible_keys": ["GCurve.Type", "Coverage.Angle", "Length"],
        "locked_keys": [],
        "sweepable_keys": [],
        "issues": [],
    }

    def evaluate_batch(sel: dict, _sw: dict, _mode: str) -> dict:
        gcurve_type = sel.get("GCurve.Type")
        if gcurve_type in {1, 2}:
            return {
                "visible_keys": ["GCurve.Type", "Coverage.Angle", "Length"],
                "issues": [
                    {
                        "severity": "fatal",
                        "rule_id": "validity_guidingcurve_requires_dist_and_width",
                        "field_key": "GCurve.Dist",
                        "message": "GCurve.Dist is required.",
                    }
                ],
            }
        return {
            "visible_keys": ["GCurve.Type", "Coverage.Angle", "Length"],
            "issues": [],
        }

    ui_state = adapter.compute_batch_ui_state(
        selected_params={},
        sweeps={},
        sweep_mode="single",
        compat_state=base_state,
        project_constraints={},
        evaluate_batch=evaluate_batch,
    )
    blocked = dict(ui_state.get("blocked_options", {}).get("GCurve.Type", {}) or {})
    assert "1" in blocked
    assert "2" in blocked
    assert "GCurve.Type" in set(ui_state.get("hidden_keys", []) or [])
