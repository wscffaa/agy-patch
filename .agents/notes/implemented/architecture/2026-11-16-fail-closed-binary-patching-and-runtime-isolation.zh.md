# Agent Note: Fail-Closed Binary Patching and Runtime Isolation

Status: implemented

[English](2026-11-16-fail-closed-binary-patching-and-runtime-isolation.md) | 中文

## Problem

`agy` 以单个闭源 Go Mach-O 二进制（`~/.local/bin/agy`）形式发布，其后台自动更新会静默覆盖本地修改，且内部结构体偏移量会随版本变化。盲目按旧偏移打补丁存在破坏无关指令的风险，而把二进制修补、运行时包装器与升级工具混在同一层会让发布脆弱且难以复现部署。

## Decision

[`patch_agy.py`](../../../../patch_agy.py) 严格从干净的版本化备份（`agy.v<ver>.orig`）重建 `~/.local/bin/agy`，借助 Go `__lrodata_gopcln` 符号与不变指令序列定位位点，并在写字节前对照 [`site_shapes.json`](../../../../site_shapes.json) 与 `templates/v<ver>/stock/` 做逐字节与形态 fail-closed 校验。运行时产物（`runtime/`）、升级与分析工具（`tools/`）、部署与门禁脚本（`scripts/`）以及可选集成（`integrations/`）通过明确边界解耦。

说明：该决策落地于 [`patch_agy.py`](../../../../patch_agy.py)（`apply_patch`、`unreviewed_shapes`）、[`tools/probe_agy.py`](../../../../tools/probe_agy.py)（`rehearse`）与 [`scripts/install.py`](../../../../scripts/install.py)。

## Alternatives considered

**按版本硬编码文件偏移表**：初期更新偏移最快，但上游每次重编译或调整栈槽都会导致静默错位；采用符号解析加掩码指令形态守卫可以在写入前拦截错位。

**不保留干净备份直接原地打补丁**：原地二次修补无法干净卸载（`--revert`），也无法在 `prompt_overrides.json` 删除某条覆盖时自动恢复原模板。

**所有脚本平铺在仓库根目录**：将二进制补丁、运行时包装器、提示词抓包与 MCP 集成混在一起会模糊归属边界，不利于自动化测试与 Agent 部署。

## Consequences

每次升级 `agy` 都必须具备对应的 `templates/v<ver>/` 基线并在 `site_shapes.json` 中完成形态审查；用一次短暂的 `tools/probe_agy.py rehearse` 预演换取确定、可回滚的二进制修补和基于 `scripts/install.py` 的可复现部署。
