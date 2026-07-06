"""Run subprocesses from a spawn worker to avoid fork()+PROJ crashes on macOS.

Streamlit is multi-threaded and may import geopandas/pyproj (PROJ SQLite cache).
fork() from that process triggers PROJ atfork handlers and can SIGSEGV before exec.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import queue
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any


def _merge_env(env: dict[str, str] | None) -> dict[str, str]:
    merged = os.environ.copy()
    merged["PROJ_DISABLE_CACHE"] = "ON"
    if env:
        merged.update(env)
    return merged


def _run_captured_worker(
    cmd: list[str],
    cwd: str | None,
    env: dict[str, str],
    result_queue: Any,
) -> None:
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
    )
    result_queue.put((proc.returncode, proc.stdout or "", proc.stderr or ""))


def run_command(
    cmd: list[str],
    *,
    cwd: Path | str | None = None,
    env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    ctx = mp.get_context("spawn")
    result_queue: mp.Queue = ctx.Queue()
    worker = ctx.Process(
        target=_run_captured_worker,
        args=(cmd, str(cwd) if cwd else None, _merge_env(env), result_queue),
    )
    worker.start()
    worker.join()
    if not result_queue.empty():
        rc, stdout, stderr = result_queue.get()
        return int(rc), stdout, stderr
    return worker.exitcode or 1, "", "subprocess worker failed"


def _run_stream_worker(
    cmd: list[str],
    cwd: str | None,
    env: dict[str, str],
    line_queue: Any,
) -> None:
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
    )
    try:
        if proc.stdout is not None:
            for line in iter(proc.stdout.readline, ""):
                line_queue.put(("line", line))
        rc = proc.wait()
        line_queue.put(("done", rc))
    except Exception as exc:
        line_queue.put(("error", str(exc)))


def run_command_stream(
    cmd: list[str],
    *,
    cwd: Path | str | None = None,
    env: dict[str, str] | None = None,
    on_line: Callable[[str], None] | None = None,
) -> tuple[int, str]:
    ctx = mp.get_context("spawn")
    line_queue: mp.Queue = ctx.Queue()
    worker = ctx.Process(
        target=_run_stream_worker,
        args=(cmd, str(cwd) if cwd else None, _merge_env(env), line_queue),
    )
    worker.start()

    collected: list[str] = []
    rc = 1
    while True:
        if not worker.is_alive() and line_queue.empty():
            break
        try:
            kind, payload = line_queue.get(timeout=0.25)
        except queue.Empty:
            continue
        if kind == "line":
            line = str(payload)
            collected.append(line)
            if on_line is not None:
                on_line(line)
        elif kind == "done":
            rc = int(payload)
            break
        elif kind == "error":
            collected.append(f"\n[subprocess error: {payload}]\n")
            break

    worker.join()
    return rc, "".join(collected)


def _launch_detached_worker(
    cmd: list[str],
    cwd: str | None,
    env: dict[str, str],
    result_queue: Any,
) -> None:
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env=env,
    )
    result_queue.put(proc.pid)


def launch_detached(
    cmd: list[str],
    *,
    cwd: Path | str | None = None,
    env: dict[str, str] | None = None,
) -> int:
    ctx = mp.get_context("spawn")
    result_queue: mp.Queue = ctx.Queue()
    worker = ctx.Process(
        target=_launch_detached_worker,
        args=(cmd, str(cwd) if cwd else None, _merge_env(env), result_queue),
    )
    worker.start()
    worker.join()
    if not result_queue.empty():
        return int(result_queue.get())
    raise RuntimeError("failed to launch detached subprocess")
