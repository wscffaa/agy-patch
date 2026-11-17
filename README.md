# `agy-patch`

English | [中文](README.zh.md)

Fail-closed binary patcher, prompt-cache relay, powerline statusline, and upgrade-rehearsal toolchain for Google Antigravity CLI (`agy`): the full patch set on macOS/arm64 and an experimental, partially verified Windows/amd64 port.

> **Why this exists:** Official `agy` updates replace a single closed-source Go Mach-O binary (`~/.local/bin/agy`) and silently drop customizations. `agy-patch` anchors patches to Go `pclntab` symbols and instruction shapes, verifies every stock site before writing, isolates upgrades through dry-run rehearsal, and cleanly separates binary patching, runtime wrappers, and system-prompt overrides.

---

## Features

- **Context Window & Checkpointer Unlock** (`patch_agy.py`): The macOS patch enables `/model` `Tab` context selection (`256K` / `512K` / `900K`) on Gemini 4 Argon, Carbon, and Hydrogen, removes >256K checkpoint and 64K `USER_INPUT` step clamps, and fixes statusline token accounting + 15s idle refresh. The Windows code contains candidate context/checkpoint/input-limit patches; their target behavior still needs end-to-end verification.
- **TUI & CoT Readability** (macOS/arm64): Full multi-line `∴ Thought...` rendering (live one-liner under `medium` verbosity, full streaming block under `high`), native terminal `Faint` + `Italic` typography, semantic ANSI `"terminal"` palette alignment, adaptive Dark/Light full-width user prompt bar with live DEC 2031 theme switching, and the breathing Gemini star pending line.
- **System Prompt Trimming** (`templates/v<ver>/`): Byte-verified overrides for embedded `system_prompts/*.tmpl` slots with explicit per-file rationale in `prompt_overrides.json`.
- **Prompt Cache Keepalive Relay** (`runtime/agy-wrapper.sh` / `runtime/agy_wrapper.py` + `runtime/cache_relay.py`): Disables silent background auto-updates (`AGY_CLI_DISABLE_AUTO_UPDATE=true`) and keeps the 5-minute implicit prompt cache warm during idle stretches for interactive and `acp` sessions (`AGY_CACHE_RELAY=off` disables it).
- **Pastel Powerline Statusline** (`runtime/statusline.sh` / `runtime/statusline.py`): Context usage, tokens, step latency/TPS, quota, and cache TTL keepalive state (`↻`, `↻n`, `✗`). The Windows port is dependency-free Python.
- **Fail-Closed Upgrade Rehearsal** (`tools/probe_agy.py`): Downloads and SHA-512 verifies releases, resolves patch sites, and patches isolated copies. macOS also probes wire payloads and PTY screens. Windows rehearsal is a byte-check and startup smoke test; it does not verify model requests, long inputs, or TUI behavior.
- **Optional ACP MCP Hub** (`integrations/consult_gemini/`, POSIX only): Zero-dependency MCP stdio server + singleton Unix-socket Hub exposing read-only `consult_gemini` over persistent `agy acp` with SQLite `gen_metadata` telemetry. This Hub has not been ported to Windows.

---

## Requirements & Support Matrix

- **macOS**: Apple Silicon (`darwin/arm64`), full patch set, `agy v1.5.3`–`v1.5.9`
- **Windows**: experimental `amd64` PE32+ port for `agy v1.5.9`; installer, runtime wrapper/statusline, prompt trimming, and candidate long-conversation patches. This is not feature parity with macOS.
- **Dependencies**: Python `>= 3.12`; macOS additionally needs `jq` and Xcode Command Line Tools (`codesign`); Windows needs no extra tools

---

## Quick Start (For Humans & Deploying Agents)

Paths are standardized around `~/.gemini/agy-patch`, `~/.local/bin/agy`, and `~/.gemini/bin/agy`.

### 1. Clone & Preview (`--dry-run`)

```sh
git clone https://github.com/wscffaa/agy-patch.git ~/.gemini/agy-patch
python3 ~/.gemini/agy-patch/scripts/install.py --dry-run
```

### 2. Install (Idempotent)

```sh
python3 ~/.gemini/agy-patch/scripts/install.py --set-window 512K
```

What `install.py` does:
1. Verifies OS/arch, Python `>= 3.12`, `codesign`, `jq`, and that `~/.local/bin/agy --version` has a matching `templates/v<ver>/` directory.
2. Backs up the clean binary to `~/.local/bin/agy.v<ver>.orig`, patches & ad-hoc signs `~/.local/bin/agy`.
3. Syncs [`runtime/agy-wrapper.sh`](runtime/agy-wrapper.sh) to `~/.gemini/bin/agy` and [`runtime/statusline.sh`](runtime/statusline.sh) to `~/.gemini/antigravity-cli/statusline.sh`.
4. Merges `statusLine` and `contextWindow` into `~/.gemini/antigravity-cli/settings.json` without overwriting existing settings.
5. Adds a managed `# >>> agy-patch >>>` block to `~/.zshrc` (`AGY_CLI_DISABLE_AUTO_UPDATE=true` + `alias agy="$HOME/.gemini/bin/agy"`). Pass `--skip-shell` to manage `~/.zshrc` yourself.

### 3. Verify

Open a new shell (or run `source ~/.zshrc`) and verify:

```sh
type agy
agy --version
python3 ~/.gemini/agy-patch/patch_agy.py --status -v
```

`type agy` should point to `~/.gemini/bin/agy`, and `patch_agy.py --status -v` should report `patched` for `~/.local/bin/agy` and `wrapper` for `~/.gemini/bin/agy`.

### Uninstall / Rollback

```sh
python3 ~/.gemini/agy-patch/scripts/install.py --uninstall
```

This restores `~/.local/bin/agy` from its `.orig` backup, removes the installed wrapper and statusline copy, cleans the managed `statusLine` entry, and strips the `# >>> agy-patch >>>` block from `~/.zshrc`.

### Windows (amd64)

The Windows port targets native PE32+ `agy v1.5.9` (`windows/amd64`). It contains candidate patches for Gemini 4 context selection, checkpoint limits, and `USER_INPUT` limits, plus prompt-template trimming, the auto-update guard, a cache relay, and a Python statusline. Resolving patch bytes, running `--version`, listing models, or completing ACP initialization does **not** prove the modified feature paths work. Authenticated `/model` selection and actual long-input/checkpoint behavior remain unverified.

Missing on Windows: TUI/CoT rendering changes, corrected context-window denominators in the CLI, 15-second idle UI refresh, and the optional Unix-socket MCP Hub. The Python statusline uses the telemetry supplied by agy; it cannot repair an incorrect denominator upstream. The version-specific byte guards in [`site_shapes_windows.json`](site_shapes_windows.json) reject unsupported releases, but do not establish semantic correctness of the patched instructions.

```powershell
git clone https://github.com/wscffaa/agy-patch.git $HOME\.gemini\agy-patch
python $HOME\.gemini\agy-patch\scripts\install.py --dry-run
python $HOME\.gemini\agy-patch\scripts\install.py --set-window 512K
```

`install.py` looks for `%LOCALAPPDATA%\agy\bin\agy.exe` (agy's own Windows install target) and falls back to `%USERPROFILE%\.local\bin\agy.exe`; pass `--binary <path>` if yours is elsewhere. It writes `%USERPROFILE%\.gemini\bin\agy.cmd` + `agy_wrapper.py`, `%USERPROFILE%\.gemini\antigravity-cli\statusline.py`, and a managed block to the PowerShell profile (`Documents\PowerShell\Microsoft.PowerShell_profile.ps1`, or the 5.1 profile when that exists). Open a new PowerShell window and run `agy --version`.

Uninstall:

```powershell
python $HOME\.gemini\agy-patch\scripts\install.py --uninstall
```

Modifying a signed PE invalidates its Authenticode signature. Whether it can run also depends on local application-control policy. Close any running `agy.exe` before `--apply`/`--uninstall`; the patcher reports a replacement error if the file is locked.

---

## Safe Upgrade Workflow

Auto-update is disabled because background updates silently overwrite the patched binary (`updater.triggerUpdateShared` checks for the exact string `true`). Always rehearse an upstream release on isolated copies before upgrading:

```sh
# 1. Check whether a newer upstream release exists (read-only)
python3 -I ~/.gemini/agy-patch/tools/check_agy_update.py

# 2. Download, verify SHA-512, scaffold templates, check stock shapes, and probe wire/TUI on copies
python3 ~/.gemini/agy-patch/tools/probe_agy.py rehearse

# 3. Once rehearse reports ok (and you have reviewed any READ items):
env -u AGY_CLI_DISABLE_AUTO_UPDATE agy update
python3 ~/.gemini/agy-patch/patch_agy.py --apply
python3 ~/.gemini/agy-patch/patch_agy.py --status -v
```

If any anchor or stock shape fails, read [`docs/references/context-window-patch.md` §5](docs/references/context-window-patch.md#5-authoring-pitfalls) and [`CONTRIBUTING.md`](CONTRIBUTING.md) before changing a site.

---

## Repository Layout

| Path | Purpose |
| :--- | :--- |
| [`patch_agy.py`](patch_agy.py) | Primary version-adaptive patcher: Mach-O/ARM64 TUI + prompt sites and PE/amd64 core + prompt sites (`--apply`, `--revert`, `--status`, `--accept-shapes`) |
| [`site_shapes.json`](site_shapes.json) | Masked ARM64 stock instruction shapes for every reviewed site (fail-closed guard against shifted offsets) |
| [`site_shapes_windows.json`](site_shapes_windows.json) | Exact PE/amd64 stock bytes and `.text` bounds for the Windows v1.5.9 sites |
| [`runtime/`](runtime/agy-wrapper.sh) | Runtime wrappers (`agy-wrapper.sh`, `agy-wrapper.cmd` + `agy_wrapper.py`), cache keepalive relay (`cache_relay.py`), powerline bars (`statusline.sh`, `statusline.py`), optional `agy-gateway.env.example` |
| [`tools/`](tools/probe_agy.py) | Upgrade rehearsal (`probe_agy.py`), release checker (`check_agy_update.py`), Mach-O inspector (`inspect_agy.py`), prompt capture & scrubbing (`capture_prompt.py`, `prompt_templates.py`), PE/amd64 resolver (`binfmt.py`, `win_amd64.py`) |
| [`scripts/`](scripts/install.py) | Installer/uninstaller and repository checks |
| [`templates/`](templates/v1.5.9/README.md) | Versioned stock templates, desired overrides, and per-file reasons |
| [`integrations/`](integrations/consult_gemini_mcp.py) | Optional POSIX-only ACP MCP Hub |
| [`docs/`](docs/architecture.md) | Architecture overview, reverse-engineering references (`docs/references/`), and forensic diagnostics (`docs/diagnostics/`) |
| [`tests/`](tests/test_repo_invariants.py) | Offline unit & repo-invariant test suite (`python3 -m unittest discover -s tests -v`) |

---

## Checks & CI

Run the sustainability gate and test suite locally:

```sh
python3 ~/.gemini/agy-patch/scripts/check_repo.py
python3 -m unittest discover -s ~/.gemini/agy-patch/tests -v
```

GitHub Actions (`.github/workflows/ci.yml`) runs both on every push and pull request across Linux, macOS, and Windows.

The ordinary test suite does not download or execute Google's binary. `AGY_WINDOWS_BINARY` enables an optional site-resolution check only; it is not a functional long-conversation test. Report passed and skipped test counts separately.

## License

[MIT](LICENSE)
