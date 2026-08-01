from __future__ import annotations

from argparse import Namespace
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.vacs_export_save_all import (
    _register_owned_vacs_pid,
    _terminate_vacs_pids,
    run_once_fast,
)


class VacsExportSaveAllProcessTests(unittest.TestCase):
    def test_register_owned_pid_deduplicates_explicit_ids(self) -> None:
        args = Namespace()

        _register_owned_vacs_pid(args, 13632)
        _register_owned_vacs_pid(args, 13632)
        _register_owned_vacs_pid(args, 0)

        self.assertEqual(args._owned_vacs_pids, {13632})

    def test_cleanup_targets_exact_pid_without_image_kill(self) -> None:
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="SUCCESS", stderr="")
        with (
            patch(
                "scripts.vacs_export_save_all._running_vacs_pids",
                side_effect=[[13632, 19000], [19000]],
            ),
            patch("scripts.vacs_export_save_all.subprocess.run", return_value=completed) as run_mock,
        ):
            result = _terminate_vacs_pids([13632])

        self.assertEqual(result["terminated"], [13632])
        command = run_mock.call_args.args[0]
        self.assertEqual(command[:3], ["taskkill", "/PID", "13632"])
        self.assertNotIn("/IM", command)

    def test_standalone_fast_mode_blocks_contaminated_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            args = Namespace(
                export_dir=str(root / "exports"),
                output_dir=str(root / "logs"),
                assume_vacs_ready=False,
                vacs_exe="VACS.exe",
            )
            with (
                patch("scripts.vacs_export_save_all._running_vacs_pids", return_value=[444]),
                patch("scripts.vacs_export_save_all.subprocess.Popen") as popen_mock,
            ):
                result = run_once_fast(args)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "preexisting_vacs_processes_not_owned")
        self.assertEqual(result["preexisting_vacs_pids"], [444])
        popen_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
