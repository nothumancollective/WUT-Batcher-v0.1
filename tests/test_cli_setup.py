from __future__ import annotations

import argparse
import unittest
from unittest.mock import patch

from app import cli


class CliSetupTests(unittest.TestCase):
    def test_setup_parser_requires_explicit_yes_for_install(self) -> None:
        args = cli.build_parser().parse_args(["setup", "install-gmsh"])
        self.assertFalse(args.yes)

    def test_setup_install_without_yes_does_not_succeed(self) -> None:
        args = argparse.Namespace(yes=False, timeout_seconds=600)
        with patch(
            "app.setup_assistant.install_gmsh_with_winget",
            return_value={"status": "confirmation_required"},
        ) as install:
            with patch("builtins.print"):
                exit_code = cli.cmd_setup_install_gmsh(args)
        self.assertEqual(exit_code, 3)
        install.assert_called_once_with(confirmed=False, timeout_seconds=600)


if __name__ == "__main__":
    unittest.main()
