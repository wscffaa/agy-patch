# AGENTS.md

`agy-patch` is a fail-closed, version-adaptive ARM64 binary patcher, prompt-cache keepalive wrapper, statusline, and upgrade-rehearsal harness for Google Antigravity CLI (`agy`). Read [docs/architecture.md](docs/architecture.md) before changing source code.

## Repository layout

```text
patch_agy.py     Primary version-adaptive ARM64 binary & template patcher
site_shapes.json Reviewed stock instruction shapes (fail-closed offset guard)
runtime/         Runtime wrapper (`agy-wrapper.sh`), `cache_relay.py`, `statusline.sh`
tools/           Upgrade rehearsal (`probe_agy.py`), update check, Mach-O inspector, prompt capture
scripts/         Idempotent installer (`install.py`) and repository hygiene checks (`check_repo.py`)
integrations/    Optional `consult_gemini` MCP stdio server and ACP Unix-socket Hub
templates/       Per-release (`v1.5.3`–`v1.5.9`) stock baselines and `system_prompts/` overrides
tests/           Offline unit and repository-invariant tests (`unittest`)
docs/            Architecture overview, reverse-engineering references, and diagnostics
```

## Common commands

```sh
python3 scripts/install.py --dry-run      # Preview local installation steps
python3 scripts/install.py                # Idempotent setup (patch, wrapper, statusline, settings, .zshrc)
python3 scripts/check_repo.py             # Python compile, shell syntax, template parity, privacy, and links
python3 -m unittest discover -s tests -v  # Offline unit test suite
python3 tools/probe_agy.py rehearse       # Isolated upgrade rehearsal against a new agy release
```

## Hard invariants

- **Never mutate `.orig` backups**: `patch_agy.py --apply` always rebuilds `~/.local/bin/agy` from `~/.local/bin/agy.v<ver>.orig`.
- **Always re-sign modified Mach-O binaries**: run `codesign -f -s -` after patching on `darwin/arm64`.
- **Fail closed on shifted instructions**: never bypass `site_shapes.json` verification without inspecting diffs via `python3 tools/probe_agy.py sites <old.orig> <new.orig>` and reading [`docs/references/context-window-patch.md` §5](docs/references/context-window-patch.md#5-authoring-pitfalls).
- **Keep tests offline and quota-free**: unit tests under `tests/` must not make live upstream API calls or mutate user `$HOME`.
- **Never commit secrets or unredacted user context**: keep `.cache/`, `~/.gemini/agy-gateway.env`, user rules, personal skills, and configured MCP lists out of tracked files.
