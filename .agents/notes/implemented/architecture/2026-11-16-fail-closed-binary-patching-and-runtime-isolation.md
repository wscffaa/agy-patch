# Agent Note: Fail-Closed Binary Patching and Runtime Isolation

Status: implemented

English | [中文](2026-11-16-fail-closed-binary-patching-and-runtime-isolation.zh.md)

## Problem

`agy` ships as a single closed-source Go Mach-O binary (`~/.local/bin/agy`) whose background updater silently overwrites local modifications and whose internal struct offsets shift across releases. Patching offsets blindly risks corrupting unrelated instructions, while mixing binary patching logic with runtime wrappers and upgrade tooling makes releases fragile and hard to deploy reproducibly.

## Decision

[`patch_agy.py`](../../../../patch_agy.py) rebuilds `~/.local/bin/agy` strictly from a clean versioned backup (`agy.v<ver>.orig`), anchors sites via Go `__lrodata_gopcln` symbols plus invariant instruction sequences, and fails closed against [`site_shapes.json`](../../../../site_shapes.json) and `templates/v<ver>/stock/` byte parity before writing any byte. Runtime artifacts (`runtime/`), upgrade/inspection tools (`tools/`), deployment/gate scripts (`scripts/`), and optional integrations (`integrations/`) stay decoupled behind explicit boundaries.

Note: Implemented in [`patch_agy.py`](../../../../patch_agy.py) (`apply_patch`, `unreviewed_shapes`), [`tools/probe_agy.py`](../../../../tools/probe_agy.py) (`rehearse`), and [`scripts/install.py`](../../../../scripts/install.py).

## Alternatives considered

**Hardcoded per-version offset tables**: Updating raw file offsets for each release is fast initially, but breaks silently whenever upstream recompiles or shifts stack slots. Symbolic resolution plus masked instruction shapes catches shifted targets before patching.

**In-place patching without a clean backup**: Patching the already-modified binary prevents clean uninstallation (`--revert`) and breaks idempotent template override removal when an override is dropped from `prompt_overrides.json`.

**Putting all scripts flat at repository root**: Keeping binary patching, runtime wrappers, prompt capture, and MCP integration in one directory obscures ownership and complicates automated testing and agent deployment.

## Consequences

Every `agy` upgrade requires a matching `templates/v<ver>/` baseline and reviewed instruction shapes in `site_shapes.json`, trading a short `tools/probe_agy.py rehearse` step for deterministic, reversible binary patches and reproducible deployment via `scripts/install.py`.
