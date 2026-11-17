# `agy-patch`

[English](README.md) | 中文

面向 Google Antigravity CLI（`agy`）的 fail-closed 版本自适应二进制补丁、系统提示词精简、提示词缓存保活中继、Powerline 状态栏与升级预演工具链，支持 **macOS（`darwin/arm64`）** 与 **Windows（`windows/amd64`）** 双平台。

> **设计动机：** 官方每次升级 `agy` 都会替换单个闭源 Go 二进制（macOS 为 `~/.local/bin/agy`，Windows 为 `%LOCALAPPDATA%\agy\bin\agy.exe`），直接覆盖本地改动。`agy-patch` 将补丁锚定在 Go `pclntab` 符号与指令形态上，写字节前先做 fail-closed 形态校验，通过隔离沙箱预演（`rehearse`）验证新版本，并把二进制补丁、运行时包装器与系统提示词模板解耦管理。

---

## 核心能力与平台支持矩阵

| 能力模块 | macOS（`darwin/arm64`） | Windows（`windows/amd64`） |
| :--- | :--- | :--- |
| **支持 `agy` 版本** | `v1.5.3`–`v1.5.9` | `v1.5.9` |
| **依赖环境** | Python `>= 3.12`、`jq`、Xcode CLT（`codesign`） | Python `>= 3.12`（无需额外工具） |
| **上下文窗口与 Checkpointer 解锁**（`256K` / `512K` / `900K`、>256K checkpoint、64K `USER_INPUT`） | 已验证 | 已包含并由精确字节守卫固定（`site_shapes_windows.json`）；已登录 `/model` 与长对话实测待补充 |
| **系统提示词精简**（`templates/v<ver>/`） | 支持（逐字节校验 + `prompt_overrides.json`） | 支持（含 LF/CRLF 行尾规范化） |
| **提示词缓存保活中继**（`cache_relay.py`） | 支持（`agy-wrapper.sh`，覆盖交互式与 `acp`） | 支持（`agy.cmd` + `agy_wrapper.py`，覆盖交互式与 `acp`） |
| **Pastel Powerline 状态栏** | 支持（`runtime/statusline.sh`，`jq`） | 支持（`runtime/statusline.py`，无第三方依赖 Python） |
| **TUI 与 CoT 可读性 / 分母修正 / 15 秒空闲刷新** | 支持（`∴ Thought...`、Faint+Italic、ANSI 调色板、DEC 2031 输入栏、呼吸星标） | 暂未移植（状态栏展示上游原始遥测数据） |
| **Fail-Closed 升级预演**（`tools/probe_agy.py`） | 支持（SHA-512 + 形态守卫 + 回环请求与 PTY TUI 探测） | 支持（SHA-512 + 精确字节守卫 + 启动冒烟检查） |
| **可选 ACP MCP Hub**（`integrations/consult_gemini/`） | 支持（Unix Socket Hub + SQLite 遥测） | 暂未移植（仅 POSIX） |

---

## 快速部署（macOS 与 Windows）

双平台共用同一个幂等安装器（`scripts/install.py`）、`--set-window` 参数（`Default` / `256K` / `512K` / `900K`）与 `--uninstall` 回滚流程。

### macOS（Apple Silicon / `darwin/arm64`）

工具链默认约定路径为 `~/.gemini/agy-patch`、`~/.local/bin/agy` 与 `~/.gemini/bin/agy`。

1. **克隆并预览计划（`--dry-run`）**

   ```sh
   git clone https://github.com/wscffaa/agy-patch.git ~/.gemini/agy-patch
   python3 ~/.gemini/agy-patch/scripts/install.py --dry-run
   ```

2. **一键幂等安装**

   ```sh
   python3 ~/.gemini/agy-patch/scripts/install.py --set-window 512K
   ```

   `install.py` 会依次完成：
   - 检查 `darwin/arm64`、Python `>= 3.12`、`codesign`、`jq`，以及 `~/.local/bin/agy --version` 是否存在对应的 `templates/v<ver>/`。
   - 备份干净原件至 `~/.local/bin/agy.v<ver>.orig`，对 `~/.local/bin/agy` 打补丁并做 ad-hoc 签名。
   - 同步 [`runtime/agy-wrapper.sh`](runtime/agy-wrapper.sh) 到 `~/.gemini/bin/agy`，同步 [`runtime/statusline.sh`](runtime/statusline.sh) 到 `~/.gemini/antigravity-cli/statusline.sh`。
   - 将 `statusLine` 与 `contextWindow` 安全合并写入 `~/.gemini/antigravity-cli/settings.json`（保留原有配置）。
   - 在 `~/.zshrc` 中幂等写入 `# >>> agy-patch >>>` 管理块（`AGY_CLI_DISABLE_AUTO_UPDATE=true` + `alias agy="$HOME/.gemini/bin/agy"`）；若需手动管理 shell 配置，可加 `--skip-shell`。

3. **校验安装结果**

   新开终端（或执行 `source ~/.zshrc`）后检查：

   ```sh
   type agy
   agy --version
   python3 ~/.gemini/agy-patch/patch_agy.py --status -v
   ```

   确认 `type agy` 指向 `~/.gemini/bin/agy`，且 `patch_agy.py --status -v` 对 `~/.local/bin/agy` 输出 `patched`、对 `~/.gemini/bin/agy` 输出 `wrapper`。

4. **卸载与回滚**

   ```sh
   python3 ~/.gemini/agy-patch/scripts/install.py --uninstall
   ```

   从 `.orig` 备份恢复 `~/.local/bin/agy`，移除安装后的 wrapper、statusline 副本、`settings.json` 中的托管 `statusLine` 配置以及 `~/.zshrc` 管理块。

---

### Windows（`amd64`）

工具链默认约定路径为 `$HOME\.gemini\agy-patch`、`%LOCALAPPDATA%\agy\bin\agy.exe`（若未找到则回退 `%USERPROFILE%\.local\bin\agy.exe`，也可通过 `--binary <path>` 指定），以及 `%USERPROFILE%\.gemini\bin\agy.cmd`。

> **Windows 操作前注意：** 执行 `--apply` 或 `--uninstall` 前请先关闭正在运行的 `agy.exe`，以免文件被占用导致替换失败。修改已签名的 PE 会使 Authenticode 签名失效，能否执行仍取决于本机应用控制策略。

1. **克隆并预览计划（`--dry-run`）**

   ```powershell
   git clone https://github.com/wscffaa/agy-patch.git $HOME\.gemini\agy-patch
   python $HOME\.gemini\agy-patch\scripts\install.py --dry-run
   ```

2. **一键幂等安装**

   ```powershell
   python $HOME\.gemini\agy-patch\scripts\install.py --set-window 512K
   ```

   `install.py` 会依次完成：
   - 检查 `Windows/amd64`、Python `>= 3.12`，以及 `agy.exe --version` 是否匹配已支持版本（`v1.5.9`）。
   - 备份干净原件至 `agy.exe.v<ver>.orig`，写入经精确字节校验的 PE/amd64 补丁与 `system_prompts/*.tmpl` 覆盖。
   - 在 `%USERPROFILE%\.gemini\bin\` 下安装生成的 [`runtime/agy-wrapper.cmd`](runtime/agy-wrapper.cmd)、[`runtime/agy_wrapper.py`](runtime/agy_wrapper.py) 与 [`runtime/cache_relay.py`](runtime/cache_relay.py)，并将 [`runtime/statusline.py`](runtime/statusline.py) 安装到 `%USERPROFILE%\.gemini\antigravity-cli\statusline.py`。
   - 将 `statusLine` 与 `contextWindow` 安全合并写入 `%USERPROFILE%\.gemini\antigravity-cli\settings.json`。
   - 向已安装的 PowerShell 配置文件（`Documents\WindowsPowerShell\Microsoft.PowerShell_profile.ps1` 与/或 `Documents\PowerShell\Microsoft.PowerShell_profile.ps1`）幂等写入 `# >>> agy-patch >>>` 管理块（设置 `AGY_CLI_DISABLE_AUTO_UPDATE=true` 并将 `%USERPROFILE%\.gemini\bin` 加入 `PATH`）；若需手动管理，可加 `--skip-shell`。

3. **校验安装结果**

   新开 PowerShell 窗口后检查：

   ```powershell
   Get-Command agy
   agy --version
   python $HOME\.gemini\agy-patch\patch_agy.py --status -v
   ```

4. **卸载与回滚**

   ```powershell
   python $HOME\.gemini\agy-patch\scripts\install.py --uninstall
   ```

   从 `.orig` 备份恢复 `agy.exe`，移除安装后的 wrapper/relay/statusline 副本、`settings.json` 中的托管 `statusLine` 配置以及 PowerShell 配置文件中的 `# >>> agy-patch >>>` 管理块。

---

## 安全升级流程

`AGY_CLI_DISABLE_AUTO_UPDATE=true` 必须保持开启（上游仅识别精确字符串 `true`），防止后台更新静默覆盖已打补丁的二进制。每次升级前先用隔离副本预演：

**macOS（`sh`）：**

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

**Windows（`PowerShell`）：**

```powershell
# 1. Check whether a newer upstream release exists (read-only)
python -I $HOME\.gemini\agy-patch\tools\check_agy_update.py

# 2. Download, verify SHA-512, check Windows exact-byte guards, and run startup smoke check
python $HOME\.gemini\agy-patch\tools\probe_agy.py rehearse

# 3. Once rehearse reports ok (close running agy.exe before --apply):
Remove-Item Env:AGY_CLI_DISABLE_AUTO_UPDATE -ErrorAction SilentlyContinue
& "$env:LOCALAPPDATA\agy\bin\agy.exe" update
python $HOME\.gemini\agy-patch\patch_agy.py --apply
python $HOME\.gemini\agy-patch\patch_agy.py --status -v
```

若出现解析失败或未审查的新形态，请先阅读 [`docs/references/context-window-patch.md` §5](docs/references/context-window-patch.md#5-authoring-pitfalls) 与 [`CONTRIBUTING.zh.md`](CONTRIBUTING.zh.md)。

---

## 仓库结构

| 路径 | 职责 |
| :--- | :--- |
| [`patch_agy.py`](patch_agy.py) | 核心版本自适应补丁器：Mach-O/ARM64（TUI + 提示词位点）与 PE/amd64（核心 + 提示词位点）（`--apply` / `--revert` / `--status` / `--accept-shapes`） |
| [`site_shapes.json`](site_shapes.json) | 经人工审查的 macOS ARM64 原始指令形态库（防止偏移漂移时误改指令） |
| [`site_shapes_windows.json`](site_shapes_windows.json) | 经审查的 Windows PE/amd64 精确原始字节与 `.text` 边界 |
| [`runtime/`](runtime/agy-wrapper.sh) | 运行时包装器（`agy-wrapper.sh`、`agy-wrapper.cmd` + `agy_wrapper.py`）、缓存保活中继（`cache_relay.py`）、状态栏（`statusline.sh` / `statusline.py`）、可选网关模板 |
| [`tools/`](tools/probe_agy.py) | 升级预演（`probe_agy.py`）、更新检查（`check_agy_update.py`）、Mach-O 分析（`inspect_agy.py`）、提示词抓取脱敏（`capture_prompt.py`、`prompt_templates.py`）、PE/amd64 解析（`binfmt.py`、`win_amd64.py`） |
| [`scripts/`](scripts/install.py) | 跨平台幂等安装/卸载器（`install.py`）与仓库规范自检门禁（`check_repo.py`） |
| [`templates/`](templates/v1.5.9/README.md) | 按版本归档（`v1.5.3`–`v1.5.9`）的原始模板、`PROMPT.md`/`tools.json`、期望覆盖与 `prompt_overrides.json` |
| [`integrations/`](integrations/consult_gemini_mcp.py) | 可选（仅 POSIX）`consult_gemini` MCP stdio 服务与 ACP Unix Socket Hub |
| [`docs/`](docs/architecture.zh.md) | 架构总览、逆向参考手册（`docs/references/`）与诊断取证记录（`docs/diagnostics/`） |
| [`tests/`](tests/test_repo_invariants.py) | 离线单元测试与仓库不变量测试集（`python -m unittest discover -s tests -v`） |

---

## 本地自检与 CI

```sh
# macOS / Linux
python3 ~/.gemini/agy-patch/scripts/check_repo.py
python3 -m unittest discover -s ~/.gemini/agy-patch/tests -v
```

```powershell
# Windows (PowerShell)
python $HOME\.gemini\agy-patch\scripts\check_repo.py
python -m unittest discover -s $HOME\.gemini\agy-patch\tests -v
```

GitHub Actions（`.github/workflows/ci.yml`）会在每次 push / PR 时在 Linux（`ubuntu-latest`）、macOS（`macos-latest`）与 Windows（`windows-latest`）上自动执行上述门禁与测试。

普通测试不会下载或运行 Google 二进制。`AGY_WINDOWS_BINARY` 仅启用本地可选位点解析检查；测试报告应分别列出通过和跳过数量。

## 许可证

[MIT](LICENSE)
