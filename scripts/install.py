#!/usr/bin/env python3
"""Idempotent installer and uninstaller for agy-patch.

Designed for both humans and deploying agents:
  - Preflight checks the platform, Python >= 3.12, required tools, and stock binary + templates.
  - Supports --dry-run to inspect every planned change before touching disk.
  - Applies the binary patch, syncs the runtime wrapper/statusline, configures
    statusLine + contextWindow in ~/.gemini/antigravity-cli/settings.json, and
    manages a clean marker block in ~/.zshrc (macOS) or every detected PowerShell
    profile (Windows).
  - Supports --uninstall to cleanly revert the binary and remove installed wrapper/shell block.
"""

from __future__ import annotations

import argparse
import codecs
import json
import locale
import ntpath
import os
import pathlib
import platform
import re
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

IS_WINDOWS = sys.platform == "win32"
MARKER_BEGIN = "# >>> agy-patch >>>"
MARKER_END = "# <<< agy-patch <<<"
VALID_WINDOWS = ("Default", "256K", "512K", "900K")
SHELL_BLOCK = "\n".join(
    [
        MARKER_BEGIN,
        'export AGY_CLI_DISABLE_AUTO_UPDATE=true',
        'alias agy="$HOME/.gemini/bin/agy"',
        MARKER_END,
    ]
)
POWERSHELL_BLOCK = "\n".join(
    [
        MARKER_BEGIN,
        '$env:AGY_CLI_DISABLE_AUTO_UPDATE = "true"',
        '$agyPatchBin = Join-Path $HOME ".gemini\\bin"',
        'if (($env:PATH -split \';\') -notcontains $agyPatchBin) { $env:PATH = "$agyPatchBin;$env:PATH" }',
        MARKER_END,
    ]
)


def default_binary(home: pathlib.Path) -> pathlib.Path:
    """The installed binary for this platform; Windows uses agy's own install target."""
    if IS_WINDOWS:
        local = pathlib.Path(os.environ.get("LOCALAPPDATA", home))
        candidates = (local / "agy/bin/agy.exe", home / ".local/bin/agy.exe")
        return next((path for path in candidates if path.exists()), candidates[0])
    return home / ".local/bin/agy"


def windows_paths(home: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    """(wrapper .cmd, wrapper .py, statusline .py) for the Windows runtime layer."""
    return (
        home / ".gemini/bin/agy.cmd",
        home / ".gemini/bin/agy_wrapper.py",
        home / ".gemini/antigravity-cli/statusline.py",
    )


def documents_dir(home: pathlib.Path) -> pathlib.Path:
    """The user's real Documents directory, or the sandbox's when --home overrides HOME.

    Explorer stores the shell folder under HKCU and may redirect it to OneDrive, so
    the literal `home/Documents` is not enough for a real installation. Reading that
    value never starts PowerShell or executes a profile. A sandbox home always keeps
    every installed file inside the sandbox.
    """
    fallback = home / "Documents"
    if not IS_WINDOWS:
        return fallback
    if home.resolve() != pathlib.Path.home().resolve():
        return fallback
    return _profile_documents(fallback)


def _profile_documents(fallback: pathlib.Path) -> pathlib.Path:
    """Resolve the current user's Documents folder from Explorer's shell-folder registry."""
    try:
        import winreg
    except ImportError:  # not Windows, or a stripped interpreter
        return fallback
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "Personal")
    except OSError:
        return fallback
    expanded = os.path.expandvars(str(value))
    candidate = pathlib.Path(expanded)
    if not expanded or not candidate.is_absolute():
        return fallback
    return candidate


def _pwsh_installed() -> bool:
    """Whether PowerShell 7+ is installed, without starting it or loading a profile."""
    if shutil.which("pwsh.exe") or shutil.which("pwsh"):
        return True
    candidates = []
    for env in ("ProgramFiles", "ProgramFiles(x86)"):
        if root := os.environ.get(env):
            candidates.append(pathlib.Path(root) / "PowerShell/7/pwsh.exe")
    if local := os.environ.get("LOCALAPPDATA"):
        candidates.append(pathlib.Path(local) / "Microsoft/WindowsApps/pwsh.exe")
    return any(candidate.is_file() for candidate in candidates)


def _windows_powershell_installed() -> bool:
    """Whether the built-in Windows PowerShell 5.1 host is present."""
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    builtin = pathlib.Path(system_root) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    return builtin.is_file() or bool(shutil.which("powershell.exe") or shutil.which("powershell"))


def powershell_hosts() -> list[str]:
    """Installed PowerShell hosts, detected from files/PATH rather than profile existence."""
    if not IS_WINDOWS:
        return []
    hosts = []
    if _pwsh_installed():
        hosts.append("pwsh")
    if _windows_powershell_installed():
        hosts.append("windows-powershell")
    return hosts


def powershell_profiles(home: pathlib.Path) -> list[pathlib.Path]:
    """Every profile that can load the managed block for an installed PowerShell host.

    Windows PowerShell 5.1 ships with Windows, so a fresh machine always gets its
    profile; PowerShell 7 is added only when `pwsh` is installed. An existing PS7
    profile is still managed so uninstall can clean up after a removed host. This
    never infers PS7 from a missing profile.
    """
    docs = documents_dir(home)
    ps5 = docs / "WindowsPowerShell/Microsoft.PowerShell_profile.ps1"
    ps7 = docs / "PowerShell/Microsoft.PowerShell_profile.ps1"
    hosts = powershell_hosts()
    profiles = []
    if "windows-powershell" in hosts or not hosts:
        profiles.append(ps5)
    if "pwsh" in hosts or ps7.exists():
        profiles.append(ps7)
    return profiles or [ps5]


def statusline_command(home: pathlib.Path) -> str:
    if IS_WINDOWS:
        _, _, target = windows_paths(home)
        return f'"{sys.executable}" -I "{target}"'
    return str(home / ".gemini/antigravity-cli/statusline.sh")


def merge_settings(existing: dict, statusline_cmd: str, window: str | None) -> dict:
    """Merge statusLine and optional contextWindow into settings without clobbering user keys."""
    updated = dict(existing)
    updated["statusLine"] = {
        "type": "command",
        "command": statusline_cmd,
        "enabled": True,
    }
    if window:
        if window == "Default":
            updated.pop("contextWindow", None)
        else:
            updated["contextWindow"] = window
    return updated


def remove_statusline_if_managed(
    existing: dict, statusline_cmd: str, statusline_target: pathlib.Path | None = None
) -> tuple[dict, bool]:
    """Remove statusLine only when it points to our managed statusline."""
    updated = dict(existing)
    sl = updated.get("statusLine")
    command = sl.get("command") if isinstance(sl, dict) else None
    managed = {statusline_cmd, "~/.gemini/antigravity-cli/statusline.sh"}
    if isinstance(command, str) and (
        command in managed or (statusline_target is not None and str(statusline_target) in command)
    ):
        updated.pop("statusLine", None)
        return updated, True
    return updated, False


def upsert_zshrc_block(text: str) -> tuple[str, str]:
    """Insert or update the managed agy-patch block in .zshrc idempotently."""
    pattern = re.compile(
        rf"(?ms)^{re.escape(MARKER_BEGIN)}\n.*?^{re.escape(MARKER_END)}\n?"
    )
    if pattern.search(text):
        new_text = pattern.sub(lambda _: SHELL_BLOCK + "\n", text, count=1)
        return new_text, "unchanged" if new_text == text else "updated"

    # Avoid duplicating manual exports/aliases already configured by the user.
    has_export = "AGY_CLI_DISABLE_AUTO_UPDATE=true" in text
    has_alias = re.search(r'^\s*alias\s+agy=.*(?:/\.gemini/bin/agy)', text, re.M) is not None
    if has_export and has_alias:
        return text, "already-configured"

    sep = "" if not text or text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
    return text + sep + SHELL_BLOCK + "\n", "added"


def remove_zshrc_block(text: str) -> tuple[str, bool]:
    """Remove the managed agy-patch block from .zshrc if present."""
    pattern = re.compile(
        rf"(?ms)\n?^{re.escape(MARKER_BEGIN)}\n.*?^{re.escape(MARKER_END)}\n?"
    )
    new_text, count = pattern.subn("\n", text)
    if count == 0:
        return text, False
    new_text = re.sub(r"\n{3,}", "\n\n", new_text).strip("\n")
    if new_text:
        new_text += "\n"
    return new_text, True


def upsert_powershell_block(text: str) -> tuple[str, str]:
    """Insert or update the managed agy-patch block in a PowerShell profile."""
    pattern = re.compile(
        rf"(?ms)^{re.escape(MARKER_BEGIN)}\n.*?^{re.escape(MARKER_END)}\n?"
    )
    if pattern.search(text):
        new_text = pattern.sub(lambda _: POWERSHELL_BLOCK + "\n", text, count=1)
        return new_text, "unchanged" if new_text == text else "updated"

    has_export = "AGY_CLI_DISABLE_AUTO_UPDATE" in text
    has_path = ".gemini\\bin" in text
    if has_export and has_path:
        return text, "already-configured"

    sep = "" if not text or text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
    return text + sep + POWERSHELL_BLOCK + "\n", "added"


def remove_powershell_block(text: str) -> tuple[str, bool]:
    """Remove the managed agy-patch block from a PowerShell profile if present."""
    pattern = re.compile(
        rf"(?ms)\n?^{re.escape(MARKER_BEGIN)}\n.*?^{re.escape(MARKER_END)}\n?"
    )
    new_text, count = pattern.subn("\n", text)
    if count == 0:
        return text, False
    new_text = re.sub(r"\n{3,}", "\n\n", new_text).strip("\n")
    if new_text:
        new_text += "\n"
    return new_text, True


def read_profile(path: pathlib.Path) -> tuple[str, str, str | None]:
    """Read a shell profile as (LF-normalized text, encoding, newline).

    Profiles on Windows may be UTF-8, UTF-16 (PowerShell 5.1's `Out-File` default),
    or the active ANSI code page. Preserve the bytes' encoding and line endings when
    writing the managed block back instead of silently transcoding user content.
    `newline` is None when the file does not exist or has no newline yet.
    """
    if not path.exists():
        return "", "utf-8", None
    raw = path.read_bytes()
    if raw.startswith(codecs.BOM_UTF8):
        encoding = "utf-8-sig"
    elif raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        encoding = "utf-16"
    else:
        try:
            raw.decode("utf-8")
            encoding = "utf-8"
        except UnicodeDecodeError:
            encoding = "mbcs" if os.name == "nt" else locale.getpreferredencoding(False)
    text = raw.decode(encoding)
    newline = "\r\n" if "\r\n" in text else ("\n" if "\n" in text else None)
    return text.replace("\r\n", "\n").replace("\r", "\n"), encoding, newline


def write_profile(path: pathlib.Path, text: str, encoding: str, newline: str) -> None:
    """Write LF-normalized profile text back with its original encoding and newlines."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.replace("\n", newline).encode(encoding))


def check_prerequisites(binary: pathlib.Path, force_platform: bool = False) -> tuple[list[str], str | None]:
    """Validate runtime prerequisites before patching."""
    errors: list[str] = []
    if IS_WINDOWS:
        if not force_platform and (
            platform.system() != "Windows" or platform.machine().lower() not in ("amd64", "x86_64")
        ):
            errors.append(f"Unsupported platform {platform.system()}/{platform.machine()} (requires Windows/amd64)")
    elif not force_platform and (platform.system() != "Darwin" or platform.machine() != "arm64"):
        errors.append(f"Unsupported platform {platform.system()}/{platform.machine()} (requires Darwin/arm64)")
    if sys.version_info < (3, 12):
        errors.append(f"Python >= 3.12 required (found {sys.version.split()[0]})")
    if not IS_WINDOWS:
        for cmd in ("codesign", "jq"):
            if shutil.which(cmd) is None:
                errors.append(f"Required tool not found in PATH: {cmd}")
    if not binary.exists():
        errors.append(f"Target agy binary not found: {binary}")
        return errors, None

    proc = subprocess.run([str(binary), "--version"], capture_output=True, text=True)
    version = proc.stdout.strip() if proc.returncode == 0 else None
    if not version:
        errors.append(f"Could not read `agy --version` from {binary}")
    elif not (REPO / "templates" / f"v{version}").is_dir():
        errors.append(f"No templates/v{version}/ directory for {binary} (supported: {_supported_versions()})")
    return errors, version


def _supported_versions() -> str:
    versions = sorted(p.name for p in (REPO / "templates").glob("v*") if p.is_dir())
    return ", ".join(versions) or "none"


_CMD_PATH_VARS = (
    "LOCALAPPDATA",
    "APPDATA",
    "USERPROFILE",
    "ProgramFiles",
    "ProgramFiles(x86)",
    "ProgramData",
    "SystemRoot",
    "TEMP",
    "TMP",
)


def _windows_path_expression(path: pathlib.Path) -> str:
    """A batch expression for a Windows path, preferring ASCII `%VAR%` expansion.

    cmd reads a .cmd file in the console's OEM code page, so literal non-ASCII text
    is unsafe under GBK/CP1252. Replacing an install-time environment-variable
    prefix with `%LOCALAPPDATA%` and friends keeps the command file ASCII while cmd
    still expands the real Unicode value from its environment block. Only a path
    with non-ASCII text outside every known variable prefix needs the UTF-8 fallback.
    """
    text = str(path)
    normalized = ntpath.normcase(text)
    literal = text.replace("%", "%%")
    best, best_bad = literal, sum(not char.isascii() for char in literal)
    for name in _CMD_PATH_VARS:
        root = os.environ.get(name)
        if not root:
            continue
        root = root.rstrip("\\/")
        root_normalized = ntpath.normcase(root)
        if normalized == root_normalized:
            expression = f"%{name}%"
        elif normalized.startswith(root_normalized + "\\"):
            expression = f"%{name}%" + text[len(root) :].replace("%", "%%")
        else:
            continue
        bad = sum(not char.isascii() for char in expression)
        if bad == 0:
            return expression
        if bad < best_bad:
            best, best_bad = expression, bad
    return best


def _windows_wrapper_cmd(binary: pathlib.Path, python: pathlib.Path | None = None) -> str:
    """A shim with the absolute interpreter and target binary, independent of PATH.

    Unicode paths travel through the environment block. When a path cannot be
    expressed through `%VAR%`, the two assignments are read as UTF-8 and the console
    code page is restored *before* Python starts, so the caller's console is left
    unchanged and the launcher line stays ASCII. `setlocal` keeps AGY_REAL_BINARY
    from leaking into a cmd session that `call`s the shim, and the child's exit code
    is propagated explicitly.
    """
    python = pathlib.Path(python or sys.executable)
    python_expr = _windows_path_expression(python)
    binary_expr = _windows_path_expression(binary)
    utf8_assignments = not (python_expr.isascii() and binary_expr.isascii())
    lines = ["@echo off", "setlocal"]
    if utf8_assignments:
        lines += [
            'for /f "tokens=2 delims=:" %%c in (\'chcp\') do set "agy_patch_cp=%%c"',
            'set "agy_patch_cp=%agy_patch_cp: =%"',
            'set "agy_patch_cp=%agy_patch_cp:.=%"',
            'if defined agy_patch_cp chcp 65001 >nul',
        ]
    lines += [
        f'set "AGY_PATCH_PYTHON={python_expr}"',
        f'set "AGY_REAL_BINARY={binary_expr}"',
    ]
    if utf8_assignments:
        lines.append('if defined agy_patch_cp chcp %agy_patch_cp% >nul')
    lines += [
        '"%AGY_PATCH_PYTHON%" -I "%~dp0agy_wrapper.py" %*',
        'set "agy_patch_rc=%ERRORLEVEL%"',
        "endlocal & exit /b %agy_patch_rc%",
    ]
    return "\r\n".join(lines) + "\r\n"


def install(
    home: pathlib.Path,
    binary: pathlib.Path,
    window: str,
    dry_run: bool,
    skip_shell: bool,
    force_platform: bool,
) -> int:
    errors, version = check_prerequisites(binary, force_platform=force_platform)
    if errors:
        for err in errors:
            print(f"[error] {err}", file=sys.stderr)
        return 1

    settings_path = home / ".gemini/antigravity-cli/settings.json"
    shell_kind = "PowerShell profile" if IS_WINDOWS else "shell rc"
    if IS_WINDOWS:
        wrapper_target, wrapper_py, statusline_target = windows_paths(home)
        runtime_wrapper = REPO / "runtime/agy-wrapper.cmd"
        runtime_wrapper_py = REPO / "runtime/agy_wrapper.py"
        runtime_statusline = REPO / "runtime/statusline.py"
        statusline_cmd = statusline_command(home)
        upsert_shell = upsert_powershell_block
    else:
        wrapper_target = home / ".gemini/bin/agy"
        statusline_target = home / ".gemini/antigravity-cli/statusline.sh"
        runtime_wrapper = REPO / "runtime/agy-wrapper.sh"
        runtime_statusline = REPO / "runtime/statusline.sh"
        statusline_cmd = str(statusline_target)
        upsert_shell = upsert_zshrc_block

    existing_settings: dict = {}
    if settings_path.exists():
        try:
            existing_settings = json.loads(settings_path.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            print(f"[error] Invalid JSON in {settings_path}: {exc}", file=sys.stderr)
            return 1
    new_settings = merge_settings(existing_settings, statusline_cmd, window)

    # --skip-shell must not even discover, read, or write a profile.
    shell_plans: list[tuple[pathlib.Path, str, str, str, str, str]] = []
    if not skip_shell:
        profiles = powershell_profiles(home) if IS_WINDOWS else [home / ".zshrc"]
        default_newline = "\r\n" if IS_WINDOWS else "\n"
        for profile in profiles:
            before, encoding, newline = read_profile(profile)
            after, state = upsert_shell(before)
            shell_plans.append((profile, before, after, state, encoding, newline or default_newline))

    if dry_run:
        print(f"[dry-run] Binary      : {binary} (v{version})")
        print(f"[dry-run] Patch apply : {sys.executable} {REPO / 'patch_agy.py'} --apply")
        print(f"[dry-run] Wrapper     : {runtime_wrapper} -> {wrapper_target}")
        if IS_WINDOWS:
            print(f"[dry-run] Wrapper py  : {runtime_wrapper_py} -> {wrapper_py}")
        print(f"[dry-run] Statusline  : {runtime_statusline} -> {statusline_target}")
        print(f"[dry-run] Settings    : {settings_path} ({'unchanged' if new_settings == existing_settings else 'update'})")
        for profile, _, _, state, _, _ in shell_plans:
            print(f"[dry-run] {shell_kind:9s}: {profile} ({state})")
        return 0

    cmd = [
        sys.executable,
        str(REPO / "patch_agy.py"),
        "--apply",
        "--binary",
        str(binary),
    ]
    if not IS_WINDOWS:
        cmd += ["--binary", str(wrapper_target)]
    child_env = os.environ.copy()
    child_env["HOME"] = str(home)
    child_env["USERPROFILE"] = str(home)
    subprocess.run(cmd, check=True, env=child_env)

    if IS_WINDOWS:
        wrapper_target.parent.mkdir(parents=True, exist_ok=True)
        wrapper_target.write_text(_windows_wrapper_cmd(binary), encoding="utf-8", newline="")
        shutil.copy2(runtime_wrapper_py, wrapper_py)
        shutil.copy2(REPO / "runtime/cache_relay.py", wrapper_py.with_name("cache_relay.py"))
        print(f"[cfg]  Installed wrapper {wrapper_target} + {wrapper_py.name}")
    else:
        wrapper_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(runtime_wrapper, wrapper_target)
        os.chmod(wrapper_target, 0o755)

    statusline_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(runtime_statusline, statusline_target)
    if not IS_WINDOWS:
        os.chmod(statusline_target, 0o755)
    print(f"[cfg]  Installed statusline {statusline_target}")

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    if new_settings != existing_settings or not settings_path.exists():
        settings_path.write_text(json.dumps(new_settings, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(f"[cfg]  Updated {settings_path} (statusLine + contextWindow={window!r})")
    else:
        print(f"[ok]   {settings_path} already up to date")

    for profile, before, after, state, encoding, newline in shell_plans:
        if after != before:
            write_profile(profile, after, encoding, newline)
            print(f"[cfg]  Updated {profile} ({state} managed agy-patch block)")
        else:
            print(f"[ok]   {profile} ({state})")

    print("\nVerification:")
    subprocess.run(
        [sys.executable, str(REPO / "patch_agy.py"), "--status", "--binary", str(binary)],
        check=True,
        env=child_env,
    )
    if IS_WINDOWS:
        print("\nDone. Open a new PowerShell window and run `agy --version`.")
    else:
        print("\nDone. Open a new shell (or run `source ~/.zshrc`) and check `type agy`.")
    return 0


def uninstall(home: pathlib.Path, binary: pathlib.Path, dry_run: bool, skip_shell: bool) -> int:
    settings_path = home / ".gemini/antigravity-cli/settings.json"
    if IS_WINDOWS:
        wrapper_target, wrapper_py, statusline_target = windows_paths(home)
        remove_shell = remove_powershell_block
        shell_kind = "PowerShell profile"
    else:
        wrapper_target = home / ".gemini/bin/agy"
        wrapper_py = None
        statusline_target = home / ".gemini/antigravity-cli/statusline.sh"
        remove_shell = remove_zshrc_block
        shell_kind = "shell rc"

    # --skip-shell must not even discover, read, or write a profile.
    shell_profiles = [] if skip_shell else (powershell_profiles(home) if IS_WINDOWS else [home / ".zshrc"])

    if dry_run:
        print(f"[dry-run] Revert binary  : {binary}")
        print(f"[dry-run] Remove wrapper : {wrapper_target}")
        if wrapper_py is not None:
            print(f"[dry-run] Remove script  : {wrapper_py}")
        print(f"[dry-run] Remove script  : {statusline_target}")
        print(f"[dry-run] Clean settings : {settings_path}")
        for profile in shell_profiles:
            print(f"[dry-run] Clean {shell_kind}: {profile}")
        return 0

    if binary.exists():
        child_env = os.environ.copy()
        child_env["HOME"] = str(home)
        child_env["USERPROFILE"] = str(home)
        subprocess.run(
            [sys.executable, str(REPO / "patch_agy.py"), "--revert", "--binary", str(binary)],
            check=True,
            env=child_env,
        )

    if wrapper_target.exists():
        if IS_WINDOWS or wrapper_target.open("rb").read(2) == b"#!":
            wrapper_target.unlink()
            print(f"[del]  Removed wrapper {wrapper_target}")

    if wrapper_py is not None and wrapper_py.exists():
        wrapper_py.unlink()
        print(f"[del]  Removed {wrapper_py}")
        relay_copy = wrapper_py.with_name("cache_relay.py")
        if relay_copy.exists():
            relay_copy.unlink()
            print(f"[del]  Removed {relay_copy}")

    if statusline_target.exists():
        statusline_target.unlink()
        print(f"[del]  Removed {statusline_target}")

    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            existing = None
        if isinstance(existing, dict):
            cleaned, changed = remove_statusline_if_managed(existing, statusline_command(home), statusline_target)
            if changed:
                settings_path.write_text(json.dumps(cleaned, indent=2) + "\n", encoding="utf-8", newline="\n")
                print(f"[cfg]  Removed managed statusLine from {settings_path}")

    for profile in shell_profiles:
        if not profile.exists():
            continue
        before, encoding, newline = read_profile(profile)
        after, removed = remove_shell(before)
        if removed:
            write_profile(profile, after, encoding, newline or ("\r\n" if IS_WINDOWS else "\n"))
            print(f"[cfg]  Removed agy-patch block from {profile}")

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Print planned actions without modifying files")
    parser.add_argument("--uninstall", action="store_true", help="Revert binary patch and remove installed wrappers")
    parser.add_argument("--set-window", choices=VALID_WINDOWS, default="512K", help="Default contextWindow preset (default: 512K)")
    parser.add_argument("--skip-shell", action="store_true", help="Do not modify ~/.zshrc or any PowerShell profile")
    parser.add_argument("--binary", type=pathlib.Path, help="Target agy binary path (default: the platform install target)")
    parser.add_argument("--home", type=pathlib.Path, default=pathlib.Path.home(), help="Override HOME directory (for testing)")
    parser.add_argument("--force-platform", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    home = args.home.expanduser().resolve()
    binary = (args.binary or default_binary(home)).expanduser().resolve()

    if args.uninstall:
        return uninstall(home, binary, dry_run=args.dry_run, skip_shell=args.skip_shell)
    return install(
        home,
        binary,
        window=args.set_window,
        dry_run=args.dry_run,
        skip_shell=args.skip_shell,
        force_platform=args.force_platform,
    )


if __name__ == "__main__":
    raise SystemExit(main())
