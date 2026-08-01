from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.export_specs import ExportSpec
from app.vacs_export_pipeline import (
    VacsExportPipelineError,
    _run_external_vacs_export_save_all,
    _graph_kind_match_score,
    run_vacs_export_specs,
)


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
    def test_external_runner_uses_assume_ready_auto_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            captured: dict = {}

            class _Proc:
                returncode = 0
                stdout = json.dumps({"ok": True, "run_id": "r1", "exported_files": []})
                stderr = ""

            def _fake_run(cmd, capture_output, text, check):  # type: ignore[no-untyped-def]
                captured["cmd"] = list(cmd)
                return _Proc()

            with patch("app.vacs_export_pipeline.subprocess.run", side_effect=_fake_run):
                payload = _run_external_vacs_export_save_all(
                    executable="C:\\Tools\\VACS\\vacsviewer_32.exe",
                    akabak_executable="C:\\Tools\\AKABAK\\AKABAK.exe",
                    export_dir=root / "exports",
                    log_dir=root / "logs",
                )

            self.assertTrue(bool(payload.get("ok")))
            cmd = list(captured.get("cmd", []))
            self.assertIn("--mode", cmd)
            self.assertIn("auto", cmd)
            self.assertIn("--assume-vacs-ready", cmd)
            staging_arg = Path(cmd[cmd.index("--export-dir") + 1])
            self.assertNotEqual(staging_arg, root / "exports")
            self.assertIn("wut_vacs_export_", staging_arg.name)

    def test_external_runner_relocates_short_staging_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            captured_staging: list[Path] = []

            def _fake_run(cmd, capture_output, text, check):  # type: ignore[no-untyped-def]
                staging = Path(cmd[cmd.index("--export-dir") + 1])
                captured_staging.append(staging)
                source = staging / "Radiation_Impedance_with_a_descriptive_title.txt"
                source.write_text("Data_LevelType=Impedance10\nData\n100 0 0\n", encoding="utf-8")

                class _Proc:
                    returncode = 0
                    stdout = json.dumps(
                        {
                            "ok": True,
                            "run_id": "r1",
                            "exported_files": [{"graph": {"title": "Radiation Impedance"}, "path": str(source)}],
                        }
                    )
                    stderr = ""

                return _Proc()

            with patch("app.vacs_export_pipeline.subprocess.run", side_effect=_fake_run):
                payload = _run_external_vacs_export_save_all(
                    executable="C:\\Tools\\VACS\\vacsviewer_32.exe",
                    akabak_executable="C:\\Tools\\AKABAK\\AKABAK.exe",
                    export_dir=root / "canonical" / "exports",
                    log_dir=root / "logs",
                )

            relocated = Path(payload["exported_files"][0]["path"])
            self.assertTrue(relocated.exists())
            self.assertEqual(relocated.name, "external_raw_01.txt")
            self.assertEqual(relocated.parent, root / "canonical" / "exports")
            self.assertTrue(bool(payload["staging"]["used"]))
            self.assertFalse(captured_staging[0].exists())

    def test_external_runner_surfaces_structured_error_on_nonzero_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)

            class _Proc:
                returncode = 1
                stdout = json.dumps(
                    {
                        "ok": False,
                        "error": "vacs_not_ready_after_f4",
                        "summary_file": "C:/tmp/summary.json",
                        "trace_file": "C:/tmp/trace.jsonl",
                    }
                )
                stderr = ""

            def _fake_run(cmd, capture_output, text, check):  # type: ignore[no-untyped-def]
                return _Proc()

            with patch("app.vacs_export_pipeline.subprocess.run", side_effect=_fake_run):
                with self.assertRaises(VacsExportPipelineError) as ctx:
                    _run_external_vacs_export_save_all(
                        executable="C:\\Tools\\VACS\\vacsviewer_32.exe",
                        akabak_executable="C:\\Tools\\AKABAK\\AKABAK.exe",
                        export_dir=root / "exports",
                        log_dir=root / "logs",
                    )
            message = str(ctx.exception)
            self.assertIn("rc=1", message)
            self.assertIn("vacs_not_ready_after_f4", message)
            self.assertIn("summary_file=", message)

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

    def test_external_export_relocates_to_final_path_above_dialog_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source = root / "raw_spl.txt"
            source.write_text(
                "Data_LevelType=SoundPressure\nData_Legend='SPL'\nData\n1000 1.0\n",
                encoding="utf-8",
            )
            target_length = 231
            pad_length = target_length - len(str(root)) - 1
            self.assertGreater(pad_length, 0)
            export_dir = root / ("x" * pad_length)
            spec = ExportSpec(id="spl_main", tool="vacs", graph_kind="spl", format="txt")
            with patch(
                "app.vacs_export_pipeline._run_external_vacs_export_save_all",
                return_value={
                    "ok": True,
                    "run_id": "run_long_final_path",
                    "exported_files": [
                        {"graph": {"title": "SPL spectrum"}, "path": str(source)},
                    ],
                    "summary_file": str(root / "summary.json"),
                },
            ):
                result = run_vacs_export_specs(
                    executable="C:\\Tools\\VACS\\vacsviewer_32.exe",
                    vacs_version="default",
                    project_id="P001",
                    batch_id="B001",
                    version_id="V001",
                    abec_path=root / "Project.abec",
                    export_specs=[spec],
                    export_dir=export_dir,
                    log_dir=root / "logs",
                    akabak_executable="C:\\Tools\\AKABAK\\AKABAK.exe",
                )

            output_path = Path(result["exports"][0]["output_path"])
            self.assertTrue(output_path.exists())
            self.assertGreater(len(str(output_path)), 240)
            self.assertLessEqual(len(str(output_path)), 259)

    def test_graph_kind_match_score_uses_metadata(self) -> None:
        score = _graph_kind_match_score(
            graph_kind="impedance",
            title="Graph #1",
            path="C:\\tmp\\g1.txt",
            metadata={"Data_LevelType": "Impedance10", "Data_Legend": "Radiation_Impedance #5"},
        )
        self.assertGreater(score, 0)

    def test_external_mapping_uses_data_level_type_for_impedance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source = root / "raw_graph.txt"
            source.write_text(
                "\n".join(
                    [
                        "SourceDesc=VACS_Data_Text",
                        "Data_LevelType=Impedance10",
                        "Data_Legend='Radiation_Impedance #5'",
                        "StartString_Data=Data",
                        "EndString_Data=Data_End",
                        "Data",
                        "1000 0.0 0.0",
                        "Data_End",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            spec = ExportSpec(id="radimp_main", tool="vacs", graph_kind="impedance", format="txt")
            with patch(
                "app.vacs_export_pipeline._run_external_vacs_export_save_all",
                return_value={
                    "ok": True,
                    "run_id": "run_x",
                    "exported_files": [
                        {
                            "graph": {"title": "Graph #1"},
                            "path": str(source),
                        }
                    ],
                    "summary_file": str(root / "summary.json"),
                },
            ):
                result = run_vacs_export_specs(
                    executable="C:\\Tools\\VACS\\vacsviewer_32.exe",
                    vacs_version="default",
                    project_id="P001",
                    batch_id="B001",
                    version_id="V001",
                    abec_path=root / "Project.abec",
                    export_specs=[spec],
                    export_dir=root / "exports",
                    log_dir=root / "logs",
                    akabak_executable="C:\\Tools\\AKABAK\\AKABAK.exe",
                )
            self.assertTrue(result["executed"])
            self.assertEqual(result["export_count"], 1)
            details = result["exports"][0]["details"]
            self.assertEqual(details["source_data_level_type"], "Impedance10")
            self.assertGreaterEqual(int(details["mapping_score"]), 1)

    def test_external_mapping_failure_lists_available_graph_signatures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source = root / "raw_graph.txt"
            source.write_text(
                "\n".join(
                    [
                        "SourceDesc=VACS_Data_Text",
                        "Data_LevelType=SoundPressure",
                        "Data_Legend='Sound pressure'",
                        "StartString_Data=Data",
                        "EndString_Data=Data_End",
                        "Data",
                        "1000 1.0 0.0",
                        "Data_End",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            spec = ExportSpec(id="radimp_main", tool="vacs", graph_kind="impedance", format="txt")
            with patch(
                "app.vacs_export_pipeline._run_external_vacs_export_save_all",
                return_value={
                    "ok": True,
                    "run_id": "run_x",
                    "exported_files": [
                        {
                            "graph": {"title": "Mic Polar - BE_Spectrum #2"},
                            "path": str(source),
                        }
                    ],
                    "summary_file": str(root / "summary.json"),
                },
            ):
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
                        akabak_executable="C:\\Tools\\AKABAK\\AKABAK.exe",
                    )
            text = str(ctx.exception)
            self.assertIn("available_graphs=", text)
            self.assertIn("SoundPressure", text)

    def test_external_any_graph_fallback_accepts_any_exported_graph(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source_a = root / "raw_graph_a.txt"
            source_b = root / "raw_graph_b.txt"
            source_a.write_text(
                "\n".join(
                    [
                        "SourceDesc=VACS_Data_Text",
                        "Data_LevelType=SoundPressure",
                        "Data_Legend='SPL curve'",
                        "StartString_Data=Data",
                        "EndString_Data=Data_End",
                        "Data",
                        "100 1.0",
                        "Data_End",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            source_b.write_text(
                "\n".join(
                    [
                        "SourceDesc=VACS_Data_Text",
                        "Data_LevelType=Impedance10",
                        "Data_Legend='Radiation_Impedance #5'",
                        "StartString_Data=Data",
                        "EndString_Data=Data_End",
                        "Data",
                        "100 0.0 0.0",
                        "Data_End",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            spec = ExportSpec(id="only_one_requested", tool="vacs", graph_kind="spl", format="txt")
            with patch(
                "app.vacs_export_pipeline._run_external_vacs_export_save_all",
                return_value={
                    "ok": True,
                    "run_id": "run_x",
                    "exported_files": [
                        {"graph": {"title": "Mic Polar - BE_Spectrum #2"}, "path": str(source_a)},
                        {"graph": {"title": "Graph #2"}, "path": str(source_b)},
                    ],
                    "summary_file": str(root / "summary.json"),
                },
            ):
                result = run_vacs_export_specs(
                    executable="C:\\Tools\\VACS\\vacsviewer_32.exe",
                    vacs_version="default",
                    project_id="P001",
                    batch_id="B001",
                    version_id="V001",
                    abec_path=root / "Project.abec",
                    export_specs=[spec],
                    export_dir=root / "exports",
                    log_dir=root / "logs",
                    akabak_executable="C:\\Tools\\AKABAK\\AKABAK.exe",
                    allow_graph_kind_fallback=True,
                )

            self.assertTrue(result["executed"])
            self.assertEqual(str(result.get("mapping_mode", "")), "any_graph")
            self.assertEqual(int(result["export_count"]), 2)
            exports = list(result.get("exports", []) or [])
            self.assertEqual(len(exports), 2)
            kinds = {str((row.get("spec", {}) or {}).get("graph_kind", "") or "") for row in exports}
            self.assertIn("spl", kinds)
            self.assertIn("impedance", kinds)
            for row in exports:
                details = dict(row.get("details", {}) or {})
                self.assertEqual(str(details.get("mapping_mode", "")), "any_graph")
                self.assertEqual(
                    str(details.get("inferred_graph_kind", "") or ""),
                    str((row.get("spec", {}) or {}).get("graph_kind", "") or ""),
                )
                self.assertIn("only_one_requested", list(details.get("requested_spec_ids", []) or []))
                self.assertTrue(Path(str(row.get("output_path", ""))).exists())

    def test_external_any_graph_fallback_requires_at_least_one_graph(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            spec = ExportSpec(id="only_one_requested", tool="vacs", graph_kind="spl", format="txt")
            with patch(
                "app.vacs_export_pipeline._run_external_vacs_export_save_all",
                return_value={
                    "ok": True,
                    "run_id": "run_x",
                    "exported_files": [],
                    "summary_file": str(root / "summary.json"),
                },
            ):
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
                        akabak_executable="C:\\Tools\\AKABAK\\AKABAK.exe",
                        allow_graph_kind_fallback=True,
                    )
            self.assertIn("no usable graph files", str(ctx.exception))

    def test_external_any_graph_fallback_requires_requested_kind_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source = root / "raw_spl.txt"
            source.write_text(
                "Data_LevelType=SoundPressure\nData_Legend='SPL'\nData\n100 1.0\n",
                encoding="utf-8",
            )
            specs = [
                ExportSpec(id="polar", tool="vacs", graph_kind="polar", format="txt"),
                ExportSpec(id="radimp", tool="vacs", graph_kind="impedance", format="txt"),
            ]
            with patch(
                "app.vacs_export_pipeline._run_external_vacs_export_save_all",
                return_value={
                    "ok": True,
                    "run_id": "run_x",
                    "exported_files": [
                        {"graph": {"title": "Mic Polar - BE_Spectrum #2"}, "path": str(source)},
                    ],
                    "summary_file": str(root / "summary.json"),
                },
            ):
                with self.assertRaises(VacsExportPipelineError) as ctx:
                    run_vacs_export_specs(
                        executable="C:\\Tools\\VACS\\vacsviewer_32.exe",
                        vacs_version="default",
                        project_id="P001",
                        batch_id="B001",
                        version_id="V001",
                        abec_path=root / "Project.abec",
                        export_specs=specs,
                        export_dir=root / "exports",
                        log_dir=root / "logs",
                        akabak_executable="C:\\Tools\\AKABAK\\AKABAK.exe",
                        allow_graph_kind_fallback=True,
                    )
            self.assertIn("requested graph families", str(ctx.exception))
            self.assertIn("impedance", str(ctx.exception))

    def test_external_any_graph_fallback_includes_orientation_token_in_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source = root / "raw_graph_h.txt"
            source.write_text(
                "\n".join(
                    [
                        "SourceDesc=VACS_Data_Text",
                        "Data_LevelType=SoundPressure",
                        "Data_Legend='Mic Polar - BE_Spectrum #2'",
                        "Param_Coord_x3=0",
                        "StartString_Data=Data",
                        "EndString_Data=Data_End",
                        "Data",
                        "100 1.0 0.0",
                        "Data_End",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            spec = ExportSpec(id="only_one_requested", tool="vacs", graph_kind="spl", format="txt")
            with patch(
                "app.vacs_export_pipeline._run_external_vacs_export_save_all",
                return_value={
                    "ok": True,
                    "run_id": "run_x",
                    "exported_files": [
                        {"graph": {"title": "Mic Polar - BE_Spectrum #2"}, "path": str(source)},
                    ],
                    "summary_file": str(root / "summary.json"),
                },
            ):
                result = run_vacs_export_specs(
                    executable="C:\\Tools\\VACS\\vacsviewer_32.exe",
                    vacs_version="default",
                    project_id="P001",
                    batch_id="B001",
                    version_id="V001",
                    abec_path=root / "Project.abec",
                    export_specs=[spec],
                    export_dir=root / "exports",
                    log_dir=root / "logs",
                    akabak_executable="C:\\Tools\\AKABAK\\AKABAK.exe",
                    allow_graph_kind_fallback=True,
                )
            self.assertTrue(result["executed"])
            output_path = Path(str(result["exports"][0]["output_path"]))
            self.assertIn("_H.txt", output_path.name)
            details = dict(result["exports"][0].get("details", {}) or {})
            self.assertEqual(str(details.get("source_orientation_token", "")), "H")


if __name__ == "__main__":
    unittest.main()
