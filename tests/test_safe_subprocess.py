"""Tests for macOS-safe subprocess launching."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from server.core import safe_subprocess as ss


def test_cmd_for_subprocess_keeps_cwd_on_linux(monkeypatch):
    monkeypatch.setattr(ss, "_DARWIN", False)
    cmd, cwd = ss._cmd_for_subprocess(["echo", "hi"], "/tmp/work")
    assert cmd == ["echo", "hi"]
    assert cwd == "/tmp/work"


def test_cmd_for_subprocess_wraps_cwd_on_darwin(monkeypatch):
    monkeypatch.setattr(ss, "_DARWIN", True)
    cmd, cwd = ss._cmd_for_subprocess(["/bin/echo", "hi"], "/tmp/work")
    assert cwd is None
    assert cmd[0] == sys.executable
    assert cmd[1] == "-c"
    payload = json.loads(cmd[3])
    assert payload["cwd"] == "/tmp/work"
    assert payload["cmd"] == ["/bin/echo", "hi"]


@pytest.mark.skipif(not Path("/tmp").exists(), reason="needs /tmp")
def test_run_command_stream_with_cwd_on_darwin(monkeypatch):
    monkeypatch.setattr(ss, "_DARWIN", True)
    rc, out = ss.run_command_stream(
        [sys.executable, "-c", "import os; print(os.getcwd())"],
        cwd="/tmp",
    )
    assert rc == 0
    assert "/tmp" in out.replace("\\", "/")


@pytest.mark.skipif(not Path("/tmp").exists(), reason="needs /tmp")
def test_run_command_stream_from_thread_on_darwin(monkeypatch):
    import threading

    monkeypatch.setattr(ss, "_DARWIN", True)
    results: list[tuple[int, str]] = []

    def worker() -> None:
        rc, out = ss.run_command_stream(
            [sys.executable, "-c", "print('thread-ok')"],
            cwd="/tmp",
        )
        results.append((rc, out))

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert results
    assert results[0][0] == 0
    assert "thread-ok" in results[0][1]
