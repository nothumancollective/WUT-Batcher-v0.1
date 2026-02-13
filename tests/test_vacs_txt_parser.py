from __future__ import annotations

from pathlib import Path
import unittest

from app.vacs_txt_parser import parse_vacs_txt_file


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "vacs"


class VacsTxtParserTests(unittest.TestCase):
    def test_parses_keyvalue_data_block_export(self) -> None:
        parsed = parse_vacs_txt_file(FIXTURES / "result_v001spl.txt")
        self.assertEqual(parsed.graph_type, "SPL")
        self.assertEqual(parsed.x_name, "Frequency")
        self.assertEqual(parsed.x_unit, "Hz")
        self.assertEqual(parsed.y_name, "SPL")
        self.assertEqual(parsed.y_unit, "dB")
        self.assertEqual(len(parsed.points), 2)
        self.assertEqual(parsed.points[0], (100.0, 90.5))
        self.assertEqual(parsed.points[1], (200.0, 91.25))

    def test_parses_semicolon_export_with_locale_decimals(self) -> None:
        parsed = parse_vacs_txt_file(FIXTURES / "result_v001imp.txt")
        self.assertEqual(parsed.graph_type, "IMP")
        self.assertEqual(parsed.x_name, "Frequency")
        self.assertEqual(parsed.x_unit, "Hz")
        self.assertEqual(parsed.y_name, "Impedance")
        self.assertEqual(parsed.y_unit, "Ohm")
        self.assertEqual(len(parsed.points), 3)
        self.assertEqual(parsed.points[0], (100.0, 6.5))
        self.assertEqual(parsed.points[1], (200.0, 7.1))
        self.assertEqual(parsed.points[2], (300.0, 8.25))

    def test_parses_polar_export_into_angle_series(self) -> None:
        parsed = parse_vacs_txt_file(FIXTURES / "result_v001polar.txt")
        self.assertEqual(parsed.graph_type, "POLAR_SPL")
        self.assertEqual(len(parsed.series), 3)
        self.assertEqual(parsed.series[0].angle_deg, 0.0)
        self.assertEqual(parsed.series[1].angle_deg, 30.0)
        self.assertEqual(parsed.series[2].angle_deg, 60.0)
        self.assertEqual(len(parsed.series[0].points), 5)
        self.assertEqual(parsed.series[0].points[0].x_value, 100.0)
        self.assertEqual(parsed.series[0].points[0].y_value, 90.0)
        self.assertEqual(int(parsed.export_meta["series_count"]), 3)
        self.assertEqual(int(parsed.export_meta["point_count"]), 15)

    def test_parses_complex_points_with_imag_part(self) -> None:
        parsed = parse_vacs_txt_file(FIXTURES / "result_v001polar_complex.txt")
        self.assertEqual(parsed.graph_type, "POLAR_PRESSURE_COMPLEX")
        self.assertEqual(len(parsed.series), 2)
        first = parsed.series[0].points[0]
        self.assertEqual(first.x_value, 100.0)
        self.assertEqual(first.y_value, 1.0)
        self.assertEqual(first.y_imag, 0.1)
        self.assertTrue(bool(parsed.export_meta["contains_complex"]))


if __name__ == "__main__":
    unittest.main()

