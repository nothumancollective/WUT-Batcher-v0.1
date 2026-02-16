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
