# 架构

[English](architecture.md) | 中文

修改 `patch_agy.py`、`runtime/`、`tools/`、`scripts/` 或 `integrations/` 下的源码前请先阅读本文。底层逆向细节见 [references/](references/context-window-patch.md)。

## 概览

`agy-patch` 在不破坏干净备份的前提下封装并修补 Google Antigravity CLI：macOS 的 `~/.local/bin/agy` 是闭源 `darwin/arm64` Go Mach-O，Windows 的 `%LOCALAPPDATA%\agy\bin\agy.exe` 是同一程序的 `windows/amd64` PE32+。根目录主入口（[`patch_agy.py`](../patch_agy.py)）基于 `agy.v<ver>.orig` 重建补丁二进制并同步 `runtime/` 运行时脚本，配合隔离升级预演工具链（`tools/`）、幂等安装器（`scripts/install.py`）及可选 ACP MCP Hub（`integrations/consult_gemini/`）协同工作。

## 核心模块

| 模块 | 职责 | 归属文档 |
|---|---|---|
| 二进制补丁器 | 格式分派；Mach-O `pclntab` 符号定位、ARM64 锚点解析、形态校验与 ad-hoc 重签名 | [`patch_agy.py`](../patch_agy.py) |
| PE/amd64 解析器 | PE 段地址转换、Go `pclntab` 定位、精确字节守卫、`.text` 填充区 x86-64 thunk | [`tools/win_amd64.py`](../tools/win_amd64.py)、[`tools/binfmt.py`](../tools/binfmt.py) |
| 形态守卫 | 按补丁位点记录已审查的 ARM64 指令掩码形态与 PE/amd64 精确原始字节 | [`site_shapes.json`](../site_shapes.json)、[`site_shapes_windows.json`](../site_shapes_windows.json) |
| 运行时层 | 自动更新屏蔽、Cloud Code 缓存保活中继、Powerline 状态栏（macOS 用 zsh，Windows 用 Python） | [`runtime/agy-wrapper.sh`](../runtime/agy-wrapper.sh)、[`runtime/agy_wrapper.py`](../runtime/agy_wrapper.py) |
| 升级工具链 | 版本清单拉取、隔离回环/PTY 预演、`pclntab` 与样式表分析、提示词抓包脱敏 | [`tools/probe_agy.py`](../tools/probe_agy.py) |
| 提示词基线 | 按版本归档原始模板、`PROMPT.md` 及带理由的覆盖文件 | [`templates/v1.5.9/README.md`](../templates/v1.5.9/README.md) |
| 安装与门禁 | 幂等安装/卸载、模板/隐私与链接自检 | [`scripts/install.py`](../scripts/install.py) |
| ACP MCP Hub | 可选 stdio MCP 服务与多路复用 `agy acp` 的 Unix Socket Hub | [`integrations/consult_gemini_mcp.py`](../integrations/consult_gemini_mcp.py) |

## 数据流

1. **安装部署（`scripts/install.py`）**：校验 `darwin/arm64`、Python `>= 3.12`、`jq`、`codesign` 与 `templates/v<ver>/`，调用 `patch_agy.py --apply`，向 `~/.gemini/antigravity-cli/settings.json` 非破坏性合并 `statusLine` 与 `contextWindow`，并在 `~/.zshrc` 写入带起止标记的管理块。
2. **二进制修补（`patch_agy.py --apply`）**：首次运行时将 `~/.local/bin/agy` 备份为 `agy.v<ver>.orig`，解析全部 ARM64 位点与 `templates/v<ver>/system_prompts/` 覆盖，对照 `site_shapes.json` 拒绝未审查形态，写入临时文件并执行 `codesign -f -s -`，原子替换 `~/.local/bin/agy` 后同步 `runtime/agy-wrapper.sh` 与 `runtime/statusline.sh`。
3. **交互执行（`~/.gemini/bin/agy`）**：`runtime/agy-wrapper.sh` 导出 `AGY_CLI_DISABLE_AUTO_UPDATE=true`，为交互式与 `acp` 会话拉起 `runtime/cache_relay.py` 并注入 `CLOUD_CODE_URL`，再 `exec` 调用 `~/.local/bin/agy`。
4. **Windows 安装（`scripts/install.py` + `runtime/agy_wrapper.py`）**：校验 `Windows/amd64` 与 Python，从 `agy.exe.v<ver>.orig` 修补 `%LOCALAPPDATA%\agy\bin\agy.exe`，安装 `%USERPROFILE%\.gemini\bin\agy.cmd` + `agy_wrapper.py`，合并 `statusLine`/`contextWindow`，并在 PowerShell 配置中写入托管块。包装器定位 PE，为交互式/`acp` 会话启动中继，并等待 agy 结束以停止中继。
5. **升级预演（`tools/probe_agy.py rehearse`）**：下载并校验 SHA-512，在不删除用户提供的干净备份的前提下暂存副本、解析并应用已支持的位点。macOS 路径还执行回环 `wire` 与 PTY `tui` 探测；Windows 路径只检查字节守卫与启动，跳过行为探测意味着功能验证仍不完整。

## 扩展点

- **二进制补丁位点**：在 [`patch_agy.py`](../patch_agy.py) 中通过不变指令锚点新增域解析器，并用 `--accept-shapes` 记录已审查的原始形态；编写前先阅读 [docs/references/context-window-patch.md §5](references/context-window-patch.md#5-authoring-pitfalls)。Windows/amd64 位点位于 [`tools/win_amd64.py`](../tools/win_amd64.py)，并由 `site_shapes_windows.json` 的精确字节固定。
- **系统提示词覆盖**：按版本号新建 `templates/v<ver>/` 目录，并在 `prompt_overrides.json` 为每处修改提供 `reason`。
- **深度参考与取证**：子系统逆向细节归档于 [references/](references/tui-styles-and-palette.md)，事故调查归档于 [diagnostics/](diagnostics/2026-11-04-400-investigation.md)。

## 持久化格式

- `site_shapes.json`：位点名称到已审查掩码 ARM64 指令序列的 JSON 映射。
- `site_shapes_windows.json`：按版本记录 PE/amd64 `.text` 边界与 Windows 位点精确原始字节。
- `templates/v<ver>/prompt_overrides.json`：记录每个被修改 `system_prompts/*.tmpl` 及其必填 `reason` 的 JSON 清单。
- `~/.gemini/antigravity-cli/settings.json`：上游 CLI 配置文件，由安装器安全合并 `statusLine` 与 `contextWindow`。
