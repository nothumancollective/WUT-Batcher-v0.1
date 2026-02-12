from __future__ import annotations

import unittest

from app.compat_engine import _extract_values, _parse_action, _safe_eval_when


class CompatEngineDslTests(unittest.TestCase):
    def test_operator_precedence_and_negation(self) -> None:
        values = {"B": 1}
        self.assertFalse(_safe_eval_when("isDefined(A) || isDefined(B) && isDefined(C)", values))
        self.assertTrue(_safe_eval_when("!isDefined(A) && isDefined(B)", values))

    def test_dotted_keys_and_missing_keys_are_deterministic(self) -> None:
        values = {"Source.Shape": 1}
        self.assertTrue(_safe_eval_when("isDefined(Source.Shape)", values))
        self.assertFalse(_safe_eval_when("isDefined(Source.Radius)", values))
        self.assertFalse(_safe_eval_when("Source.Radius == 1", values))

    def test_warn_action_supports_escaped_quotes(self) -> None:
        parsed = _parse_action(r'warn("He said \"hello\".")')
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed[0], "warn")
        self.assertEqual(parsed[1], r'He said \"hello\".')

    def test_numeric_parsing_is_deterministic(self) -> None:
        self.assertTrue(_safe_eval_when("1.5 > 1 && -2 < -1", {}))
        self.assertFalse(_safe_eval_when("1,5 > 1", {}))

    def test_denylist_blocks_unknown_functions_and_attribute_access(self) -> None:
        self.assertFalse(_safe_eval_when('__import__("os").system("dir") == 0', {}))
        self.assertFalse(_safe_eval_when("isDefined.__class__", {}))

    def test_is_defined_respects_unset_param_state(self) -> None:
        values = _extract_values(
            {
                "fixed_params": {"Length": 120},
                "param_states": [
                    {"param_name": "GCurve.Dist", "is_set": 0, "value": 10},
                    {"param_name": "GCurve.Width", "is_set": 1, "value": 20},
                ],
            }
        )
        self.assertFalse(_safe_eval_when("isDefined(GCurve.Dist)", values))
        self.assertTrue(_safe_eval_when("isDefined(GCurve.Width)", values))


if __name__ == "__main__":
    unittest.main()
