# Contributing & Supporting New `agy` Releases

English | [中文](CONTRIBUTING.zh.md)

`agy-patch` targets a closed-source Go binary: Mach-O/arm64 on macOS and PE32+/amd64 on Windows. Sustainability depends on **fail-closed upgrades**: never blindly apply old byte offsets to a new upstream release.

## Upgrading to a New `agy` Release

1. **Check for updates without modifying `~/.local/bin/agy`:**
   ```sh
   python3 -I tools/check_agy_update.py
   ```
2. **Rehearse on isolated copies first:**
   ```sh
   python3 tools/probe_agy.py rehearse
   ```
   `rehearse` downloads and verifies the SHA-512 of the new release in a temporary directory, dumps or scaffolds `templates/v<new>/`, resolves every patch group, checks stock instruction shapes against `site_shapes.json`, patches the temporary copy, and probes wire requests and TUI screens.
3. **Review any `REVIEW` / `READ` / `FAIL` items:**
   - If stock instruction shapes changed at a site, inspect them with:
     ```sh
     python3 tools/probe_agy.py sites ~/.local/bin/agy.v<old>.orig <tmp>/agy.v<new>.orig
     ```
     Read [`docs/references/context-window-patch.md` §5](./docs/references/context-window-patch.md#5-authoring-pitfalls) before editing any resolver or recording shapes with `--accept-shapes`.
   - If embedded templates changed, diff `templates/v<old>/stock` against `templates/v<new>/stock`, update `templates/v<new>/system_prompts/` and `prompt_overrides.json`, and add `templates/v<new>/README.md`.
4. **Upgrade the live binary only after `rehearse` is clean:**
   ```sh
   env -u AGY_CLI_DISABLE_AUTO_UPDATE agy update
   python3 patch_agy.py --apply
   python3 patch_agy.py --status -v
   ```

## Windows (amd64) Releases

Windows patches are pinned to `agy v1.5.9` in `site_shapes_windows.json`. For a new release:

1. Download `cli_windows_x64.exe` from the updater manifest and verify its SHA-512.
2. Run `python patch_agy.py --status --binary <new.exe> -v`; a changed `.text` size or any stock-byte mismatch fails closed.
3. Review the changed function bodies, branch destinations, register/stack contracts, and patch instruction semantics before updating `tools/win_amd64.py` or the authoritative stock-byte entries in `site_shapes_windows.json`. Matching a short instruction prefix alone is not a behavioral proof.
4. Patch an isolated copy. `--version`, `models`, and ACP `initialize` are startup/protocol smoke checks only. Verify `/model` + Tab, the transmitted checkpoint limit, preservation of inputs above 64K, and idle cache replay separately before recommending installation. Windows rehearsal reports incomplete behavioral coverage when wire/screens are skipped.
5. Windows TUI/CoT rendering, corrected context denominators, 15-second idle UI refresh, and the optional Unix-socket MCP Hub are not ported. Keep the PR experimental until the required behavior has evidence; do not infer parity from passing unit tests.

## Before Opening a PR

Run the repository checks and unit tests:

```sh
python3 scripts/check_repo.py
python3 -m unittest discover -s tests -v
```

Never commit real credentials, `~/.gemini/agy-gateway.env`, `.cache/`, or unredacted personal skills/rules inside `templates/*/stock/PROMPT.md`.
