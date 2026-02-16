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
