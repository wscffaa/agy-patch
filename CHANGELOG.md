# Changelog

All notable milestones for `agy-patch` are recorded here.

## [Unreleased]

### Added
- Experimental native Windows/amd64 support (PE32+): candidate context-window, checkpoint, and `USER_INPUT` limit patches, plus prompt-template trimming for `agy v1.5.9`. End-to-end long-conversation behavior remains unverified.
- PE/amd64 resolver (`tools/binfmt.py`, `tools/win_amd64.py`) with exact-byte guards (`site_shapes_windows.json`), a small x86-64 assembler, and a `.text` code cave.
- Windows installer paths: `%LOCALAPPDATA%\agy\bin\agy.exe`, `%USERPROFILE%\.gemini\bin\agy.cmd` + `agy_wrapper.py`, PowerShell profile block, no `codesign`/`jq` requirement.
- Cross-platform cache relay (temp-dir state, Windows parent watch) and a Python powerline statusline (`runtime/statusline.py`).
- Windows PE tests and CI coverage.

### Notes
- Windows TUI/CoT rendering, corrected context denominators, 15-second idle UI refresh, and the optional Unix-socket MCP Hub are not ported.
- Modifying a signed PE invalidates its Authenticode signature; local application-control policy may prevent execution.
- Windows rehearsal and the optional real-binary test establish byte resolution/startup only, not correctness of the modified feature paths.

## [0.1.0] - 2026-11-16

### Added
- Public repository structure (`runtime/`, `tools/`, `scripts/`, `integrations/`, `docs/`, `tests/`, `.github/workflows/ci.yml`).
- Idempotent installer and uninstaller (`scripts/install.py` with `--dry-run`, `--set-window`, `--uninstall`).
- Repository sustainability gate (`scripts/check_repo.py`) and offline unit test suite (`tests/`).
- `templates/v1.5.9/` support and `README.md` (`v1.5.9` adds `run-workflow` built-in skill and `run_workflow` tool).
- Automatic scrubbing in `tools/capture_prompt.py` for user rules, personal skills outside `<appDataDir>/builtin/skills/`, user MCP server listings, and `$HOME` paths.
- Bilingual root documentation (`README.md` and `README.zh.md`) and `docs/architecture.md`.

### Supported `agy` Releases
- `v1.5.3`, `v1.5.5`, `v1.5.6`, `v1.5.7`, `v1.5.8`, `v1.5.9` (`darwin/arm64`).
