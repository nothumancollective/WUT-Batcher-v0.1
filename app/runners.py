"""External tool runner wrappers for ATH, AKABAK and VACS."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import ctypes
import math
import re
import os
import subprocess
from typing import Iterable, List, Optional, Sequence


_ATH_DIM_RE = re.compile(
    r"(?i)\b(length|width|height)\b[^0-9\-+]*([-+]?\d+(?:[.,]\d+)?)"
)
_ATH_DIM_CONTEXT_RE = re.compile(r"(?i)\b(final|dimension|dimensions|overall|result)\b")
_ATH_DIM_WIDTH_HEIGHT_PAIR_RE = re.compile(
    r"(?i)\b(?:device|final)\s+width\s*x\s*height\s*=\s*([-+]?\d+(?:[.,]\d+)?)\s*x\s*([-+]?\d+(?:[.,]\d+)?)\s*(mm|m)\b"
)
_ATH_DIM_LENGTH_LINE_RE = re.compile(
    r"(?i)\b(?:device|final)\s+length\s*=\s*([-+]?\d+(?:[.,]\d+)?)\s*(mm|m)\b"
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class RunnerResult:
    tool: str
    command: List[str]
    started_at: str
    finished_at: str
    attempts: int
    exit_code: int
    timed_out: bool
    stdout_log: str
    stderr_log: str
    summary_log: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


@dataclass(frozen=True)
class AthDimensions:
    horn_length_mm: Optional[float]
    horn_width_mm: Optional[float]
    horn_height_mm: Optional[float]
    raw_line: str


def _parse_ath_mm_value(raw_value: str, unit: str | None = None) -> Optional[float]:
    try:
        value = float(str(raw_value).replace(",", "."))
    except ValueError:
        return None
    if not math.isfinite(value):
        return None
    unit_token = str(unit or "").strip().lower()
    if unit_token == "m":
        return value * 1000.0
    return value


def parse_ath_dimensions(stdout_text: str) -> AthDimensions:
    context_values: dict[str, Optional[float]] = {"length": None, "width": None, "height": None}
    fallback_values: dict[str, Optional[float]] = {"length": None, "width": None, "height": None}
    context_lines: List[str] = []
    fallback_lines: List[str] = []
    for line in stdout_text.splitlines():
        stripped = line.strip()
        has_context_hint = bool(_ATH_DIM_CONTEXT_RE.search(line))
        updated_context = False
        updated_fallback = False
        width_height_match = _ATH_DIM_WIDTH_HEIGHT_PAIR_RE.search(line)
        if width_height_match is not None:
            width_mm = _parse_ath_mm_value(width_height_match.group(1), width_height_match.group(3))
            height_mm = _parse_ath_mm_value(width_height_match.group(2), width_height_match.group(3))
            if width_mm is not None:
                if has_context_hint:
                    context_values["width"] = width_mm
                    updated_context = True
                else:
                    fallback_values["width"] = width_mm
                    updated_fallback = True
            if height_mm is not None:
                if has_context_hint:
                    context_values["height"] = height_mm
                    updated_context = True
                else:
                    fallback_values["height"] = height_mm
                    updated_fallback = True

        length_line_match = _ATH_DIM_LENGTH_LINE_RE.search(line)
        if length_line_match is not None:
            length_mm = _parse_ath_mm_value(length_line_match.group(1), length_line_match.group(2))
            if length_mm is not None:
                if has_context_hint:
                    context_values["length"] = length_mm
                    updated_context = True
                else:
                    fallback_values["length"] = length_mm
                    updated_fallback = True

        if width_height_match is not None or length_line_match is not None:
            if stripped and updated_context:
                context_lines.append(stripped)
            elif stripped and updated_fallback:
                fallback_lines.append(stripped)
            continue

        line_matches = list(_ATH_DIM_RE.finditer(line))
        if not line_matches:
            continue
        for match in line_matches:
            label_start = int(match.start(1))
            if label_start > 0 and line[label_start - 1] == ".":
                # Ignore parameter-path echoes like "GCurve.Width".
                continue
            label = match.group(1).lower()
            value = _parse_ath_mm_value(match.group(2))
            if value is None:
                continue
            if label not in context_values:
                continue
            if has_context_hint:
                context_values[label] = value
                updated_context = True
            else:
                fallback_values[label] = value
                updated_fallback = True
        if stripped and updated_context:
            context_lines.append(stripped)
        elif stripped and updated_fallback:
            fallback_lines.append(stripped)

    merged_values = {
        key: (context_values.get(key) if context_values.get(key) is not None else fallback_values.get(key))
        for key in ("length", "width", "height")
    }
    length = merged_values.get("length")
    width = merged_values.get("width")
    height = merged_values.get("height")
    source_lines = context_lines if context_lines else fallback_lines
    raw = " | ".join(source_lines[-3:]) if source_lines else ""
    return AthDimensions(
        horn_length_mm=length,
        horn_width_mm=width,
        horn_height_mm=height,
        raw_line=raw,
    )


class _SubprocessRunner:
    def __init__(
        self,
        tool_name: str,
        executable: str | Path,
        *,
        default_timeout_s: int = 300,
        default_retries: int = 1,
        base_args: Sequence[str] | None = None,
    ) -> None:
        self.tool_name = tool_name
        self.executable = str(executable)
        self.default_timeout_s = max(1, int(default_timeout_s))
        self.default_retries = max(1, int(default_retries))
        self.base_args = list(base_args or [])

    def run(
        self,
        args: Iterable[str],
        *,
        version_logs_dir: str | Path,
        workdir: str | Path | None = None,
        timeout_s: int | None = None,
        retries: int | None = None,
        log_prefix: str | None = None,
    ) -> RunnerResult:
        command = [self.executable, *self.base_args, *list(args)]
        logs_dir = Path(version_logs_dir)
        logs_dir.mkdir(parents=True, exist_ok=True)
        prefix = log_prefix or self.tool_name.lower()

        stdout_log = logs_dir / f"{prefix}.stdout.log"
        stderr_log = logs_dir / f"{prefix}.stderr.log"
        summary_log = logs_dir / f"{prefix}.runner.log"
        stdout_log.write_text("", encoding="utf-8")
        stderr_log.write_text("", encoding="utf-8")
        summary_log.write_text("", encoding="utf-8")

        effective_timeout = timeout_s if timeout_s is not None else self.default_timeout_s
        effective_retries = retries if retries is not None else self.default_retries
        effective_retries = max(1, int(effective_retries))

        started_at = _now_iso()
        last_exit_code = -1
        timed_out = False

        for attempt in range(1, effective_retries + 1):
            attempt_started = _now_iso()
            try:
                popen_kwargs = {
                    "cwd": str(workdir) if workdir else None,
                    "timeout": effective_timeout,
                    "capture_output": True,
                    "text": True,
                    "encoding": "utf-8",
                    "errors": "replace",
                    "check": False,
                }
                proc = run_process_with_tree_timeout(
                    command,
                    **popen_kwargs,
                )
                last_exit_code = int(proc.returncode)
                stdout_log.write_text(
                    stdout_log.read_text(encoding="utf-8")
                    + f"\n### attempt {attempt} @ {attempt_started}\n{proc.stdout}",
                    encoding="utf-8",
                )
                stderr_log.write_text(
                    stderr_log.read_text(encoding="utf-8")
                    + f"\n### attempt {attempt} @ {attempt_started}\n{proc.stderr}",
                    encoding="utf-8",
                )
                summary_log.write_text(
                    summary_log.read_text(encoding="utf-8")
                    + f"[{attempt_started}] attempt={attempt} exit_code={last_exit_code}\n",
                    encoding="utf-8",
                )
                if last_exit_code == 0:
                    break
            except subprocess.TimeoutExpired as exc:
                timed_out = True
                timeout_stdout = exc.stdout or ""
                timeout_stderr = exc.stderr or ""
                stdout_log.write_text(
                    stdout_log.read_text(encoding="utf-8")
                    + f"\n### attempt {attempt} @ {attempt_started} (timeout)\n{timeout_stdout}",
                    encoding="utf-8",
                )
                stderr_log.write_text(
                    stderr_log.read_text(encoding="utf-8")
                    + f"\n### attempt {attempt} @ {attempt_started} (timeout)\n{timeout_stderr}",
                    encoding="utf-8",
                )
                summary_log.write_text(
                    summary_log.read_text(encoding="utf-8")
                    + f"[{attempt_started}] attempt={attempt} timeout after {effective_timeout}s\n",
                    encoding="utf-8",
                )
                last_exit_code = -1

        finished_at = _now_iso()
        return RunnerResult(
            tool=self.tool_name,
            command=command,
            started_at=started_at,
            finished_at=finished_at,
            attempts=effective_retries,
            exit_code=last_exit_code,
            timed_out=timed_out,
            stdout_log=str(stdout_log),
            stderr_log=str(stderr_log),
            summary_log=str(summary_log),
        )


class _WindowsKillOnCloseJob:
    """Own a Windows job whose complete process tree dies when the handle closes."""

    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9

    def __init__(self) -> None:
        from ctypes import wintypes

        class _IoCounters(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class _BasicLimitInformation(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class _ExtendedLimitInformation(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", _BasicLimitInformation),
                ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self._kernel32 = kernel32
        self._handle = handle
        limits = _ExtendedLimitInformation()
        limits.BasicLimitInformation.LimitFlags = self._JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
            handle,
            self._JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            error = ctypes.get_last_error()
            self.close()
            raise ctypes.WinError(error)

    def assign(self, process_handle: int) -> None:
        if not self._handle or not self._kernel32.AssignProcessToJobObject(self._handle, process_handle):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self) -> None:
        handle = getattr(self, "_handle", None)
        if handle:
            self._handle = None
            self._kernel32.CloseHandle(handle)


def run_process_with_tree_timeout(
    command: Sequence[str],
    *,
    cwd: str | None,
    timeout: int,
    capture_output: bool,
    text: bool,
    encoding: str,
    errors: str,
    check: bool,
    env: Optional[dict[str, str]] = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command and guarantee bounded full-tree cleanup on timeout."""

    if not capture_output:
        raise ValueError("capture_output must be True for runner logging")
    popen_kwargs = {
        "cwd": cwd,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": text,
        "encoding": encoding,
        "errors": errors,
        "env": env,
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    else:
        popen_kwargs["start_new_session"] = True

    proc = subprocess.Popen(list(command), **popen_kwargs)
    windows_job: Optional[_WindowsKillOnCloseJob] = None
    if os.name == "nt":
        try:
            windows_job = _WindowsKillOnCloseJob()
            windows_job.assign(int(proc._handle))  # type: ignore[attr-defined]
        except OSError:
            if windows_job is not None:
                windows_job.close()
            windows_job = None
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        if windows_job is not None:
            windows_job.close()
            windows_job = None
        else:
            _terminate_process_tree(proc.pid)
        timeout_stdout = ""
        timeout_stderr = ""
        try:
            timeout_stdout, timeout_stderr = proc.communicate(timeout=5)
        except Exception:
            timeout_stdout = str(exc.stdout or "")
            timeout_stderr = str(exc.stderr or "")
        raise subprocess.TimeoutExpired(
            cmd=list(command),
            timeout=timeout,
            output=timeout_stdout,
            stderr=timeout_stderr,
        )
    finally:
        if windows_job is not None:
            windows_job.close()

    completed = subprocess.CompletedProcess(
        args=list(command),
        returncode=int(proc.returncode or 0),
        stdout=str(stdout or ""),
        stderr=str(stderr or ""),
    )
    if check and completed.returncode != 0:
        raise subprocess.CalledProcessError(
            returncode=completed.returncode,
            cmd=completed.args,
            output=completed.stdout,
            stderr=completed.stderr,
        )
    return completed


def _terminate_process_tree(pid: int) -> None:
    if int(pid) <= 0:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(int(pid)), "/T", "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
        return
    try:
        os.killpg(int(pid), 9)
    except Exception:
        try:
            os.kill(int(pid), 9)
        except Exception:
            pass


class AthRunner(_SubprocessRunner):
    def __init__(self, executable: str | Path, *, base_args: Sequence[str] | None = None) -> None:
        super().__init__(
            "ATH",
            executable,
            default_timeout_s=180,
            default_retries=2,
            base_args=base_args,
        )

    def run_cfg(
        self,
        cfg_path: str | Path,
        *,
        version_logs_dir: str | Path,
        workdir: str | Path | None = None,
    ) -> RunnerResult:
        return self.run(
            [str(cfg_path)],
            version_logs_dir=version_logs_dir,
            workdir=workdir,
            log_prefix="ath",
        )


class AkabakRunner(_SubprocessRunner):
    def __init__(self, executable: str | Path, *, base_args: Sequence[str] | None = None) -> None:
        super().__init__(
            "AKABAK",
            executable,
            default_timeout_s=600,
            default_retries=2,
            base_args=base_args,
        )

    def run_project(
        self,
        abec_project: str | Path,
        *,
        version_logs_dir: str | Path,
        workdir: str | Path | None = None,
        timeout_s: int | None = None,
    ) -> RunnerResult:
        return self.run(
            [str(abec_project)],
            version_logs_dir=version_logs_dir,
            workdir=workdir,
            timeout_s=timeout_s,
            log_prefix="akabak",
        )


class VacsRunner(_SubprocessRunner):
    def __init__(self, executable: str | Path, *, base_args: Sequence[str] | None = None) -> None:
        super().__init__(
            "VACS",
            executable,
            default_timeout_s=600,
            default_retries=2,
            base_args=base_args,
        )

    def run_export(
        self,
        project_or_abec: str | Path,
        *,
        version_logs_dir: str | Path,
        workdir: str | Path | None = None,
    ) -> RunnerResult:
        return self.run(
            [str(project_or_abec)],
            version_logs_dir=version_logs_dir,
            workdir=workdir,
            log_prefix="vacs",
        )
