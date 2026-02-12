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


if __name__ == "__main__":
    unittest.main()

