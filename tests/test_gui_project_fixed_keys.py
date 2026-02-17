from __future__ import annotations

from app.gui import MainWindow
from app.models import ProjectConstraints


def test_project_fixed_keys_include_set_param_states() -> None:
    constraints = ProjectConstraints(
        project_id="P001",
        fixed_params={"Length": 200.0},
        limits={"Throat.Diameter": 15.0},
        param_states=[
            {"param_name": "Throat.Profile", "is_set": 1, "value": 2},
            {"param_name": "Morph.TargetShape", "is_set": 0, "value": None},
            {"param_name": "GCurve.Type", "is_set": True, "value": 1},
        ],
    )
    keys = MainWindow._project_fixed_keys_from_constraints(constraints)
    assert set(keys) == {"Length", "Throat.Diameter", "Throat.Profile", "GCurve.Type"}


def test_sanitize_batch_payload_prunes_non_visible_and_fixed_keys() -> None:
    constraints = ProjectConstraints(
        project_id="P001",
        fixed_params={"Length": 200.0, "Throat.Profile": 2},
        limits={},
        param_states=[{"param_name": "Throat.Profile", "is_set": 1, "value": 2}],
    )
    payload = {
        "batch_name": "B1",
        "sweep_mode": "single",
        "selected_params": {
            "Length": 250.0,  # fixed at project level -> remove
            "Throat.Profile": 1,  # fixed at project level -> remove
            "Term.s": 0.4,  # not visible in project state -> remove
            "GCurve.Dist": 120.0,  # keep
        },
        "sweeps": {
            "Term.s": {"start": 0.3, "end": 0.5, "steps": 3},  # remove (not visible)
            "GCurve.Type": {"start": 1, "end": 2, "steps": 2},  # remove (not sweepable)
            "GCurve.Dist": {"start": 100.0, "end": 140.0, "steps": 3},  # keep
        },
    }
    project_state = {
        "visible_keys": ["Length", "GCurve.Type", "GCurve.Dist"],
        "sweepable_keys": ["GCurve.Dist"],
    }
    sanitized, changed = MainWindow._sanitize_batch_payload_for_project_constraints(payload, constraints, project_state)
    assert changed is True
    assert sanitized["selected_params"] == {"GCurve.Dist": 120.0}
    assert sanitized["sweeps"] == {"GCurve.Dist": {"start": 100.0, "end": 140.0, "steps": 3}}


def test_sanitize_batch_payload_keeps_sweeps_if_current_batch_state_allows_them() -> None:
    constraints = ProjectConstraints(
        project_id="P001",
        fixed_params={"Length": 200.0},
        limits={},
        param_states=[],
    )
    payload = {
        "batch_name": "B1",
        "sweep_mode": "single",
        "selected_params": {"Term.s": 0.4},
        "sweeps": {"Term.s": {"start": 0.3, "end": 0.5, "steps": 3}},
    }
    current_batch_state = {
        "visible_keys": ["Length", "Term.s"],
        "sweepable_keys": ["Term.s"],
    }
    sanitized, changed = MainWindow._sanitize_batch_payload_for_project_constraints(
        payload,
        constraints,
        current_batch_state,
    )
    assert changed is False
    assert sanitized["selected_params"] == {"Term.s": 0.4}
    assert sanitized["sweeps"] == {"Term.s": {"start": 0.3, "end": 0.5, "steps": 3}}
