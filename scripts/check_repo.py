#!/usr/bin/env python3
"""Sustainability and hygiene gate for agy-patch.

Checks:
  1. Python syntax compilation across all tracked/repo .py files.
  2. Shell syntax (`zsh -n`) for runtime/*.sh when zsh is installed.
  3. `site_shapes.json` schema validity.
  4. `templates/v*/` completeness and `prompt_overrides.json` parity with `system_prompts/`.
  5. Privacy/secret guard across `templates/*/stock/PROMPT.md` and source files.
  6. Relative Markdown link integrity across READMEs, CONTRIBUTING, docs/, and templates/.
"""

from __future__ import annotations

import json
import pathlib
import py_compile
import re
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools import prompt_templates

COMMON_PRIVACY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("personal home path", re.compile(r"/(?:Users|home)/[A-Za-z0-9._-]+/")),
    ("raw user rule block", re.compile(r"<RULE\[[^\]]+\]>")),
    ("secret token prefix", re.compile(r"\b(?:AIza[A-Za-z0-9_-]{20,}|gho_[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|ya29\.[A-Za-z0-9._-]{20,})\b")),
)
PROMPT_ONLY_PATTERN = ("non-builtin skill path", re.compile(r"^- .+ \((?!<appDataDir>/builtin/skills/)[^)]+/SKILL\.md\):", re.M))
INLINE_CODE_RE = re.compile(r"`[^`]*`")
MD_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)#\s]+)(?:#[^)\s]*)?\)")


def check_python_compile() -> list[str]:
    errors: list[str] = []
    for path in sorted(REPO.rglob("*.py")):
        if ".cache" in path.parts or "__pycache__" in path.parts:
            continue
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            errors.append(f"py_compile failed for {path.relative_to(REPO)}: {exc}")
    return errors


def check_shell_syntax() -> list[str]:
    zsh = shutil.which("zsh")
    if not zsh:
        print("[skip] Shell syntax: zsh is not installed.", file=sys.stderr)
        return []
    try:
        probe = subprocess.run([zsh, "--version"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        if sys.platform != "win32":
            return [f"could not run zsh: {exc}"]
        print(f"[skip] Shell syntax: zsh could not run ({exc}).", file=sys.stderr)
        return []
    if probe.returncode != 0:
        if sys.platform != "win32":
            return [f"zsh --version failed with exit code {probe.returncode}"]
        print(f"[skip] Shell syntax: installed zsh failed with exit code {probe.returncode}.", file=sys.stderr)
        return []
    errors: list[str] = []
    for sh in sorted((REPO / "runtime").glob("*.sh")):
        # Windows checkouts can carry CRLF; zsh -n rejects the CR before the newline.
        with tempfile.NamedTemporaryFile("wb", suffix=".sh", delete=False) as tmp:
            tmp.write(sh.read_bytes().replace(b"\r\n", b"\n"))
            tmp_path = pathlib.Path(tmp.name)
        try:
            proc = subprocess.run([zsh, "-n", str(tmp_path)], capture_output=True, text=True)
        finally:
            tmp_path.unlink(missing_ok=True)
        if proc.returncode != 0:
            errors.append(f"zsh -n failed for {sh.relative_to(REPO)}: {proc.stderr.strip()}")
    return errors


def check_site_shapes() -> list[str]:
    errors: list[str] = []
    path = REPO / "site_shapes.json"
    try:
        data = json.loads(path.read_text())
    except Exception as exc:
        return [f"invalid site_shapes.json: {exc}"]
    if not isinstance(data, dict) or not data:
        return ["site_shapes.json must be a non-empty object"]
    for site_name, shapes in data.items():
        if not isinstance(shapes, list) or not shapes or not all(isinstance(s, str) and s for s in shapes):
            errors.append(f"site_shapes.json[{site_name!r}] must be a non-empty list of strings")
    return errors


def check_site_shapes_windows() -> list[str]:
    """Validate the reviewed PE/amd64 stock bytes and text-section bounds."""
    path = REPO / "site_shapes_windows.json"
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return []
    except Exception as exc:
        return [f"invalid site_shapes_windows.json: {exc}"]
    if not isinstance(data, dict) or not data:
        return ["site_shapes_windows.json must be a non-empty object"]
    errors: list[str] = []
    for version, spec in data.items():
        if not isinstance(spec, dict):
            errors.append(f"site_shapes_windows.json[{version!r}] must be an object")
            continue
        vsize, raw = spec.get("text_vsize"), spec.get("text_raw_size")
        if not isinstance(vsize, int) or not isinstance(raw, int) or not 0 < vsize < raw:
            errors.append(f"site_shapes_windows.json[{version!r}] needs 0 < text_vsize < text_raw_size")
        sites = spec.get("sites")
        if not isinstance(sites, dict) or not sites:
            errors.append(f"site_shapes_windows.json[{version!r}].sites must be a non-empty object")
            continue
        for name, shape in sites.items():
            try:
                if not bytes.fromhex(shape):
                    raise ValueError("empty")
            except (TypeError, ValueError):
                errors.append(f"site_shapes_windows.json[{version!r}][{name!r}] is not a non-empty hex string")
    return errors


def check_templates() -> list[str]:
    errors: list[str] = []
    versions = sorted(p for p in (REPO / "templates").glob("v*") if p.is_dir())
    if not versions:
        return ["no templates/v*/ directories found"]

    for vdir in versions:
        for req in ("prompt_overrides.json", "README.md", "stock/PROMPT.md", "stock/tools.json"):
            if not (vdir / req).is_file():
                errors.append(f"missing {vdir.relative_to(REPO)}/{req}")

        stock_dir = vdir / "stock" / "system_prompts"
        desired_dir = vdir / "system_prompts"
        overrides_path = vdir / "prompt_overrides.json"
        if not stock_dir.is_dir() or not desired_dir.is_dir() or not overrides_path.is_file():
            continue

        try:
            overrides = json.loads(overrides_path.read_text()).get("templates", {})
        except Exception as exc:
            errors.append(f"invalid JSON in {overrides_path.relative_to(REPO)}: {exc}")
            continue

        stock_files = {p.relative_to(stock_dir).as_posix(): p for p in stock_dir.rglob("*.tmpl")}
        desired_files = {p.relative_to(desired_dir).as_posix(): p for p in desired_dir.rglob("*.tmpl")}
        if set(stock_files) != set(desired_files):
            missing = sorted(set(stock_files) - set(desired_files))
            extra = sorted(set(desired_files) - set(stock_files))
            errors.append(f"{vdir.name}: template set mismatch (missing={missing}, extra={extra})")
            continue

        for name, stock_path in sorted(stock_files.items()):
            differs = stock_path.read_bytes() != desired_files[name].read_bytes()
            reason = (overrides.get(name) or {}).get("reason", "").strip()
            if differs and not reason:
                errors.append(f"{vdir.name}: {name} differs from stock/ without a reason in prompt_overrides.json")
            if not differs and name in overrides:
                errors.append(f"{vdir.name}: {name} matches stock/ but still has an override entry")

        # Also validate template naming helper keeps matching.
        _ = prompt_templates.TEMPLATES_ROOT
    return errors


def check_privacy_and_secrets() -> list[str]:
    errors: list[str] = []
    targets = list((REPO / "templates").glob("v*/stock/PROMPT.md"))
    for root_dir in ("runtime", "tools", "scripts", "integrations", "docs"):
        targets.extend((REPO / root_dir).rglob("*.py"))
        targets.extend((REPO / root_dir).rglob("*.sh"))
        targets.extend((REPO / root_dir).rglob("*.md"))
    targets.extend(REPO.glob("*.py"))
    targets.extend(REPO.glob("*.md"))

    prompt_docs = set((REPO / "templates").glob("v*/stock/PROMPT.md"))
    for path in sorted(set(targets)):
        if ".cache" in path.parts or "__pycache__" in path.parts:
            continue
        text = path.read_text(errors="replace")
        patterns = COMMON_PRIVACY_PATTERNS + ((PROMPT_ONLY_PATTERN,) if path in prompt_docs else ())
        for label, pattern in patterns:
            if m := pattern.search(text):
                errors.append(f"privacy guard ({label}) matched in {path.relative_to(REPO)}: {m.group(0)!r}")
    return errors


def check_markdown_links() -> list[str]:
    errors: list[str] = []
    md_files = list(REPO.glob("*.md"))
    md_files.extend((REPO / "docs").rglob("*.md"))
    md_files.extend((REPO / "templates").glob("v*/README.md"))

    for md in sorted(set(md_files)):
        text = md.read_text(errors="replace")
        in_fence = False
        for line_no, line in enumerate(text.splitlines(), 1):
            if line.lstrip().startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            cleaned = INLINE_CODE_RE.sub("", line)
            for match in MD_LINK_RE.finditer(cleaned):
                target = match.group(1)
                if target.startswith(("http://", "https://", "mailto:")):
                    continue
                resolved = (md.parent / target).resolve()
                if not resolved.exists():
                    errors.append(f"broken link in {md.relative_to(REPO)}:{line_no} -> {target}")
    return errors


def run_all() -> list[str]:
    checks = (
        check_python_compile,
        check_shell_syntax,
        check_site_shapes,
        check_site_shapes_windows,
        check_templates,
        check_privacy_and_secrets,
        check_markdown_links,
    )
    errors: list[str] = []
    for fn in checks:
        errors.extend(fn())
    return errors


def main() -> int:
    errors = run_all()
    if errors:
        for err in errors:
            print(f"[FAIL] {err}", file=sys.stderr)
        return 1
    print("[ok] Available repository checks passed; any unavailable checks are listed as [skip].")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
