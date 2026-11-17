"""Unit tests for idempotent helpers and dry-run flow in scripts/install.py."""

from __future__ import annotations

import contextlib
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
import unittest.mock

from scripts import install


class InstallHelpersTests(unittest.TestCase):
    def test_merge_settings_preserves_existing_keys(self) -> None:
        existing = {"model": "Gemini 4 Hydrogen (High)", "trustedWorkspaces": ["/a"]}
        merged = install.merge_settings(existing, "/h/.gemini/antigravity-cli/statusline.sh", "512K")
        self.assertEqual(merged["model"], "Gemini 4 Hydrogen (High)")
        self.assertEqual(merged["trustedWorkspaces"], ["/a"])
        self.assertEqual(merged["contextWindow"], "512K")
        self.assertTrue(merged["statusLine"]["enabled"])

    def test_merge_settings_default_window_removes_key(self) -> None:
        merged = install.merge_settings({"contextWindow": "512K"}, "/s.sh", "Default")
        self.assertNotIn("contextWindow", merged)

    def test_upsert_and_remove_zshrc_block_is_idempotent(self) -> None:
        initial = "export PATH=$HOME/.local/bin:$PATH\n"
        once, state1 = install.upsert_zshrc_block(initial)
        self.assertEqual(state1, "added")
        twice, state2 = install.upsert_zshrc_block(once)
        self.assertEqual(state2, "unchanged")
        self.assertEqual(once, twice)

        cleaned, removed = install.remove_zshrc_block(twice)
        self.assertTrue(removed)
        self.assertEqual(cleaned, initial)

    def test_upsert_skips_if_manual_config_already_present(self) -> None:
        manual = 'export AGY_CLI_DISABLE_AUTO_UPDATE=true\nalias agy="$HOME/.gemini/bin/agy"\n'
        after, state = install.upsert_zshrc_block(manual)
        self.assertEqual(state, "already-configured")
        self.assertEqual(after, manual)

    def test_dry_run_makes_zero_disk_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp)
            fake_bin = home / ".local/bin/agy"
            fake_bin.parent.mkdir(parents=True)
            fake_bin.write_text("#!/bin/sh\necho 1.5.9\n")
            fake_bin.chmod(0o755)

            if not all(install.shutil.which(c) for c in ("codesign", "jq")):
                self.skipTest("codesign/jq required for preflight")

            rc = install.main(
                [
                    "--dry-run",
                    "--home",
                    str(home),
                    "--binary",
                    str(fake_bin),
                    "--force-platform",
                ]
            )
            self.assertEqual(rc, 0)
            self.assertFalse((home / ".zshrc").exists())
            self.assertFalse((home / ".gemini/antigravity-cli/settings.json").exists())

    def test_powershell_block_is_idempotent(self) -> None:
        initial = '$env:PATH = "C:\\Tools;$env:PATH"\n'
        once, state1 = install.upsert_powershell_block(initial)
        self.assertEqual(state1, "added")
        twice, state2 = install.upsert_powershell_block(once)
        self.assertEqual(state2, "unchanged")
        self.assertEqual(once, twice)
        cleaned, removed = install.remove_powershell_block(twice)
        self.assertTrue(removed)
        self.assertEqual(cleaned, initial)

    def test_remove_statusline_accepts_a_windows_command(self) -> None:
        target = pathlib.Path("C:/Users/example/.gemini/antigravity-cli/statusline.py")
        existing = {"statusLine": {"type": "command", "command": f'"python.exe" -I "{target}"'}}
        cleaned, changed = install.remove_statusline_if_managed(existing, "unused", target)
        self.assertTrue(changed)
        self.assertNotIn("statusLine", cleaned)

    @unittest.skipUnless(install.IS_WINDOWS, "Windows-specific paths")
    def test_windows_dry_run_makes_zero_disk_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp)
            fake_bin = home / "agy.exe"
            fake_bin.write_bytes(b"MZ")
            with unittest.mock.patch.object(install, "check_prerequisites", return_value=([], "1.5.9")):
                rc = install.main(
                    [
                        "--dry-run",
                        "--home",
                        str(home),
                        "--binary",
                        str(fake_bin),
                        "--force-platform",
                    ]
                )
            self.assertEqual(rc, 0)
            self.assertFalse((home / ".gemini").exists())
            self.assertFalse((home / "Documents").exists())


class WindowsInstallRegressionTests(unittest.TestCase):
    def test_powershell_profiles_fresh_51_uses_builtin_profile_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp)
            with unittest.mock.patch.object(install, "IS_WINDOWS", True), unittest.mock.patch.object(
                install, "powershell_hosts", return_value=["windows-powershell"]
            ):
                profiles = install.powershell_profiles(home)
            self.assertEqual(profiles, [home / "Documents/WindowsPowerShell/Microsoft.PowerShell_profile.ps1"])
            self.assertFalse((home / "Documents/PowerShell").exists())

    def test_powershell_profiles_manage_every_installed_host(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp)
            with unittest.mock.patch.object(install, "IS_WINDOWS", True), unittest.mock.patch.object(
                install, "powershell_hosts", return_value=["pwsh", "windows-powershell"]
            ):
                profiles = install.powershell_profiles(home)
            self.assertEqual(
                profiles,
                [
                    home / "Documents/WindowsPowerShell/Microsoft.PowerShell_profile.ps1",
                    home / "Documents/PowerShell/Microsoft.PowerShell_profile.ps1",
                ],
            )

    def test_documents_dir_keeps_sandbox_home_under_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp)
            with unittest.mock.patch.object(install, "IS_WINDOWS", True):
                self.assertEqual(install.documents_dir(home), home / "Documents")

    def test_fresh_windows_51_dry_run_activates_51_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp).resolve()
            fake_bin = home / "agy.exe"
            fake_bin.write_bytes(b"MZ")
            output = io.StringIO()
            with unittest.mock.patch.object(install, "IS_WINDOWS", True), unittest.mock.patch.object(
                install, "check_prerequisites", return_value=([], "1.5.9")
            ), unittest.mock.patch.object(
                install, "powershell_hosts", return_value=["windows-powershell"]
            ), contextlib.redirect_stdout(output):
                rc = install.main(
                    ["--dry-run", "--home", str(home), "--binary", str(fake_bin), "--force-platform"]
                )
            self.assertEqual(rc, 0)
            text = output.getvalue()
            self.assertIn(str(home / "Documents/WindowsPowerShell/Microsoft.PowerShell_profile.ps1"), text)
            self.assertNotIn(str(home / "Documents/PowerShell/Microsoft.PowerShell_profile.ps1"), text)
            self.assertFalse((home / "Documents").exists())

    def test_skip_shell_does_not_even_discover_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp)
            fake_bin = home / "agy.exe"
            fake_bin.write_bytes(b"MZ")
            output = io.StringIO()
            with unittest.mock.patch.object(install, "IS_WINDOWS", True), unittest.mock.patch.object(
                install, "check_prerequisites", return_value=([], "1.5.9")
            ), unittest.mock.patch.object(
                install, "powershell_profiles", side_effect=AssertionError("profile work was not skipped")
            ), contextlib.redirect_stdout(output):
                rc = install.main(
                    [
                        "--dry-run",
                        "--skip-shell",
                        "--home",
                        str(home),
                        "--binary",
                        str(fake_bin),
                        "--force-platform",
                    ]
                )
                uninstall_rc = install.main(
                    [
                        "--dry-run",
                        "--uninstall",
                        "--skip-shell",
                        "--home",
                        str(home),
                        "--binary",
                        str(fake_bin),
                    ]
                )
            self.assertEqual((rc, uninstall_rc), (0, 0))
            self.assertNotIn("PowerShell profile", output.getvalue())
            self.assertFalse((home / "Documents").exists())

    def test_repeat_install_and_uninstall_manage_both_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp)
            binary = home / "程序/agy.exe"
            binary.parent.mkdir(parents=True)
            binary.write_bytes(b"MZ")
            profiles = [
                home / "Documents/WindowsPowerShell/Microsoft.PowerShell_profile.ps1",
                home / "Documents/PowerShell/Microsoft.PowerShell_profile.ps1",
            ]
            completed = subprocess.CompletedProcess([], 0)

            with unittest.mock.patch.object(install, "IS_WINDOWS", True), unittest.mock.patch.object(
                install, "check_prerequisites", return_value=([], "1.5.9")
            ), unittest.mock.patch.object(
                install, "powershell_profiles", return_value=profiles
            ), unittest.mock.patch.object(
                install.subprocess, "run", return_value=completed
            ):
                self.assertEqual(
                    install.install(home, binary, window="512K", dry_run=False, skip_shell=False, force_platform=True),
                    0,
                )
                first = {profile: profile.read_bytes() for profile in profiles}
                self.assertEqual(
                    install.install(home, binary, window="512K", dry_run=False, skip_shell=False, force_platform=True),
                    0,
                )
                self.assertEqual({profile: profile.read_bytes() for profile in profiles}, first)
                self.assertEqual(install.uninstall(home, binary, dry_run=False, skip_shell=False), 0)

            for profile in profiles:
                self.assertNotIn(install.MARKER_BEGIN, profile.read_text(encoding="utf-8"))

    def test_wrapper_cmd_uses_environment_transport_for_non_ascii_home(self) -> None:
        binary = pathlib.Path(r"C:\Users\张三\AppData\Local\agy\bin\agy.exe")
        python = pathlib.Path(r"C:\Users\张三\AppData\Local\Programs\Python\Python312\python.exe")
        with unittest.mock.patch.dict(
            os.environ, {"LOCALAPPDATA": r"C:\Users\张三\AppData\Local"}, clear=False
        ):
            command = install._windows_wrapper_cmd(binary, python=python)
        self.assertIn(r'set "AGY_REAL_BINARY=%LOCALAPPDATA%\agy\bin\agy.exe"', command)
        self.assertNotIn("chcp", command)
        self.assertTrue(all(line.isascii() for line in command.splitlines()))

    def test_wrapper_cmd_falls_back_to_utf8_for_literal_non_ascii_paths(self) -> None:
        binary = pathlib.Path(r"D:\工具\agy.exe")
        python = pathlib.Path(r"D:\Python\python.exe")
        fixed_roots = {
            "LOCALAPPDATA": r"C:\OnlyLocal",
            "APPDATA": r"C:\OnlyRoaming",
            "USERPROFILE": r"C:\OnlyUser",
            "ProgramFiles": r"C:\OnlyPrograms",
            "ProgramFiles(x86)": r"C:\OnlyProgramsX86",
            "ProgramData": r"C:\OnlyData",
            "SystemRoot": r"C:\OnlyWindows",
            "TEMP": r"C:\OnlyTemp",
            "TMP": r"C:\OnlyTmp",
        }
        with unittest.mock.patch.dict(os.environ, fixed_roots, clear=False):
            command = install._windows_wrapper_cmd(binary, python=python)
        self.assertIn("chcp 65001", command)
        self.assertLess(command.index("chcp 65001"), command.index(str(binary)))
        self.assertLess(command.index("chcp %agy_patch_cp%"), command.index('"%AGY_PATCH_PYTHON%"'))
        self.assertIn("setlocal", command)
        self.assertIn("endlocal & exit /b %agy_patch_rc%", command)
        for line in command.splitlines():
            if "AGY_PATCH_PYTHON=" not in line and "AGY_REAL_BINARY=" not in line:
                self.assertTrue(line.isascii(), line)

    def test_profile_io_preserves_utf8_non_ascii_and_crlf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            profile = pathlib.Path(tmp) / "profile.ps1"
            profile.write_bytes("# 用户\r\nWrite-Host 'Café'\r\n".encode("utf-8"))
            text, encoding, newline = install.read_profile(profile)
            self.assertEqual((encoding, newline), ("utf-8", "\r\n"))
            updated, state = install.upsert_powershell_block(text)
            self.assertEqual(state, "added")
            install.write_profile(profile, updated, encoding, newline)
            raw = profile.read_bytes()
            self.assertIn("用户".encode("utf-8"), raw)
            self.assertIn("Café".encode("utf-8"), raw)
            self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))

    def test_profile_io_preserves_utf16_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            profile = pathlib.Path(tmp) / "profile.ps1"
            profile.write_bytes("# 用户\r\n".encode("utf-16"))
            text, encoding, newline = install.read_profile(profile)
            self.assertEqual((encoding, newline), ("utf-16", "\r\n"))
            updated, _ = install.upsert_powershell_block(text)
            install.write_profile(profile, updated, encoding, newline)
            raw = profile.read_bytes()
            self.assertTrue(raw.startswith(b"\xff\xfe"))
            self.assertIn("用户", raw.decode("utf-16"))
            self.assertIn(install.MARKER_BEGIN, raw.decode("utf-16"))

    @unittest.skipUnless(install.IS_WINDOWS, "runs the generated Windows batch launcher")
    def test_generated_wrapper_smoke_non_ascii_paths_no_leak_no_codepage_left(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            runtime = base / "用户目录"
            runtime.mkdir()
            (runtime / "agy_wrapper.py").write_text(
                "import json, os, pathlib, sys\n"
                "pathlib.Path(__file__).with_name('result.json').write_text(\n"
                "    json.dumps({'binary': os.environ.get('AGY_REAL_BINARY'), 'argv': sys.argv[1:]},"
                " ensure_ascii=False), encoding='utf-8')\n"
                "raise SystemExit(7)\n",
                encoding="utf-8",
            )
            binary = runtime / "程序/agy.exe"
            binary.parent.mkdir()
            binary.write_bytes(b"MZ")
            (runtime / "agy.cmd").write_text(
                install._windows_wrapper_cmd(binary, python=pathlib.Path(sys.executable)),
                encoding="utf-8",
                newline="",
            )
            runner = runtime / "runner.cmd"
            runner.write_text(
                "@echo off\r\n"
                'set "AGY_REAL_BINARY="\r\n'
                "chcp 936 >nul || exit /b 99\r\n"
                'call "%~dp0agy.cmd" one "two words"\r\n'
                'set "agy_patch_test_rc=%ERRORLEVEL%"\r\n'
                'if defined AGY_REAL_BINARY (echo leaked> "%~dp0leak.txt") else (echo clean> "%~dp0leak.txt")\r\n'
                'chcp > "%~dp0cpafter.txt"\r\n'
                '> "%~dp0rc.txt" echo %agy_patch_test_rc%\r\n',
                encoding="ascii",
                newline="",
            )
            result = subprocess.run(
                ["cmd.exe", "/c", "call", str(runner)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NEW_CONSOLE,
                timeout=60,
            )
            if result.returncode == 99:
                self.skipTest("code page 936 is unavailable on this host")
            self.assertEqual(result.returncode, 0)
            self.assertEqual((runtime / "leak.txt").read_text(encoding="ascii").strip(), "clean")
            self.assertEqual((runtime / "rc.txt").read_text(encoding="ascii").strip(), "7")
            self.assertIn("936", (runtime / "cpafter.txt").read_text(encoding="cp936", errors="replace"))
            payload = json.loads((runtime / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["binary"], str(binary))
            self.assertEqual(payload["argv"], ["one", "two words"])


if __name__ == "__main__":
    unittest.main()
