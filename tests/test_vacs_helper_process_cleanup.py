from __future__ import annotations

from argparse import Namespace
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.vacs_export_dialog_rounds import run_round
from scripts.vacs_interim_reimport import _kill_vacs_pid


class VacsHelperProcessCleanupTests(unittest.TestCase):
    def test_interim_cleanup_targets_exact_pid(self) -> None:
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with patch("scripts.vacs_interim_reimport.subprocess.run", return_value=completed) as run_mock:
            _kill_vacs_pid(8640)

        command = run_mock.call_args.args[0]
        self.assertEqual(command[:3], ["taskkill", "/PID", "8640"])
        self.assertNotIn("/IM", command)

    def test_dialog_round_blocks_preexisting_vacs(self) -> None:
        args = Namespace(vacs_exe="VACS.exe")
        recipe = {"round_id": "baseline", "note": "test"}
        with tempfile.TemporaryDirectory() as tmp_dir:
            with (
                patch("scripts.vacs_export_dialog_rounds._running_vacs_pids", return_value=[444]),
                patch("scripts.vacs_export_dialog_rounds._start_vacs") as start_mock,
            ):
                result = run_round(args, recipe, Path(tmp_dir))

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "preexisting_vacs_processes_not_owned")
        self.assertEqual(result["preexisting_vacs_pids"], [444])
        start_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
