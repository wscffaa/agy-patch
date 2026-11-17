# `agy-patch`

[English](README.md) | 中文

面向 Google Antigravity CLI（`agy`）的 fail-closed 二进制补丁、缓存中继、Powerline 状态栏与升级预演工具链：macOS/arm64 提供完整补丁集，Windows/amd64 目前为部分验证的实验性移植。

> **设计动机：** 官方每次升级 `agy` 都会替换单个闭源 Go Mach-O 二进制（`~/.local/bin/agy`），直接覆盖本地改动。`agy-patch` 将补丁锚定在 Go `pclntab` 符号与指令形态上，写字节前先做 fail-closed 形态校验，通过隔离沙箱预演（`rehearse`）验证新版本，并把二进制补丁、运行时包装器与系统提示词模板解耦管理。

---

## 核心能力

- **上下文窗口与 Checkpointer 解锁**（`patch_agy.py`）：macOS 补丁在 Gemini 4 Argon / Carbon / Hydrogen 上解锁 `/model` `Tab` 档位（`256K` / `512K` / `900K`）、解除 checkpoint 与 `USER_INPUT` 限制，并修正状态栏分母与 15 秒空闲刷新。Windows 代码包含上下文、checkpoint 和输入限制的候选补丁，目标功能仍需端到端验证。
- **TUI 与 CoT 可读性增强**（macOS/arm64）：保留完整多行 `∴ Thought...` 思考块（`medium` 详略度下实时单行预览，`high` 下流式完整展开）、原生终端 `Faint` + `Italic` 排版、语义 ANSI `"terminal"` 调色板、自适应明暗（DEC 2031）全宽输入栏以及呼吸态 Gemini 星标等待行。
- **系统提示词精简**（`templates/v<ver>/`）：逐字节校验内嵌 `system_prompts/*.tmpl` 槽位，并在 `prompt_overrides.json` 中强制记录每项改动的理由。
- **提示词缓存保活中继**（`runtime/agy-wrapper.sh` / `runtime/agy_wrapper.py` + `runtime/cache_relay.py`）：禁止后台静默自动更新（`AGY_CLI_DISABLE_AUTO_UPDATE=true`），并在交互式与 `acp` 会话空闲期间保活 5 分钟隐式缓存（设置 `AGY_CACHE_RELAY=off` 可关闭）。
- **Pastel Powerline 状态栏**（`runtime/statusline.sh` / `runtime/statusline.py`）：渲染上下文占比、token 统计、单步延迟/TPS、配额及缓存保活状态（`↻`、`↻n`、`✗`）。Windows 版本为无第三方依赖的 Python 实现。
- **Fail-Closed 升级预演**（`tools/probe_agy.py`）：下载并校验 SHA-512、解析位点并修补隔离副本。macOS 还执行请求与 PTY 界面探测；Windows 预演仅验证字节与启动，不证明模型请求、长输入或 TUI 功能正常。
- **可选 ACP MCP Hub**（`integrations/consult_gemini/`，仅 POSIX）：零依赖 MCP stdio 服务 + 单例 Unix Socket Hub。此 Hub 尚未移植到 Windows。

---

## 环境要求与支持版本

- **macOS**：Apple Silicon（`darwin/arm64`），完整补丁集，`agy v1.5.3`–`v1.5.9`
- **Windows**：面向 `agy v1.5.9` 的实验性 `amd64` PE32+ 移植，包含安装器、包装器/状态栏、提示词裁剪与候选长对话补丁；尚未达到 macOS 功能对等。
- **依赖工具**：Python `>= 3.12`；macOS 另需 `jq` 与 Xcode Command Line Tools（`codesign`）；Windows 无需额外工具

---

## 快速部署（适合人类与 Agent 自动部署）

工具链默认约定路径为 `~/.gemini/agy-patch`、`~/.local/bin/agy` 与 `~/.gemini/bin/agy`。

### 1. 克隆并预览计划（`--dry-run`）

```sh
git clone https://github.com/wscffaa/agy-patch.git ~/.gemini/agy-patch
python3 ~/.gemini/agy-patch/scripts/install.py --dry-run
```

### 2. 一键幂等安装

```sh
python3 ~/.gemini/agy-patch/scripts/install.py --set-window 512K
```

`install.py` 会依次完成：
1. 检查操作系统/架构、Python `>= 3.12`、`codesign`、`jq`，以及 `~/.local/bin/agy --version` 是否存在对应的 `templates/v<ver>/`。
2. 备份干净原件至 `~/.local/bin/agy.v<ver>.orig`，对 `~/.local/bin/agy` 打补丁并做 ad-hoc 签名。
3. 同步 [`runtime/agy-wrapper.sh`](runtime/agy-wrapper.sh) 到 `~/.gemini/bin/agy`，同步 [`runtime/statusline.sh`](runtime/statusline.sh) 到 `~/.gemini/antigravity-cli/statusline.sh`。
4. 将 `statusLine` 与 `contextWindow` 安全合并写入 `~/.gemini/antigravity-cli/settings.json`（保留原有配置）。
5. 在 `~/.zshrc` 中幂等写入 `# >>> agy-patch >>>` 管理块（`AGY_CLI_DISABLE_AUTO_UPDATE=true` + `alias agy="$HOME/.gemini/bin/agy"`）；若需手动管理 shell 配置，可加 `--skip-shell`。

### 3. 校验安装结果

新开终端（或执行 `source ~/.zshrc`）后检查：

```sh
type agy
agy --version
python3 ~/.gemini/agy-patch/patch_agy.py --status -v
```

确认 `type agy` 指向 `~/.gemini/bin/agy`，且 `patch_agy.py --status -v` 对 `~/.local/bin/agy` 输出 `patched`、对 `~/.gemini/bin/agy` 输出 `wrapper`。

### 卸载与回滚

```sh
python3 ~/.gemini/agy-patch/scripts/install.py --uninstall
```

该命令会从 `.orig` 备份恢复 `~/.local/bin/agy`，移除安装后的 wrapper、statusline 副本、`settings.json` 中的托管 `statusLine` 配置以及 `~/.zshrc` 管理块。

### Windows（amd64）

Windows 移植面向原生 PE32+ `agy v1.5.9`（`windows/amd64`），包含 Gemini 4 上下文选择、checkpoint 与 `USER_INPUT` 限制的候选补丁，以及提示词裁剪、自动更新保护、缓存中继和 Python 状态栏。位点解析、`--version`、模型列表或 ACP 初始化成功，**不代表被修改的功能路径已经验证**。已登录环境中的 `/model` 选择、真实长输入与 checkpoint 行为仍未验证。

Windows 尚未具备：TUI/CoT 渲染改动、CLI 上下文窗口分母修正、15 秒空闲界面刷新，以及可选 Unix Socket MCP Hub。Python 状态栏使用 agy 提供的遥测，无法修正上游错误的分母。[`site_shapes_windows.json`](site_shapes_windows.json) 的版本字节守卫能拒绝不受支持的版本，但不能证明机器码补丁的语义正确。

```powershell
git clone https://github.com/wscffaa/agy-patch.git $HOME\.gemini\agy-patch
python $HOME\.gemini\agy-patch\scripts\install.py --dry-run
python $HOME\.gemini\agy-patch\scripts\install.py --set-window 512K
```

`install.py` 优先查找 `%LOCALAPPDATA%\agy\bin\agy.exe`（agy 官方 Windows 安装位置），其次 `%USERPROFILE%\.local\bin\agy.exe`；如安装在别处，用 `--binary <path>` 指定。安装会写入 `%USERPROFILE%\.gemini\bin\agy.cmd` + `agy_wrapper.py`、`%USERPROFILE%\.gemini\antigravity-cli\statusline.py`，并在 PowerShell 配置文件中写入托管块（`Documents\PowerShell\Microsoft.PowerShell_profile.ps1`，若只存在 5.1 配置则用后者）。新开 PowerShell 后执行 `agy --version`。

卸载：

```powershell
python $HOME\.gemini\agy-patch\scripts\install.py --uninstall
```

修改已签名 PE 会使 Authenticode 签名失效，能否运行还取决于本机应用控制策略。执行 `--apply`/`--uninstall` 前请关闭正在运行的 `agy.exe`；文件被占用时补丁器会报告替换错误。

---

## 安全升级流程

`AGY_CLI_DISABLE_AUTO_UPDATE=true` 必须保持开启（上游仅识别精确字符串 `true`），防止后台更新静默覆盖已打补丁的二进制。每次升级前先用副本预演：

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

若出现解析失败或未审查的新形态，请先阅读 [`docs/references/context-window-patch.md` §5](docs/references/context-window-patch.md#5-authoring-pitfalls) 与 [`CONTRIBUTING.zh.md`](CONTRIBUTING.zh.md)。

---

## 仓库结构

| 路径 | 职责 |
| :--- | :--- |
| [`patch_agy.py`](patch_agy.py) | 版本自适应补丁器：Mach-O/ARM64 的 TUI + 提示词位点，以及 PE/amd64 的核心 + 提示词位点（`--apply` / `--revert` / `--status` / `--accept-shapes`） |
| [`site_shapes.json`](site_shapes.json) | 经人工审查的 ARM64 原始指令形态库（防止偏移漂移时误改指令） |
| [`site_shapes_windows.json`](site_shapes_windows.json) | Windows v1.5.9 的 PE/amd64 精确原始字节与 `.text` 边界 |
| [`runtime/`](runtime/agy-wrapper.sh) | 运行时包装器（`agy-wrapper.sh`、`agy-wrapper.cmd` + `agy_wrapper.py`）、缓存保活中继（`cache_relay.py`）、状态栏（`statusline.sh` / `statusline.py`）、可选网关模板 |
| [`tools/`](tools/probe_agy.py) | 升级预演（`probe_agy.py`）、更新检查（`check_agy_update.py`）、Mach-O 分析（`inspect_agy.py`）、提示词抓取脱敏（`capture_prompt.py`、`prompt_templates.py`）、PE/amd64 解析（`binfmt.py`、`win_amd64.py`） |
| [`scripts/`](scripts/install.py) | 幂等安装/卸载器（`install.py`）与仓库规范自检门禁（`check_repo.py`） |
| [`templates/`](templates/v1.5.9/README.md) | 按版本归档（`v1.5.3`–`v1.5.9`）的原始模板、`PROMPT.md`/`tools.json`、期望覆盖与 `prompt_overrides.json` |
| [`integrations/`](integrations/consult_gemini_mcp.py) | 可选 `consult_gemini` MCP stdio 服务与 ACP Unix Socket Hub（`consult_gemini/`） |
| [`docs/`](docs/architecture.zh.md) | 架构总览、逆向参考手册（`docs/references/`）与诊断取证记录（`docs/diagnostics/`） |
| [`tests/`](tests/test_repo_invariants.py) | 离线单元测试与仓库不变量测试集（`python3 -m unittest discover -s tests -v`） |

---

## 本地自检与 CI

```sh
python3 ~/.gemini/agy-patch/scripts/check_repo.py
python3 -m unittest discover -s ~/.gemini/agy-patch/tests -v
```

GitHub Actions（`.github/workflows/ci.yml`）会在每次 push / PR 时在 Linux、macOS 与 Windows 上自动执行上述门禁与测试。

普通测试不会下载或运行 Google 二进制。`AGY_WINDOWS_BINARY` 仅启用可选位点解析检查，不是长对话功能测试；测试报告应分别列出通过和跳过数量。

## 许可证

[MIT](LICENSE)
