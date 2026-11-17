# AGENTS.md

`agy-patch` is a fail-closed binary patcher, prompt-cache relay, statusline, and upgrade-rehearsal harness for Google Antigravity CLI (`agy`). macOS/arm64 has the full Mach-O patch set; Windows/amd64 is an experimental PE port with unverified long-conversation behavior. Read [docs/architecture.md](docs/architecture.md) before changing source code.

## Repository layout

```text
patch_agy.py     Primary version-adaptive patcher (Mach-O/ARM64 + PE/amd64 dispatch)
site_shapes.json Reviewed ARM64 stock instruction shapes (fail-closed offset guard)
site_shapes_windows.json Exact PE/amd64 stock bytes and .text bounds for the Windows sites
runtime/         Runtime wrappers (`agy-wrapper.sh`, `agy-wrapper.cmd` + `agy_wrapper.py`), `cache_relay.py`, statuslines
tools/           Upgrade rehearsal (`probe_agy.py`), update check, Mach-O inspector, prompt capture, PE/amd64 resolver (`binfmt.py`, `win_amd64.py`)
scripts/         Idempotent installer (`install.py`) and repository hygiene checks (`check_repo.py`)
integrations/    Optional `consult_gemini` MCP stdio server and ACP Unix-socket Hub
templates/       Per-release (`v1.5.3`–`v1.5.9`) stock baselines and `system_prompts/` overrides
tests/           Offline unit and repository-invariant tests (`unittest`)
docs/            Architecture overview, reverse-engineering references, and diagnostics
```

## Common commands

```sh
python3 scripts/install.py --dry-run      # Preview local installation steps
python3 scripts/install.py                # Idempotent setup (patch, wrapper, statusline, settings, shell block)
python scripts/install.py --dry-run       # Same on Windows (PowerShell profile instead of .zshrc)
python3 scripts/check_repo.py             # Python compile, shell syntax, template parity, privacy, and links
python3 -m unittest discover -s tests -v  # Offline unit test suite
python3 tools/probe_agy.py rehearse       # Isolated upgrade rehearsal against a new agy release
```

## Hard invariants

- **Never mutate `.orig` backups**: `patch_agy.py --apply` always rebuilds `~/.local/bin/agy` from `~/.local/bin/agy.v<ver>.orig`.
- **Always re-sign modified Mach-O binaries**: run `codesign -f -s -` after patching on `darwin/arm64`. PE builds are not re-signed; modifying a signed PE invalidates Authenticode, and local policy may prevent execution.
- **Windows sites are pinned by exact bytes**: `tools/win_amd64.py` refuses a binary whose `.text` bounds or any reviewed byte differ from `site_shapes_windows.json`. Never widen a guard to make a new release pass; review the new bytes first.
- **Close agy before Windows apply/uninstall**: the PE is replaced atomically, and a running `agy.exe` locks the file.
- **Fail closed on shifted instructions**: never bypass `site_shapes.json` verification without inspecting diffs via `python3 tools/probe_agy.py sites <old.orig> <new.orig>` and reading [`docs/references/context-window-patch.md` §5](docs/references/context-window-patch.md#5-authoring-pitfalls).
- **Keep tests offline and quota-free**: unit tests under `tests/` must not make live upstream API calls or mutate user `$HOME`.
- **Distinguish smoke checks from feature proof**: byte resolution, `--version`, model listing, and ACP initialization do not validate context limits, truncation, or idle cache reuse. Report skipped behavior probes and unavailable ports explicitly.
- **Never commit secrets or unredacted user context**: keep `.cache/`, `~/.gemini/agy-gateway.env`, user rules, personal skills, and configured MCP lists out of tracked files.
