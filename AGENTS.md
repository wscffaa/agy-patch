<!-- Adapted from deepseek-ai/deepseek-harness (MIT): AGENTS.md -->
# AGENTS.md

`agy-patch` is a fail-closed, version-adaptive ARM64 binary patcher, prompt-cache keepalive wrapper, statusline, and upgrade-rehearsal harness for Google Antigravity CLI (`agy`). Read [docs/architecture.md](docs/architecture.md) before changing code under `patch_agy.py`, `runtime/`, `tools/`, `scripts/`, or `integrations/`; follow [docs/AGENTS.md](docs/AGENTS.md) for documentation.

## Pre-stable APIs and persisted data

CLI flags and internal module helpers are pre-stable; update every caller in the same change and record externally visible breaking changes in [CHANGELOG.md](CHANGELOG.md).

Persisted state (`site_shapes.json`, `templates/v<ver>/`, `~/.local/bin/agy.v<ver>.orig`, and `~/.gemini/antigravity-cli/settings.json`) is versioned or merged non-destructively. Never mutate a clean `.orig` backup or apply unreviewed instruction shapes. See [docs/architecture.md](docs/architecture.md) for the owning format references.

## Repository layout

```
patch_agy.py     primary version-adaptive ARM64 binary and template patcher
site_shapes.json reviewed stock instruction shapes (fail-closed offset guard)
runtime/         installed wrapper, cache keepalive relay, and statusline
tools/           upgrade rehearsal, update check, Mach-O inspection, prompt capture
scripts/         idempotent installer (install.py), repo checks (check_repo.py), and Tianshu gates (scripts/tianshu/)
integrations/    optional consult_gemini MCP stdio server and ACP Unix-socket Hub
templates/       per-release stock baselines, captured prompts, and system_prompts overrides
tests/           offline unit and repository-invariant tests (stdlib unittest)
docs/            bilingual architecture, subsystems, cookbooks, references, and diagnostics
.agents/notes/   Agent Notes: decision records (.agents/notes/README.md)
```

## Commands

```sh
python3 scripts/install.py --dry-run                       # preview local installation
python3 scripts/check_repo.py                                # Python, templates, privacy, and link gate
python3 -m unittest discover -s tests -v                     # offline unit test suite
python3 tools/probe_agy.py rehearse                          # isolated rehearsal for new agy releases
npm --prefix scripts/tianshu ci                              # install Tianshu gates
npm --prefix scripts/tianshu run gates -- --repo "$PWD"      # all Tianshu repository gates
npm --prefix scripts/tianshu run gate -- <name> --repo "$PWD" # one Tianshu gate
```

Run focused checks that match the change before pushing. CI owns the full matrix; do not repeat a passing check for commit or push.

## Conventions

- Validate at external boundaries (Mach-O headers, `pclntab` symbols, `site_shapes.json`, `templates/v<ver>/`, `settings.json`, HTTP relay headers); trust internal invariants between checked helpers. See [docs/defensive-patterns/README.md](docs/defensive-patterns/README.md).
- Failures are fail-closed and explicit: refuse patching on missing backups, version mismatches, missing override reasons, or unreviewed instruction shapes.
- Never bypass `codesign -f -s -` after modifying a Mach-O binary on `darwin/arm64`.
- An empty `except` names the exception and why it is safe to ignore; keep the `try` to one operation.
- Paths and runtime toggles (`AGY_CACHE_RELAY`, `AGY_BIN`, `AGY_CLI_DISABLE_AUTO_UPDATE`, `contextWindow`) are explicit configuration; protocol constants stay fixed.
- Comments state contracts, preconditions, and non-obvious ARM64/Mach-O invariants. Do not restate code or narrate tests. See [docs/AGENTS.md](docs/AGENTS.md).
- Files end with one trailing newline. Pre-commit runs `git diff --cached --check`.
- Never commit credentials, `~/.gemini/agy-gateway.env`, `.cache/`, or unredacted personal skills/rules inside `templates/*/stock/PROMPT.md`.

## Testing

- Tests describe behavior, not implementation. Change obsolete behavior together with its tests and explain why in the PR.
- Each requirement gets tests for happy path, boundary/empty inputs, error handling, and valid state transitions.
- Keep unit tests in `tests/` offline and quota-free (no live Google Cloud Code calls).

## Documentation

- Docs accompany every code change. Update affected READMEs and module docstrings in the same change.
- One physical line per paragraph. Bilingual pairs (`*.md` and `*.zh.md`) update together; see [docs/AGENTS.md](docs/AGENTS.md). `docs/references/`, `docs/diagnostics/`, and `templates/` are excluded from translation pairing in `.tianshu/config.json`.

## Agent Notes

- Write an Agent Note only for durable decision rationale. Mechanical and local edits are exempt. See [.agents/notes/README.md](.agents/notes/README.md).
- Every new Agent Note runs a supersession check. Archived notes are frozen; never edit them or treat them as current authority.

## Issues and PRs

- Issues start from the templates in [.github/ISSUE_TEMPLATE](.github/ISSUE_TEMPLATE). Labels come from the Tianshu kit: `type/*`, `severity/*`, `env/*`, `priority/*`, `stage/rework`, `agent/auto`, `status/needs-owner`, and `area/*`.
- Every Issue and PR carries exactly one `type/*` label; a `type/bug` also carries one `severity/S1`–`S3` and one `env/prod` or `env/test`; at most one `priority/p0`–`p3`.
- Every PR also carries every materially affected `area/*` label, at least one.
- PR descriptions follow [.github/pull_request_template.md](.github/pull_request_template.md): Motivation, Changes, Testing, AI Usage. Link issues with `Fixes #N` or `Refs #N`.
- Disclose AI participation in the AI Usage section.

## Editing these instructions

This file is the real instruction file; do not add `CLAUDE.md` or other duplicate instruction files. Keep each rule self-contained with a link to its home. Condense when clarity survives. Raise a ceiling in `.tianshu/doc-budgets.json` only when the required content needs the space, and justify the diff.
