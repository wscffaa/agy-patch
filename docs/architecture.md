<!-- Adapted from deepseek-ai/deepseek-harness (MIT): docs/architecture.md -->
# Architecture

English | [中文](architecture.zh.md)

Read this before changing source under `patch_agy.py`, `runtime/`, `tools/`, `scripts/`, or `integrations/`. It is an ordered map: composition, core modules, data flow, and extension points. Decision rationale lives in [Agent Notes](../.agents/notes/README.md) and deep reverse-engineering notes live in [references/](references/context-window-patch.md).

## Overview

`agy-patch` wraps and patches Google Antigravity CLI (`~/.local/bin/agy`, a closed-source `darwin/arm64` Go Mach-O binary) without mutating clean backups. The root CLI ([`patch_agy.py`](../patch_agy.py)) rebuilds the patched binary from `agy.v<ver>.orig`, syncs runtime shell/relay/statusline assets under `runtime/`, and coordinates with an isolated upgrade-rehearsal toolchain (`tools/`), an idempotent installer (`scripts/install.py`), and an optional ACP MCP Hub (`integrations/consult_gemini/`).

## Core modules

| Module | Owns | Home |
|---|---|---|
| Binary patcher | Mach-O `pclntab` symbol lookup, ARM64 anchor resolution, shape verification, ad-hoc codesign | [`patch_agy.py`](../patch_agy.py) |
| Shape guard | Masked stock instruction shapes per patch site | [`site_shapes.json`](../site_shapes.json) |
| Runtime layer | Auto-update guard, Cloud Code cache keepalive relay, pastel powerline statusline | [`runtime/agy-wrapper.sh`](../runtime/agy-wrapper.sh) |
| Upgrade toolchain | Release manifest fetch, isolated loopback/PTY rehearsal, `pclntab` & style inspection, prompt scrubbing | [`tools/probe_agy.py`](../tools/probe_agy.py) |
| Prompt baselines | Per-version stock templates, rendered `PROMPT.md`, and justified overrides | [`templates/v1.5.9/README.md`](../templates/v1.5.9/README.md) |
| Installer & gates | Idempotent setup/uninstall, Python/privacy invariants, and Tianshu repository gates | [`scripts/install.py`](../scripts/install.py) |
| ACP MCP Hub | Optional stdio MCP server + Unix-socket Hub multiplexing `agy acp` | [`integrations/consult_gemini_mcp.py`](../integrations/consult_gemini_mcp.py) |

## Data flow

1. **Installation (`scripts/install.py`)**: Verifies `darwin/arm64`, Python `>= 3.12`, `jq`, `codesign`, and `templates/v<ver>/`, invokes `patch_agy.py --apply`, merges `statusLine` and `contextWindow` into `~/.gemini/antigravity-cli/settings.json`, and writes a delimited block in `~/.zshrc`.
2. **Binary patching (`patch_agy.py --apply`)**: Copies `~/.local/bin/agy` to `agy.v<ver>.orig` on first run, resolves all ARM64 code sites and `templates/v<ver>/system_prompts/` overrides, rejects unreviewed shapes against `site_shapes.json`, writes a temp binary, runs `codesign -f -s -`, atomically replaces `~/.local/bin/agy`, and syncs `runtime/agy-wrapper.sh` and `runtime/statusline.sh`.
3. **Interactive execution (`~/.gemini/bin/agy`)**: `runtime/agy-wrapper.sh` exports `AGY_CLI_DISABLE_AUTO_UPDATE=true`, starts `runtime/cache_relay.py` for interactive and `acp` sessions, injects `CLOUD_CODE_URL`, and `exec`s `~/.local/bin/agy`.
4. **Upgrade rehearsal (`tools/probe_agy.py rehearse`)**: Fetches and SHA-512 verifies the new release in a temp directory, scaffolds `templates/v<new>/`, resolves every site group, flags new instruction shapes, and runs loopback `wire` and PTY `tui` probes before any live binary change.

## Extension points

- **Binary patch sites**: Add domain resolvers in [`patch_agy.py`](../patch_agy.py) using invariant instruction anchors and record reviewed stock shapes via `--accept-shapes`; follow [docs/references/context-window-patch.md §5](references/context-window-patch.md#5-authoring-pitfalls).
- **System prompt overrides**: Add a release directory under `templates/v<ver>/` and justify every changed `.tmpl` file in `prompt_overrides.json`.
- **Forensic & deep references**: Place subsystem internals in [references/](references/tui-styles-and-palette.md) and incident investigations in [diagnostics/](diagnostics/2026-11-04-400-investigation.md).

## Persisted formats

- `site_shapes.json`: JSON map of site name to reviewed masked 32-bit ARM64 instruction sequences.
- `templates/v<ver>/prompt_overrides.json`: JSON manifest pairing each modified `system_prompts/*.tmpl` path with a required `reason`.
- `~/.gemini/antigravity-cli/settings.json`: Upstream CLI settings JSON merged non-destructively with `statusLine` and `contextWindow`.
