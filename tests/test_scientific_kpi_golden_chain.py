from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import tempfile
import unittest

from app.analyzer.cache import AnalyzerCachePolicy, AnalyzerPlotCache
from app.analyzer.kpi_engine import compute_run_kpis, compute_stage_score
from app.analyzer.plot_service import AnalyzerPlotService
from app.analyzer.presets import ALGO_VERSION
from app.gui import AnalysePage, VERSION_INFO_METRIC_META
from app.models import Batch, Project, ProjectConstraints, VersionSpec
from app.polar_txt_parser import parse_polar_legacy_complex_txt
from app.tidy_dataset import TidyDatasetWriter
from app.vacs_txt_parser import parse_vacs_txt_file


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "scientific_validation"
ANGLES = [-30.0, -20.0, -10.0, 0.0, 10.0, 20.0, 30.0]
FREQUENCIES = [1000.0, 2000.0]
TARGET_H = 34.0
TARGET_V = 26.0
TOLERANCE = 5.0

# Literal source values are independent of the production parser and KPI code.
MAGNITUDES = {
    "H": [[1.0, 4.0, 8.0, 10.0, 8.0, 4.0, 1.0], [2.0, 8.0, 16.0, 20.0, 16.0, 8.0, 2.0]],
    "V": [[1.2, 3.6, 7.2, 12.0, 7.2, 3.6, 1.2], [1.8, 5.4, 10.8, 18.0, 10.8, 5.4, 1.8]],
    "D": [[1.5, 5.0, 10.0, 15.0, 10.0, 5.0, 1.5], [3.0, 10.0, 20.0, 30.0, 20.0, 10.0, 3.0]],
}
ORIENTATION_RAW = {"H": 0.0, "V": 90.0, "D": 45.0}
FIXTURE_NAME = {"H": "golden_polar_h.txt", "V": "golden_polar_v.txt", "D": "golden_polar_d.txt"}


def _complex_samples(plane: str) -> list[list[complex]]:
    return [
        [complex(round(0.6 * value, 12), round(0.8 * value, 12)) for value in row]
        for row in MAGNITUDES[plane]
    ]


def _db(value: complex) -> float:
    return 20.0 * math.log10(abs(value))


def _crossing(angles: list[float], normalized: list[float]) -> float:
    pivot = angles.index(0.0)
    left = right = None
    for index in range(pivot, len(angles) - 1):
        if normalized[index] >= -6.0 > normalized[index + 1]:
            ratio = (-6.0 - normalized[index]) / (normalized[index + 1] - normalized[index])
            right = angles[index] + ratio * (angles[index + 1] - angles[index])
            break
    for index in range(pivot, 0, -1):
        if normalized[index] >= -6.0 > normalized[index - 1]:
            ratio = (-6.0 - normalized[index]) / (normalized[index - 1] - normalized[index])
            left = angles[index] + ratio * (angles[index - 1] - angles[index])
            break
    assert left is not None and right is not None
    return right - left


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _rms(values: list[float]) -> float:
    return math.sqrt(_mean([value * value for value in values]))


def _plane_reference(plane: str) -> dict[str, float | list[float]]:
    target = TARGET_H if plane == "H" else TARGET_V if plane == "V" else (TARGET_H + TARGET_V) / 2.0
    widths: list[float] = []
    coverages: list[float] = []
    spill: list[float] = []
    di_proxy: list[float] = []
    smoothness: list[float] = []
    ripple: list[float] = []
    for samples in _complex_samples(plane):
        absolute = [_db(value) for value in samples]
        reference = absolute[ANGLES.index(0.0)]
        normalized = [value - reference for value in absolute]
        widths.append(_crossing(ANGLES, normalized))
        inside = [value for angle, value in zip(ANGLES, normalized) if abs(angle) <= target * 0.5]
        outside = [value for angle, value in zip(ANGLES, normalized) if abs(angle) > target * 0.5]
        inside_mean = _mean(inside)
        coverages.append(_rms([value - inside_mean for value in inside]))
        inside_power = _mean([10.0 ** (value / 10.0) for value in inside])
        outside_power = _mean([10.0 ** (value / 10.0) for value in outside])
        spill.append(outside_power / inside_power)
        local = [value for angle, value in zip(ANGLES, absolute) if abs(angle) <= 10.0]
        di_proxy.append(_mean(local) - _mean(absolute))
        smooth_samples = [(angle, value) for angle, value in zip(ANGLES, absolute) if abs(angle) <= target * 0.5]
        gradients = [
            (smooth_samples[index + 1][1] - smooth_samples[index][1])
            / (smooth_samples[index + 1][0] - smooth_samples[index][0])
            for index in range(len(smooth_samples) - 1)
        ]
        smoothness.append(_rms(gradients))
        off_indices = sorted({min(range(len(ANGLES)), key=lambda i: abs(ANGLES[i] - wanted)) for wanted in (-60, -45, -30, 30, 45, 60)})
        off_values = [absolute[index] for index in off_indices]
        ripple.append(max(off_values) - min(off_values))
    in_tolerance = [abs(width - target) <= TOLERANCE for width in widths]
    pass_octaves = math.log2(FREQUENCIES[-1] / FREQUENCIES[0]) if all(in_tolerance) else 0.0
    return {
        "target": target,
        "widths": widths,
        "e_bw": _mean([abs(width - target) for width in widths]),
        "b_pc_oct": pass_octaves,
        "e_cov": _mean(coverages),
        "r_spill": _mean(spill),
        "di_proxy": _mean(di_proxy),
        "di_curve": di_proxy,
        "s_theta": _mean(smoothness),
        "r_off": _mean(ripple),
    }


def _weighted(values: dict[str, float]) -> float:
    return 0.45 * values["H"] + 0.45 * values["V"] + 0.10 * values["D"]


def _reference_payload() -> tuple[dict[str, dict[str, float | list[float]]], dict[str, float], float]:
    planes = {plane: _plane_reference(plane) for plane in "HVD"}
    aggregate = {
        key: _weighted({plane: float(planes[plane][key]) for plane in "HVD"})
        for key in ("e_bw", "b_pc_oct", "e_cov", "r_spill", "di_proxy", "s_theta", "r_off")
    }
    e_sym_by_freq = []
    for freq_index in range(len(FREQUENCIES)):
        values = [float(planes[plane]["di_curve"][freq_index]) for plane in "HVD"]  # type: ignore[index]
        mean_value = _mean(values)
        e_sym_by_freq.append(_rms([value - mean_value for value in values]))
    aggregate["e_sym_shape"] = _mean(e_sym_by_freq)
    bpc_norm = min(max(aggregate["b_pc_oct"] / 3.0, 0.0), 1.0)
    ebw_norm = min(max(1.0 - aggregate["e_bw"] / 20.0, 0.0), 1.0)
    ecov_norm = min(max(1.0 - aggregate["e_cov"] / 6.0, 0.0), 1.0)
    spill_db = 10.0 * math.log10(max(aggregate["r_spill"], 1.0e-12))
    spill_norm = min(max((5.0 - spill_db) / 20.0, 0.0), 1.0)
    score = round((0.30 * bpc_norm + 0.30 * ebw_norm + 0.18 * ecov_norm + 0.14 * spill_norm + 0.08) * 100.0, 2)
    return planes, aggregate, score


class ScientificKpiGoldenChainTests(unittest.TestCase):
    def test_raw_txt_to_sql_analyzer_kpis_and_gui_display(self) -> None:
        reference_planes, reference_aggregate, reference_score = _reference_payload()
        with tempfile.TemporaryDirectory(prefix="wut_phase2_kpi_golden_") as tmp:
            project_root = Path(tmp) / "library" / "P_GOLDEN"
            project_root.mkdir(parents=True)
            writer = TidyDatasetWriter(project_root, library_root=project_root.parent)
            project = Project(
                project_id="P_GOLDEN",
                name="Scientific KPI Golden",
                root_path=str(project_root),
                constraints=ProjectConstraints(project_id="P_GOLDEN"),
            )
            batch = Batch(batch_id="B_GOLDEN", project_id="P_GOLDEN")
            version = VersionSpec(
                project_id="P_GOLDEN",
                batch_id="B_GOLDEN",
                version_id="V001",
                sweep_mode="single",
                sequence_index=1,
                parameters={"Length": 60.0},
            )
            writer.write_plan_bundle(project=project, batch=batch, versions=[version])
            points_by_plane: dict[str, list[dict[str, float | int]]] = {}
            fixture_hashes: dict[str, str] = {}
            for plane in "HVD":
                path = FIXTURE_ROOT / FIXTURE_NAME[plane]
                fixture_hashes[plane] = hashlib.sha256(path.read_bytes()).hexdigest()
                parsed = parse_polar_legacy_complex_txt(path)
                self.assertEqual(parsed.angles_deg, ANGLES)
                self.assertEqual(parsed.freq_values, FREQUENCIES)
                self.assertEqual(parsed.orientation_raw, ORIENTATION_RAW[plane])
                expected = _complex_samples(plane)
                points: list[dict[str, float | int]] = []
                for freq_index, row in enumerate(parsed.rows):
                    for angle_index, angle in enumerate(ANGLES):
                        self.assertEqual(row.re_values[angle_index], expected[freq_index][angle_index].real)
                        self.assertEqual(row.im_values[angle_index], expected[freq_index][angle_index].imag)
                        points.append(
                            {
                                "freq_index": freq_index,
                                "angle_index": angle_index,
                                "freq_hz": row.freq_hz,
                                "angle_deg": angle,
                                "re": row.re_values[angle_index],
                                "im": row.im_values[angle_index],
                            }
                        )
                points_by_plane[plane] = points
                writer.write_polar_measurement(
                    measurement={
                        "project_id": "P_GOLDEN", "batch_id": "B_GOLDEN", "version_id": "V001", "run_id": "R_GOLDEN",
                        "orientation": plane, "orientation_raw": ORIENTATION_RAW[plane], "norm_angle_deg": 10.0,
                        "data_level_type": "SoundPressure", "data_base_unit": "Pa", "data_absc_unit": "Hz",
                        "freq_min_hz": 1000.0, "freq_max_hz": 2000.0, "freq_count": 2,
                        "angle_min_deg": -30.0, "angle_max_deg": 30.0, "angle_step_deg": 10.0, "angle_count": 7,
                        "angles_deg_json": json.dumps(ANGLES), "source_file": path.name, "file_hash": fixture_hashes[plane],
                        "export_meta_json": json.dumps(parsed.metadata, sort_keys=True),
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    },
                    points=points,
                )

            impedance_path = FIXTURE_ROOT / "golden_impedance.txt"
            impedance = parse_vacs_txt_file(impedance_path, default_graph_type="impedance")
            self.assertEqual(str(impedance.export_meta["metadata"]["Data_LevelType"]), "Impedance10")
            self.assertEqual([(p.x_value, p.y_value, p.y_imag) for p in impedance.series[0].points], [(1000.0, 4.0, 3.0), (2000.0, 8.0, 6.0)])
            writer.write_measurements(
                [
                    {
                        "project_id": "P_GOLDEN", "batch_id": "B_GOLDEN", "version_id": "V001", "run_id": "R_GOLDEN",
                        "graph_type": "impedance", "graph_kind": "impedance", "variant": "golden",
                        "x_name": "Frequency", "y_name": "Impedance", "x_unit": "Hz", "y_unit": "Ohm",
                        "source_file": impedance_path.name, "series_kind": "curve", "series_label": "impedance",
                        "point_index": index, "x_value": point.x_value, "y_value": point.y_value, "y_imag": point.y_imag,
                        "export_meta": impedance.export_meta,
                    }
                    for index, point in enumerate(impedance.series[0].points)
                ]
            )

            with closing(sqlite3.connect(str(writer.project_db_path))) as conn:
                conn.row_factory = sqlite3.Row
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM polar_measurements").fetchone()[0], 3)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM polar_points").fetchone()[0], 42)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM graphs WHERE graph_kind='impedance'").fetchone()[0], 1)
                db_rows = conn.execute(
                    "SELECT pm.orientation, pp.freq_hz, pp.angle_deg, pp.re, pp.im FROM polar_measurements pm JOIN polar_points pp ON pp.polar_id=pm.polar_id ORDER BY pm.orientation, pp.freq_hz, pp.angle_deg"
                ).fetchall()
            self.assertEqual(len(db_rows), 42)
            for row in db_rows:
                plane = str(row["orientation"])
                freq_index = FREQUENCIES.index(float(row["freq_hz"]))
                angle_index = ANGLES.index(float(row["angle_deg"]))
                expected = _complex_samples(plane)[freq_index][angle_index]
                self.assertLessEqual(abs(float(row["re"]) - expected.real), 1.0e-12)
                self.assertLessEqual(abs(float(row["im"]) - expected.imag), 1.0e-12)

            cache = AnalyzerPlotCache(AnalyzerCachePolicy(mode="low", size_limit_mb=0, keep_last_n=1))
            plot = AnalyzerPlotService(cache).load_plane_plot_payload(
                db_path=writer.project_db_path, project_id="P_GOLDEN", batch_id="B_GOLDEN", run_id="R_GOLDEN",
                version_id="V001", plane="H", band_low_hz=1000.0, band_high_hz=2000.0,
            )
            self.assertEqual(plot["ref_angle_deg"], 10.0)
            self.assertEqual(plot["angles_deg"], ANGLES)
            h_samples = _complex_samples("H")
            for angle_index, _angle in enumerate(ANGLES):
                for freq_index, _freq in enumerate(FREQUENCIES):
                    expected_db = _db(h_samples[freq_index][angle_index]) - _db(h_samples[freq_index][ANGLES.index(10.0)])
                    self.assertLessEqual(abs(float(plot["matrix_db"][angle_index][freq_index]) - expected_db), 1.0e-10)

            planes_points = {plane: points_by_plane[plane] for plane in "HVD"}
            payload = compute_run_kpis(
                planes_points=planes_points, target_h_deg=TARGET_H, target_v_deg=TARGET_V,
                tol_deg=TOLERANCE, band_low_hz=1000.0, band_high_hz=2000.0,
            )
            for plane in "HVD":
                actual = payload["planes"][plane]
                expected = reference_planes[plane]
                for key in ("e_bw", "b_pc_oct", "e_cov", "r_spill"):
                    self.assertLessEqual(abs(float(actual[key]) - float(expected[key])), 1.0e-9, msg=f"{plane}.{key}")
                self.assertEqual(actual["flag_count"], 0)
                self.assertFalse(actual["insufficient_coverage"])
            for key in ("e_bw", "b_pc_oct", "e_cov", "r_spill", "di_proxy", "s_theta", "e_sym_shape", "r_off"):
                self.assertLessEqual(abs(float(payload["aggregate"][key]) - reference_aggregate[key]), 1.0e-9, msg=key)
            score = compute_stage_score(payload, stage_id="concept")
            self.assertEqual(score, reference_score)

            writer.write_analyzer_run_kpis(
                [{
                    "project_id": "P_GOLDEN", "batch_id": "B_GOLDEN", "run_id": "R_GOLDEN", "version_id": "V001",
                    "stage_mode": "concept", "band_low_hz": 1000.0, "band_high_hz": 2000.0,
                    "target_h_deg": TARGET_H, "target_v_deg": TARGET_V, "tol_deg": TOLERANCE,
                    "kpi_json": json.dumps(payload, sort_keys=True), "flags_json": json.dumps(payload["flags"], sort_keys=True),
                    "score": score, "algo_version": ALGO_VERSION, "source_hash": hashlib.sha256("".join(fixture_hashes.values()).encode()).hexdigest(),
                    "computed_at": datetime.now(timezone.utc).isoformat(),
                }]
            )
            with closing(sqlite3.connect(str(writer.project_db_path))) as conn:
                persisted = conn.execute("SELECT score, kpi_json FROM analyzer_run_kpis WHERE run_id='R_GOLDEN'").fetchone()
            self.assertIsNotNone(persisted)
            self.assertEqual(float(persisted[0]), reference_score)
            self.assertLessEqual(abs(float(json.loads(persisted[1])["aggregate"]["e_bw"]) - reference_aggregate["e_bw"]), 1.0e-9)

            self.assertEqual(VERSION_INFO_METRIC_META["e_bw"]["label"], "BW Error")
            score_text = AnalysePage._format_float(score, 2)
            e_bw_text = AnalysePage._format_float(payload["aggregate"]["e_bw"], 2)
            self.assertLessEqual(abs(float(score_text) - float(score)), 0.005)
            self.assertLessEqual(abs(float(e_bw_text) - float(reference_aggregate["e_bw"])), 0.005)


if __name__ == "__main__":
    unittest.main()
