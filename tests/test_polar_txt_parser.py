from pathlib import Path
import tempfile
import unittest

from app.polar_txt_parser import (
    PolarTxtParseError,
    normalize_orientation_marker,
    parse_polar_legacy_complex_txt,
)


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "vacs"


class PolarTxtParserTests(unittest.TestCase):
    def test_parses_small_legacy_complex_matrix(self) -> None:
        parsed = parse_polar_legacy_complex_txt(FIXTURES / "result_v001polar_matrix_small.txt")
        self.assertEqual(parsed.angles_deg, [0.0, 30.0, 60.0])
        self.assertEqual(parsed.orientation_raw, 42.0)
        self.assertEqual(len(parsed.rows), 2)
        self.assertEqual(parsed.rows[0].freq_hz, 100.0)
        self.assertEqual(parsed.rows[0].re_values, [1.0, 2.0, 3.0])
        self.assertEqual(parsed.rows[0].im_values, [0.1, 0.2, 0.3])

    def test_parses_19_angle_shape(self) -> None:
        parsed = parse_polar_legacy_complex_txt(FIXTURES / "result_v001polar_matrix_19angles.txt")
        self.assertEqual(len(parsed.angles_deg), 19)
        self.assertEqual(parsed.angles_deg[0], 0.0)
        self.assertEqual(parsed.angles_deg[-1], 90.0)
        self.assertEqual(parsed.orientation_raw, 90.0)
        self.assertEqual(len(parsed.rows), 2)
        self.assertEqual(len(parsed.rows[0].re_values), 19)
        self.assertEqual(len(parsed.rows[0].im_values), 19)

    def test_orientation_mapping(self) -> None:
        self.assertEqual(normalize_orientation_marker(0.0), "H")
        self.assertEqual(normalize_orientation_marker(90.0), "V")
        self.assertEqual(normalize_orientation_marker(42.0), "D")
        self.assertEqual(normalize_orientation_marker(17.5), "X3_17.5")

    def test_raises_on_wrong_row_width(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "bad_polar.txt"
            path.write_text(
                "\n".join(
                    [
                        "StartString_Data=Data",
                        "EndString_Data=Data_End",
                        "Data_Format=Complex",
                        "Param_Coord_x2='0,30,60'",
                        "Param_Coord_x3=0",
                        "Data",
                        "100 1.0 0.1 2.0 0.2 3.0",
                        "Data_End",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(PolarTxtParseError):
                parse_polar_legacy_complex_txt(path)


if __name__ == "__main__":
    unittest.main()
