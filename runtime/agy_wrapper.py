#!/usr/bin/env python3
"""Windows wrapper for a patched agy: auto-update guard + prompt-cache keepalive.

Mirrors runtime/agy-wrapper.sh without a POSIX shell. `agy.cmd` calls this file
with the user's arguments; the script finds the real binary, optionally starts
the loopback cache relay for interactive/ACP sessions, and waits for agy so the
relay can be stopped on exit.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import threading
from collections.abc import Mapping

DISABLE_AUTO_UPDATE = "AGY_CLI_DISABLE_AUTO_UPDATE"
PRINT_ONLY = {"-p", "--print", "--prompt", "--login", "--help", "-h"}


def real_binary() -> pathlib.Path:
    override = os.environ.get("AGY_REAL_BINARY")
    if override:
        return pathlib.Path(override).expanduser()
    local = pathlib.Path(os.environ.get("LOCALAPPDATA", pathlib.Path.home()))
    candidates = (
        local / "agy/bin/agy.exe",
        pathlib.Path.home() / ".local/bin/agy.exe",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise SystemExit(f"agy-patch: cannot find the installed agy.exe (looked in {', '.join(map(str, candidates))})")


def relay_script() -> pathlib.Path | None:
    candidates = (
        pathlib.Path(os.environ.get("AGY_PATCH_REPO", "")) / "runtime/cache_relay.py"
        if os.environ.get("AGY_PATCH_REPO")
        else None,
        pathlib.Path.home() / ".gemini/agy-patch/runtime/cache_relay.py",
        pathlib.Path(__file__).with_name("cache_relay.py"),
    )
    return next((path for path in candidates if path and path.is_file()), None)


def wants_relay(args: list[str]) -> bool:
    if os.environ.get("AGY_CACHE_RELAY") == "off":
        return False
    if "--hub" in args:
        return False
    if args and args[0] == "acp":
        return True
    if not args:
        return True
    if args[0].startswith("-"):
        return not any(arg == flag or arg.startswith(flag + "=") for arg in args for flag in PRINT_ONLY)
    return False


def gemini_upstream(env: Mapping[str, str]) -> str:
    """The real Gemini base for non-/v1internal paths.

    A nested agy inherits its parent's relay as GOOGLE_GEMINI_BASE_URL; that URL is not an
    upstream. The parent records the original endpoint in AGY_GEMINI_UPSTREAM.
    """
    upstream = env.get("GOOGLE_GEMINI_BASE_URL") or ""
    if upstream and upstream == (env.get("AGY_CACHE_RELAY") or ""):
        upstream = env.get("AGY_GEMINI_UPSTREAM") or ""
    return upstream


def relay_command(script: pathlib.Path, env: Mapping[str, str],
                  parent: int | None = None) -> list[str]:
    command = [sys.executable, "-I", str(script), "--parent",
               str(os.getpid() if parent is None else parent)]
    upstream = gemini_upstream(env)
    if upstream:
        command += ["--gemini-upstream", upstream]
    return command


def relay_environment(env: Mapping[str, str], relay_url: str) -> dict[str, str]:
    """Child environment for agy after the relay starts.

    Gemini-provider traffic must stay on its real upstream: pointing it at this relay without
    an upstream would make the relay send /v1beta paths to Cloud Code.
    """
    result = dict(env)
    inherited_relay = env.get("AGY_CACHE_RELAY") or ""
    upstream = gemini_upstream(env)
    result["AGY_CACHE_RELAY"] = relay_url
    result["CLOUD_CODE_URL"] = relay_url
    if upstream:
        result["AGY_GEMINI_UPSTREAM"] = upstream
        result["GOOGLE_GEMINI_BASE_URL"] = relay_url
    else:
        result.pop("AGY_GEMINI_UPSTREAM", None)
        if inherited_relay and env.get("GOOGLE_GEMINI_BASE_URL") == inherited_relay:
            # The inherited value names the parent relay, not a Gemini endpoint.
            result.pop("GOOGLE_GEMINI_BASE_URL", None)
    return result


def start_relay(script: pathlib.Path) -> tuple[subprocess.Popen[str], int] | None:
    env = os.environ.copy()
    command = relay_command(script, env)
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        relay = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            creationflags=flags,
        )
    except OSError:
        return None

    line: list[str] = []

    def read_port() -> None:
        if relay.stdout is not None:
            line.append(relay.stdout.readline().strip())

    reader = threading.Thread(target=read_port, daemon=True)
    reader.start()
    reader.join(3)
    if not line or not line[0].isdigit():
        relay.terminate()
        return None
    return relay, int(line[0])


def main(argv: list[str]) -> int:
    args = list(argv)
    env = os.environ.copy()
    env[DISABLE_AUTO_UPDATE] = "true"
    binary = real_binary()
    relay: subprocess.Popen[str] | None = None
    if wants_relay(args):
        script = relay_script()
        if script is not None:
            started = start_relay(script)
            if started is not None:
                relay, port = started
                env = relay_environment(env, f"http://127.0.0.1:{port}")
    try:
        return subprocess.run([str(binary), *args], env=env).returncode
    finally:
        if relay is not None:
            relay.terminate()
            try:
                relay.wait(timeout=5)
            except subprocess.TimeoutExpired:
                relay.kill()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
