from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.export_specs import ExportSpec
from app.vacs_export_pipeline import VacsExportPipelineError, run_vacs_export_specs


@dataclass
class _DummyDriverResult:
    details: dict


class _FakeVacsDriver:
    def __init__(self, *, executable: str, log_dir: str) -> None:
        self.executable = executable
        self.log_dir = log_dir
        self.calls = []

    def open_results(self, project_or_abec_path: str) -> _DummyDriverResult:
        self.calls.append(("open_results", project_or_abec_path))
        return _DummyDriverResult(details={"ok": True})

    def open_graph(self, graph_type: str) -> _DummyDriverResult:
        self.calls.append(("open_graph", graph_type))
        return _DummyDriverResult(details={"ok": True})

    def export_txt(self, profile: dict) -> _DummyDriverResult:
        self.calls.append(("export_txt", profile))
        output_file = Path(str(profile["output_file"]))
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text("Frequency [Hz];SPL [dB]\n100;90\n", encoding="utf-8")
        return _DummyDriverResult(details={"output_file": str(output_file)})

    def close(self) -> _DummyDriverResult:
        self.calls.append(("close", None))
        return _DummyDriverResult(details={"closed": True})


class VacsExportPipelineTests(unittest.TestCase):
    def _write_catalog(self, root: Path, *, entries: list[dict]) -> None:
        path = root / "default" / "graph_catalog.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"schema_version": "1.0", "vacs_version": "default", "entries": entries}, indent=2),
            encoding="utf-8",
        )

    def test_pipeline_blocks_unmapped_spec_with_remediation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            self._write_catalog(
                root,
                entries=[
                    {
                        "graph_kind": "spl",
                        "variant": None,
                        "format": "txt",
                        "recipe_id": "vacs_export_spl_txt_v1",
                        "selectors": {"graph_open": "spl"},
                        "export_dialog_signature": "vacs_export_dialog",
                        "supported_formats": ["txt"],
                        "options": {},
                    }
                ],
            )
            spec = ExportSpec(id="phase_1", tool="vacs", graph_kind="phase", format="txt")
            with patch("app.vacs_export_pipeline.VacsDriver", _FakeVacsDriver):
                with self.assertRaises(VacsExportPipelineError) as ctx:
                    run_vacs_export_specs(
                        executable="C:\\Tools\\VACS\\vacsviewer_32.exe",
                        vacs_version="default",
                        project_id="P001",
                        batch_id="B001",
                        version_id="V001",
                        abec_path=root / "Project.abec",
                        export_specs=[spec],
                        export_dir=root / "exports",
                        log_dir=root / "logs",
                        catalog_root=root,
                    )
            self.assertIn("discover-graphs", str(ctx.exception))

    def test_pipeline_exports_mapped_spec(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            abec_path = root / "Project.abec"
            abec_path.write_text("stub", encoding="utf-8")
            self._write_catalog(
                root,
                entries=[
                    {
                        "graph_kind": "spl",
                        "variant": None,
                        "format": "txt",
                        "recipe_id": "vacs_export_spl_txt_v1",
                        "selectors": {"graph_open": "spl"},
                        "export_dialog_signature": "vacs_export_dialog",
                        "supported_formats": ["txt"],
                        "options": {},
                    }
                ],
            )
            spec = ExportSpec(id="spl_1", tool="vacs", graph_kind="spl", format="txt")
            with patch("app.vacs_export_pipeline.VacsDriver", _FakeVacsDriver):
                result = run_vacs_export_specs(
                    executable="C:\\Tools\\VACS\\vacsviewer_32.exe",
                    vacs_version="default",
                    project_id="P001",
                    batch_id="B001",
                    version_id="V001",
                    abec_path=abec_path,
                    export_specs=[spec],
                    export_dir=root / "exports",
                    log_dir=root / "logs",
                    catalog_root=root,
                )
            self.assertTrue(result["executed"])
            self.assertEqual(result["export_count"], 1)
            output_path = Path(result["exports"][0]["output_path"])
            self.assertTrue(output_path.exists())


if __name__ == "__main__":
    unittest.main()
