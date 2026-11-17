"""Offline tests for the standalone tools/prompt_templates.py CLI."""

from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = REPO / "tools/prompt_templates.py"


class PromptTemplatesCliTests(unittest.TestCase):
    def test_help_works_when_run_as_a_script_from_another_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--help"],
                cwd=tmp,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("usage", result.stdout.lower())
        self.assertNotIn("ModuleNotFoundError", result.stderr)

    def test_help_works_isolated_without_script_or_cwd_on_sys_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, "-I", str(SCRIPT), "--help"],
                cwd=tmp,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("usage", result.stdout.lower())
        self.assertNotIn("ModuleNotFoundError", result.stderr)

    def test_module_import_still_exposes_templates_root(self) -> None:
        from tools import prompt_templates

        self.assertTrue(prompt_templates.TEMPLATES_ROOT.is_dir())
        self.assertEqual(prompt_templates.TEMPLATES_ROOT, REPO / "templates")


if __name__ == "__main__":
    unittest.main()
