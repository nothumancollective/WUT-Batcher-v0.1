from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch

from app.services import OrchestratorService
from app.settings_store import SettingsStore, UserSettings
from app.storage_manager import StorageManager

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication, QMessageBox

    from app.gui import SettingsDialog
except ImportError:  # pragma: no cover
    QApplication = None  # type: ignore[assignment]
    QMessageBox = None  # type: ignore[assignment]
    SettingsDialog = None  # type: ignore[assignment]


def _build_service(tmp_root: Path, *, library_name: str = "library") -> tuple[OrchestratorService, SettingsStore, Path]:
    settings_path = tmp_root / "settings.json"
    library_root = tmp_root / library_name
    library_root.mkdir(parents=True, exist_ok=True)
    store = SettingsStore(settings_path)
    store.save(UserSettings(library_root=str(library_root)))
    return OrchestratorService(settings_store=store), store, library_root


def test_save_settings_library_root_is_atomic_on_bootstrap_failure() -> None:
    with tempfile.TemporaryDirectory(prefix="wut_library_switch_atomic_") as tmp:
        root = Path(tmp)
        service, store, initial_library = _build_service(root)
        bad_target = root / "not_a_directory.txt"
        bad_target.write_text("not a directory", encoding="utf-8")

        requested = UserSettings.from_dict(
            {
                **service.settings.to_dict(),
                "library_root": str(bad_target),
            }
        )
        result = service.save_settings(requested)

        assert result.get("saved") is False
        assert "error" in result
        assert StorageManager.normalize_library_root(service.settings.library_root) == StorageManager.normalize_library_root(
            initial_library
        )
        persisted = store.load()
        assert StorageManager.normalize_library_root(persisted.library_root) == StorageManager.normalize_library_root(
            initial_library
        )


def test_try_set_library_root_repairs_missing_library_json_from_sqlite() -> None:
    with tempfile.TemporaryDirectory(prefix="wut_library_repair_json_") as tmp:
        root = Path(tmp) / "library"
        manager = StorageManager(root)
        expected_state = manager.ensure_library_root()
        metadata_json = root / "library.json"
        assert metadata_json.exists()
        metadata_json.unlink()

        result = StorageManager.try_set_library_root(root)
        assert result.ok is True
        assert result.state is not None
        payload = json.loads(metadata_json.read_text(encoding="utf-8"))
        assert str(payload.get("library_uid")) == expected_state.library_uid


def test_try_set_library_root_repairs_missing_sqlite_from_library_json() -> None:
    with tempfile.TemporaryDirectory(prefix="wut_library_repair_sqlite_") as tmp:
        root = Path(tmp) / "library"
        root.mkdir(parents=True, exist_ok=True)
        expected_uid = str(uuid.uuid4())
        metadata_payload = {
            "library_uid": expected_uid,
            "schema_version": 1,
            "created_at": "2026-02-25T00:00:00+00:00",
            "project_counter_next": 7,
        }
        (root / "library.json").write_text(json.dumps(metadata_payload, indent=2) + "\n", encoding="utf-8")

        result = StorageManager.try_set_library_root(root)
        assert result.ok is True
        assert result.state is not None
        assert result.state.library_uid == expected_uid
        assert int(result.state.project_counter_next) == 7
        assert (root / "library.sqlite").exists()


def test_counter_resets_per_library_root_and_project_uid_stays_unique() -> None:
    with patch.dict(os.environ, {"USE_PROJECT_LIBRARY_STORAGE": "1"}, clear=False):
        with tempfile.TemporaryDirectory(prefix="wut_library_counter_") as tmp:
            root = Path(tmp)
            service, _, library_a = _build_service(root, library_name="library_a")
            project_a1 = service.create_project("A1", {})
            project_a2 = service.create_project("A2", {})
            assert project_a1.project_id.startswith("P0001__")
            assert project_a2.project_id.startswith("P0002__")
            assert project_a1.project_uid
            assert project_a2.project_uid

            library_b = root / "library_b"
            library_b.mkdir(parents=True, exist_ok=True)
            switch_payload = UserSettings.from_dict(
                {
                    **service.settings.to_dict(),
                    "library_root": str(library_b),
                }
            )
            switch_result = service.save_settings(switch_payload)
            assert switch_result.get("saved") is True
            project_b1 = service.create_project("B1", {})
            assert project_b1.project_id.startswith("P0001__")
            assert project_b1.project_uid not in {project_a1.project_uid, project_a2.project_uid}

            reopen_payload = UserSettings.from_dict(
                {
                    **service.settings.to_dict(),
                    "library_root": str(library_a),
                }
            )
            reopen_result = service.save_settings(reopen_payload)
            assert reopen_result.get("saved") is True
            listed = service.list_projects()
            listed_ids = {project.project_id for project in listed}
            assert project_a1.project_id in listed_ids
            assert project_a2.project_id in listed_ids


@unittest.skipIf(QApplication is None or SettingsDialog is None or QMessageBox is None, "PySide6 is required")
class SettingsDialogSwitchFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_library_root_change_closes_project_after_confirmation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_library_dialog_switch_confirm_") as tmp:
            root = Path(tmp)
            service, _, initial_library = _build_service(root)
            other_library = root / "other_library"
            other_library.mkdir(parents=True, exist_ok=True)
            state = {"open": True, "closed_calls": 0}

            def is_project_open() -> bool:
                return bool(state["open"])

            def close_project() -> bool:
                state["closed_calls"] += 1
                state["open"] = False
                return True

            dialog = SettingsDialog(
                service,
                is_project_open=is_project_open,
                close_project_for_switch=close_project,
            )
            dialog.library_root.setText(str(other_library))

            with patch.object(dialog, "_confirm_switch_with_close_project", return_value=True):
                with patch.object(dialog, "accept", autospec=True) as accept_mock:
                    dialog._save()
                    self.assertEqual(accept_mock.call_count, 1)

            self.assertEqual(int(state["closed_calls"]), 1)
            self.assertEqual(
                StorageManager.normalize_library_root(service.settings.library_root),
                StorageManager.normalize_library_root(other_library),
            )

    def test_library_root_change_cancel_keeps_project_and_root(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_library_dialog_switch_cancel_") as tmp:
            root = Path(tmp)
            service, _, initial_library = _build_service(root)
            other_library = root / "other_library"
            other_library.mkdir(parents=True, exist_ok=True)
            state = {"open": True, "closed_calls": 0}

            def is_project_open() -> bool:
                return bool(state["open"])

            def close_project() -> bool:
                state["closed_calls"] += 1
                state["open"] = False
                return True

            dialog = SettingsDialog(
                service,
                is_project_open=is_project_open,
                close_project_for_switch=close_project,
            )
            dialog.library_root.setText(str(other_library))

            with patch.object(dialog, "_confirm_switch_with_close_project", return_value=False):
                with patch.object(dialog, "accept", autospec=True) as accept_mock:
                    dialog._save()
                    self.assertEqual(accept_mock.call_count, 0)

            self.assertEqual(int(state["closed_calls"]), 0)
            self.assertEqual(
                StorageManager.normalize_library_root(service.settings.library_root),
                StorageManager.normalize_library_root(initial_library),
            )


if __name__ == "__main__":
    unittest.main()
