# `agy-patch`

English | [中文](README.zh.md)

Fail-closed, version-adaptive binary patcher, system-prompt trimmer, prompt-cache keepalive relay, powerline statusline, and upgrade-rehearsal toolchain for Google Antigravity CLI (`agy`) on **macOS (`darwin/arm64`)** and **Windows (`windows/amd64`)**.

> **Why this exists:** Official `agy` updates replace a single closed-source Go binary (`~/.local/bin/agy` on macOS, `%LOCALAPPDATA%\agy\bin\agy.exe` on Windows) and silently drop customizations. `agy-patch` anchors patches to Go `pclntab` symbols and instruction shapes, verifies every stock site before writing, isolates upgrades through dry-run rehearsal, and cleanly separates binary patching, runtime wrappers, and system-prompt overrides.

---

## Features & Platform Support Matrix

| Capability | macOS (`darwin/arm64`) | Windows (`windows/amd64`) |
| :--- | :--- | :--- |
| **Supported `agy` releases** | `v1.5.3`–`v1.5.9` | `v1.5.9` |
| **Dependencies** | Python `>= 3.12`, `jq`, Xcode CLT (`codesign`) | Python `>= 3.12` (no extra tools required) |
| **Context Window & Checkpointer Unlock** (`256K` / `512K` / `900K`, >256K checkpoint, 64K `USER_INPUT`) | Verified | Included & exact-byte pinned (`site_shapes_windows.json`); authenticated `/model` & long-input runtime verification pending |
| **System Prompt Trimming** (`templates/v<ver>/`) | Supported (byte-verified overrides + `prompt_overrides.json`) | Supported (with LF/CRLF normalization) |
| **Prompt Cache Keepalive Relay** (`cache_relay.py`) | Supported (`agy-wrapper.sh`, interactive & `acp`) | Supported (`agy.cmd` + `agy_wrapper.py`, interactive & `acp`) |
| **Pastel Powerline Statusline** | Supported (`runtime/statusline.sh`, `jq`) | Supported (`runtime/statusline.py`, dependency-free Python) |
| **TUI & CoT Readability / Denominator Fix / 15s Idle Refresh** | Supported (`∴ Thought...`, Faint+Italic, ANSI palette, DEC 2031 prompt bar, breathing star) | Not yet ported (statusline displays upstream telemetry) |
| **Fail-Closed Upgrade Rehearsal** (`tools/probe_agy.py`) | Supported (SHA-512 + shape guard + loopback wire & PTY TUI probes) | Supported (SHA-512 + byte guard + startup smoke check) |
| **Optional ACP MCP Hub** (`integrations/consult_gemini/`) | Supported (Unix-socket Hub + SQLite telemetry) | Not ported (POSIX only) |

---

## Quick Start (macOS & Windows)

Both platforms share the same idempotent installer (`scripts/install.py`), `--set-window` option (`Default` / `256K` / `512K` / `900K`), and `--uninstall` rollback flow.

### macOS (`darwin/arm64`)

Paths are standardized around `~/.gemini/agy-patch`, `~/.local/bin/agy`, and `~/.gemini/bin/agy`.

1. **Clone & Preview (`--dry-run`)**

   ```sh
   git clone https://github.com/wscffaa/agy-patch.git ~/.gemini/agy-patch
   python3 ~/.gemini/agy-patch/scripts/install.py --dry-run
   ```

2. **Install (Idempotent)**

   ```sh
   python3 ~/.gemini/agy-patch/scripts/install.py --set-window 512K
   ```

   What `install.py` does:
   - Verifies `darwin/arm64`, Python `>= 3.12`, `codesign`, `jq`, and that `~/.local/bin/agy --version` matches a `templates/v<ver>/` directory.
   - Backs up the clean binary to `~/.local/bin/agy.v<ver>.orig`, applies the Mach-O patches, and ad-hoc signs `~/.local/bin/agy`.
   - Syncs [`runtime/agy-wrapper.sh`](runtime/agy-wrapper.sh) to `~/.gemini/bin/agy` and [`runtime/statusline.sh`](runtime/statusline.sh) to `~/.gemini/antigravity-cli/statusline.sh`.
   - Merges `statusLine` and `contextWindow` into `~/.gemini/antigravity-cli/settings.json` without overwriting existing settings.
   - Adds a managed `# >>> agy-patch >>>` block to `~/.zshrc` (`AGY_CLI_DISABLE_AUTO_UPDATE=true` + `alias agy="$HOME/.gemini/bin/agy"`). Pass `--skip-shell` to manage `~/.zshrc` yourself.

3. **Verify**

   Open a new shell (or run `source ~/.zshrc`) and check:

   ```sh
   type agy
   agy --version
   python3 ~/.gemini/agy-patch/patch_agy.py --status -v
   ```

   `type agy` should point to `~/.gemini/bin/agy`, and `patch_agy.py --status -v` should report `patched` for `~/.local/bin/agy` and `wrapper` for `~/.gemini/bin/agy`.

4. **Uninstall / Rollback**

   ```sh
   python3 ~/.gemini/agy-patch/scripts/install.py --uninstall
   ```

   Restores `~/.local/bin/agy` from its `.orig` backup, removes the wrapper and statusline copy, cleans the managed `statusLine` entry, and strips the `# >>> agy-patch >>>` block from `~/.zshrc`.

---

### Windows (`amd64`)

Paths are standardized around `$HOME\.gemini\agy-patch`, `%LOCALAPPDATA%\agy\bin\agy.exe` (falling back to `%USERPROFILE%\.local\bin\agy.exe`, or pass `--binary <path>`), and `%USERPROFILE%\.gemini\bin\agy.cmd`.

> **Before patching/uninstalling on Windows:** Close any running `agy.exe` processes so the executable is not locked. Note that modifying a signed PE invalidates its Authenticode signature, so execution remains subject to local application-control policy.

1. **Clone & Preview (`--dry-run`)**

   ```powershell
   git clone https://github.com/wscffaa/agy-patch.git $HOME\.gemini\agy-patch
   python $HOME\.gemini\agy-patch\scripts\install.py --dry-run
   ```

2. **Install (Idempotent)**

   ```powershell
   python $HOME\.gemini\agy-patch\scripts\install.py --set-window 512K
   ```

   What `install.py` does:
   - Verifies `Windows/amd64`, Python `>= 3.12`, and that `agy.exe --version` matches a supported release (`v1.5.9`).
   - Backs up the clean binary to `agy.exe.v<ver>.orig` and applies the byte-verified PE/amd64 patches + `system_prompts/*.tmpl` overrides.
   - Installs [`runtime/agy-wrapper.cmd`](runtime/agy-wrapper.cmd) (generated launcher), [`runtime/agy_wrapper.py`](runtime/agy_wrapper.py), and [`runtime/cache_relay.py`](runtime/cache_relay.py) under `%USERPROFILE%\.gemini\bin\`, and [`runtime/statusline.py`](runtime/statusline.py) to `%USERPROFILE%\.gemini\antigravity-cli\statusline.py`.
   - Merges `statusLine` and `contextWindow` into `%USERPROFILE%\.gemini\antigravity-cli\settings.json`.
   - Adds a managed `# >>> agy-patch >>>` block (`AGY_CLI_DISABLE_AUTO_UPDATE=true` + prepending `%USERPROFILE%\.gemini\bin` to `PATH`) to the installed PowerShell profile(s) (`Documents\WindowsPowerShell\Microsoft.PowerShell_profile.ps1` and/or `Documents\PowerShell\Microsoft.PowerShell_profile.ps1`). Pass `--skip-shell` to manage profiles yourself.

3. **Verify**

   Open a new PowerShell window and check:

   ```powershell
   Get-Command agy
   agy --version
   python $HOME\.gemini\agy-patch\patch_agy.py --status -v
   ```

4. **Uninstall / Rollback**

   ```powershell
   python $HOME\.gemini\agy-patch\scripts\install.py --uninstall
   ```

   Restores `agy.exe` from its `.orig` backup, removes the installed wrapper/relay/statusline copies, cleans the managed `statusLine` entry, and strips the `# >>> agy-patch >>>` block from managed PowerShell profiles.

---

## Safe Upgrade Workflow

Auto-update is disabled because background updates silently overwrite the patched binary (`updater.triggerUpdateShared` checks for the exact string `true`). Always rehearse an upstream release on isolated copies before upgrading:

**macOS (`sh`):**

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

**Windows (`PowerShell`):**

```powershell
# 1. Check whether a newer upstream release exists (read-only)
python -I $HOME\.gemini\agy-patch\tools\check_agy_update.py

# 2. Download, verify SHA-512, check Windows exact-byte guards, and run startup smoke check
python $HOME\.gemini\agy-patch\tools\probe_agy.py rehearse

# 3. Once rehearse reports ok (close running agy.exe before --apply):
Remove-Item Env:AGY_CLI_DISABLE_AUTO_UPDATE -ErrorAction SilentlyContinue
& "$env:LOCALAPPDATA\agy\bin\agy.exe" update
python $HOME\.gemini\agy-patch\patch_agy.py --apply
python $HOME\.gemini\agy-patch\patch_agy.py --status -v
```

If any anchor or stock shape fails, read [`docs/references/context-window-patch.md` §5](docs/references/context-window-patch.md#5-authoring-pitfalls) and [`CONTRIBUTING.md`](CONTRIBUTING.md) before changing a site.

---

## Repository Layout

| Path | Purpose |
| :--- | :--- |
| [`patch_agy.py`](patch_agy.py) | Primary version-adaptive patcher: Mach-O/ARM64 TUI + prompt sites and PE/amd64 core + prompt sites (`--apply`, `--revert`, `--status`, `--accept-shapes`) |
| [`site_shapes.json`](site_shapes.json) | Masked ARM64 stock instruction shapes for every reviewed macOS site (fail-closed guard against shifted offsets) |
| [`site_shapes_windows.json`](site_shapes_windows.json) | Exact PE/amd64 stock bytes and `.text` bounds for reviewed Windows sites |
| [`runtime/`](runtime/agy-wrapper.sh) | Runtime wrappers (`agy-wrapper.sh`, `agy-wrapper.cmd` + `agy_wrapper.py`), cache keepalive relay (`cache_relay.py`), powerline statuslines (`statusline.sh`, `statusline.py`), optional `agy-gateway.env.example` |
| [`tools/`](tools/probe_agy.py) | Upgrade rehearsal (`probe_agy.py`), release checker (`check_agy_update.py`), Mach-O inspector (`inspect_agy.py`), prompt capture & scrubbing (`capture_prompt.py`, `prompt_templates.py`), PE/amd64 resolver (`binfmt.py`, `win_amd64.py`) |
| [`scripts/`](scripts/install.py) | Cross-platform idempotent installer/uninstaller (`install.py`) and repository checks (`check_repo.py`) |
| [`templates/`](templates/v1.5.9/README.md) | Versioned stock templates, captured `PROMPT.md`/`tools.json`, desired overrides, and `prompt_overrides.json` |
| [`integrations/`](integrations/consult_gemini_mcp.py) | Optional POSIX-only `consult_gemini` MCP stdio server + ACP Unix-socket Hub |
| [`docs/`](docs/architecture.md) | Architecture overview, reverse-engineering references (`docs/references/`), and forensic diagnostics (`docs/diagnostics/`) |
| [`tests/`](tests/test_repo_invariants.py) | Offline unit & repo-invariant test suite (`python -m unittest discover -s tests -v`) |

---

## Checks & CI

Run the repository gate and offline unit test suite locally:

```sh
# macOS / Linux
python3 ~/.gemini/agy-patch/scripts/check_repo.py
python3 -m unittest discover -s ~/.gemini/agy-patch/tests -v
```

```powershell
# Windows (PowerShell)
python $HOME\.gemini\agy-patch\scripts\check_repo.py
python -m unittest discover -s $HOME\.gemini\agy-patch\tests -v
```

GitHub Actions (`.github/workflows/ci.yml`) runs both on every push and pull request across Linux (`ubuntu-latest`), macOS (`macos-latest`), and Windows (`windows-latest`).

The ordinary test suite does not download or execute Google's binary. `AGY_WINDOWS_BINARY` enables an optional local site-resolution check only; report passed and skipped test counts separately.

## License

[MIT](LICENSE)
