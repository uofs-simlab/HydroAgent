"""Run subprocesses without unsafe fork() from multi-threaded Streamlit on macOS.

Streamlit is multi-threaded and may import geopandas/pyproj (PROJ SQLite cache).
fork() from that process triggers PROJ atfork handlers and can SIGSEGV before exec.

CPython ``subprocess.Popen`` only uses ``posix_spawn`` when *all* of these hold:
``cwd is None``, ``preexec_fn is None``, ``not close_fds``, ``not pass_fds``,
``not start_new_session``, etc. Using ``stdout=PIPE`` sets ``close_fds=True``,
which forces fork+exec even with ``cwd=None``. Streamlit also runs callbacks in
worker threads, so any fork from the app process is unsafe once PROJ is loaded.

On macOS we therefore call ``os.posix_spawn`` directly (no fork in the parent).
When a working directory is required, a tiny ``python -c`` helper ``chdir`` +
``execvp`` runs in the spawned child (single-threaded; safe if it forks again).
"""

from __future__ import annotations

import io
import json
import os
import signal
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

_DARWIN = sys.platform == "darwin"

_EXEC_WRAPPER = (
    "import json, os, sys\n"
    "payload = json.loads(sys.argv[1])\n"
    "os.chdir(payload['cwd'])\n"
    "os.execvp(payload['cmd'][0], payload['cmd'])\n"
)


def _merge_env(env: dict[str, str] | None) -> dict[str, str]:
    merged = os.environ.copy()
    merged["PROJ_DISABLE_CACHE"] = "ON"
    if env:
        merged.update(env)
    return merged


def _cmd_for_subprocess(
    cmd: list[str],
    cwd: Path | str | None,
) -> tuple[list[str], str | None]:
    """Return argv and popen cwd suitable for subprocess on this platform."""
    if not cwd:
        return cmd, None
    cwd_str = str(cwd)
    if _DARWIN:
        payload = json.dumps({"cmd": cmd, "cwd": cwd_str})
        wrapped = [sys.executable, "-c", _EXEC_WRAPPER, payload]
        return wrapped, None
    return cmd, cwd_str


def _posix_spawn_piped(cmd: list[str], env: dict[str, str]) -> tuple[int, int]:
    """Spawn ``cmd`` with stdout+stderr merged to a pipe; return (pid, read_fd)."""
    read_fd, write_fd = os.pipe()
    try:
        os.set_inheritable(read_fd, False)
        os.set_inheritable(write_fd, True)
        file_actions = [
            (os.POSIX_SPAWN_CLOSE, read_fd),
            (os.POSIX_SPAWN_DUP2, write_fd, 1),
            (os.POSIX_SPAWN_DUP2, write_fd, 2),
            (os.POSIX_SPAWN_CLOSE, write_fd),
        ]
        pid = os.posix_spawn(cmd[0], cmd, env, file_actions=file_actions)
    finally:
        os.close(write_fd)
    return pid, read_fd


def _wait_process(pid: int) -> int:
    while True:
        waited_pid, status = os.waitpid(pid, 0)
        if waited_pid == pid:
            return os.waitstatus_to_exitcode(status)
    return 1  # unreachable


def _terminate_process(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    try:
        os.waitpid(pid, 0)
    except OSError:
        return


def _run_command_posix_spawn(
    cmd: list[str],
    env: dict[str, str],
    *,
    on_line: Callable[[str], None] | None = None,
) -> tuple[int, str]:
    pid, read_fd = _posix_spawn_piped(cmd, env)
    collected: list[str] = []
    rc = 1
    try:
        with io.open(read_fd, "r", buffering=1, closefd=True) as stream:
            for line in stream:
                collected.append(line)
                if on_line is not None:
                    on_line(line)
        rc = _wait_process(pid)
    except Exception as exc:
        collected.append(f"\n[subprocess error: {exc}]\n")
        _terminate_process(pid)
    return rc, "".join(collected)


def run_command(
    cmd: list[str],
    *,
    cwd: Path | str | None = None,
    env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    popen_cmd, popen_cwd = _cmd_for_subprocess(cmd, cwd)
    merged = _merge_env(env)
    if _DARWIN:
        rc, out = _run_command_posix_spawn(popen_cmd, merged)
        return rc, out, ""
    proc = subprocess.run(
        popen_cmd,
        cwd=popen_cwd,
        capture_output=True,
        text=True,
        env=merged,
    )
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def run_command_stream(
    cmd: list[str],
    *,
    cwd: Path | str | None = None,
    env: dict[str, str] | None = None,
    on_line: Callable[[str], None] | None = None,
) -> tuple[int, str]:
    popen_cmd, popen_cwd = _cmd_for_subprocess(cmd, cwd)
    merged = _merge_env(env)
    if _DARWIN:
        return _run_command_posix_spawn(popen_cmd, merged, on_line=on_line)

    proc = subprocess.Popen(
        popen_cmd,
        cwd=popen_cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=merged,
    )
    collected: list[str] = []
    rc = 1
    try:
        if proc.stdout is not None:
            for line in iter(proc.stdout.readline, ""):
                collected.append(line)
                if on_line is not None:
                    on_line(line)
        rc = proc.wait()
    except Exception as exc:
        collected.append(f"\n[subprocess error: {exc}]\n")
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    return rc, "".join(collected)


def launch_detached(
    cmd: list[str],
    *,
    cwd: Path | str | None = None,
    env: dict[str, str] | None = None,
) -> int:
    popen_cmd, popen_cwd = _cmd_for_subprocess(cmd, cwd)
    merged = _merge_env(env)

    if _DARWIN:
        file_actions = [
            (os.POSIX_SPAWN_CLOSE, 0),
            (os.POSIX_SPAWN_CLOSE, 1),
            (os.POSIX_SPAWN_CLOSE, 2),
        ]
        return os.posix_spawn(
            popen_cmd[0],
            popen_cmd,
            merged,
            file_actions=file_actions,
            setsid=True,
        )

    proc = subprocess.Popen(
        popen_cmd,
        cwd=popen_cwd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env=merged,
    )
    return proc.pid
