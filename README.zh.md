# `agy-patch`

[English](README.md) | 中文

面向 Google Antigravity CLI（`agy`，`darwin/arm64`）的版本自适应二进制补丁、提示词缓存保活包装器、Powerline 状态栏与升级预演工具链。

> **设计动机：** 官方每次升级 `agy` 都会替换单个闭源 Go Mach-O 二进制（`~/.local/bin/agy`），直接覆盖本地改动。`agy-patch` 将补丁锚定在 Go `pclntab` 符号与指令形态上，写字节前先做 fail-closed 形态校验，通过隔离沙箱预演（`rehearse`）验证新版本，并把二进制补丁、运行时包装器与系统提示词模板解耦管理。

---

## 核心能力

- **上下文窗口与 Checkpointer 解锁**（`patch_agy.py`）：在 Gemini 4 Argon / Carbon / Hydrogen 上解锁 `/model` `Tab` 上下文档位（`256K` / `512K` / `900K`），解除 >256K checkpoint 上限与 64K `USER_INPUT` 步级截断，修正状态栏 token 分母与 15 秒空闲刷新。
- **TUI 与 CoT 可读性增强**：保留完整多行 `∴ Thought...` 思考块（`medium` 详略度下实时单行预览，`high` 下流式完整展开）、原生终端 `Faint` + `Italic` 排版、语义 ANSI `"terminal"` 调色板、自适应明暗（DEC 2031）全宽输入栏以及呼吸态 Gemini 星标等待行。
- **系统提示词精简**（`templates/v<ver>/`）：逐字节校验内嵌 `system_prompts/*.tmpl` 槽位，并在 `prompt_overrides.json` 中强制记录每项改动的理由。
- **提示词缓存保活中继**（`runtime/agy-wrapper.sh` + `runtime/cache_relay.py`）：禁止后台静默自动更新（`AGY_CLI_DISABLE_AUTO_UPDATE=true`），并在交互式与 `acp` 会话空闲期间保活 5 分钟隐式缓存（设置 `AGY_CACHE_RELAY=off` 可关闭）。
- **Pastel Powerline 状态栏**（`runtime/statusline.sh`）：单次 `jq` 解析渲染上下文占比、token 统计、单步延迟/TPS、配额及缓存保活状态（`↻`、`↻n`、`✗`）。
- **Fail-Closed 升级预演**（`tools/probe_agy.py`）：在临时目录下载并校验新版本 SHA-512，解析全部分组位点、核对指令形态（`site_shapes.json`），并在回环端点 + PTY 下验证线缆请求与 TUI 界面，确认无误后再动线上二进制。
- **可选 ACP MCP Hub**（`integrations/consult_gemini/`）：零依赖 MCP stdio 服务 + 单例 Unix Socket Hub，使 Claude Code 等外部客户端可通过常驻 `agy acp` 发起只读 `consult_gemini` 咨询并读取精确 SQLite 用量遥测。

---

## 环境要求与支持版本

- **系统架构**：macOS Apple Silicon（`darwin/arm64`）
- **依赖工具**：Python `>= 3.12`、`jq`、Xcode Command Line Tools（`codesign`）
- **已验证 `agy` 版本**：`v1.5.3`、`v1.5.5`、`v1.5.6`、`v1.5.7`、`v1.5.8`、`v1.5.9`

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
| [`patch_agy.py`](patch_agy.py) | 核心版本自适应 ARM64 二进制与提示词补丁器（`--apply` / `--revert` / `--status` / `--accept-shapes`） |
| [`site_shapes.json`](site_shapes.json) | 经人工审查的原始指令形态库（防止偏移漂移时误改指令） |
| [`runtime/`](runtime/agy-wrapper.sh) | 运行时包装器（`agy-wrapper.sh`）、缓存保活中继（`cache_relay.py`）、状态栏（`statusline.sh`）、可选网关模板 |
| [`tools/`](tools/probe_agy.py) | 升级预演（`probe_agy.py`）、更新检查（`check_agy_update.py`）、Mach-O 分析（`inspect_agy.py`）、提示词抓取脱敏（`capture_prompt.py`、`prompt_templates.py`） |
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

GitHub Actions（`.github/workflows/ci.yml`）会在每次 push / PR 时在 Linux 与 macOS 上自动执行上述门禁与测试。

## 许可证

[MIT](LICENSE)
