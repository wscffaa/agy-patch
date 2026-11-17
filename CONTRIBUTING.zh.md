# 参与贡献与支持新版 `agy`

[English](CONTRIBUTING.md) | 中文

`agy-patch` 面向闭源 Go 二进制：macOS 为 Mach-O/arm64，Windows 为 PE32+/amd64。项目可持续性依赖**fail-closed 升级机制**：绝不把旧版本偏移量盲目套用到新版上游二进制上。

## 升级到新版 `agy`

1. **只读检查上游是否有新版本（不改动 `~/.local/bin/agy`）：**
   ```sh
   python3 -I tools/check_agy_update.py
   ```
2. **先在隔离副本上完整预演：**
   ```sh
   python3 tools/probe_agy.py rehearse
   ```
   `rehearse` 会在临时目录下载新版并校验 SHA-512，生成或脚手架化 `templates/v<new>/`，解析全部分组位点，按 `site_shapes.json` 核对原始指令形态，给临时副本打补丁并探测线缆请求与 TUI 界面。
3. **处理所有 `REVIEW` / `READ` / `FAIL` 项：**
   - 若某位点的原始指令形态发生变化，先比对前后差异：
     ```sh
     python3 tools/probe_agy.py sites ~/.local/bin/agy.v<old>.orig <tmp>/agy.v<new>.orig
     ```
     在改动任何解析器或执行 `--accept-shapes` 记录形态前，请先阅读 [`docs/references/context-window-patch.md` §5](./docs/references/context-window-patch.md#5-authoring-pitfalls)。
   - 若内嵌模板有变化，对比 `templates/v<old>/stock` 与 `templates/v<new>/stock`，更新 `templates/v<new>/system_prompts/` 与 `prompt_overrides.json`，并补写 `templates/v<new>/README.md`。
4. **仅在 `rehearse` 全部通过后再升级本机二进制：**
   ```sh
   env -u AGY_CLI_DISABLE_AUTO_UPDATE agy update
   python3 patch_agy.py --apply
   python3 patch_agy.py --status -v
   ```

## Windows（amd64）版本

Windows 补丁固定于 `agy v1.5.9`，精确原始字节记录在 `site_shapes_windows.json`。升级新版本时：

1. 从 updater manifest 下载 `cli_windows_x64.exe` 并校验 SHA-512。
2. 执行 `python patch_agy.py --status --binary <new.exe> -v`；`.text` 大小或任一位点原始字节不匹配都会 fail-closed。
3. 审查函数体、跳转目标、寄存器/栈约定与补丁指令语义后，再更新 `tools/win_amd64.py` 或 `site_shapes_windows.json` 中唯一权威的原始字节。短指令前缀匹配不能证明功能正确。
4. 在隔离副本上打补丁。`--version`、`models` 和 ACP `initialize` 仅是启动/协议冒烟检查。推荐安装前，还需分别验证 `/model` + Tab、实际请求中的 checkpoint 限制、超过 64K 输入的保留与空闲缓存重放。Windows 预演跳过 wire/screens 时必须报告功能验证不完整。
5. Windows 尚未移植 TUI/CoT、上下文分母修正、15 秒空闲界面刷新和可选 Unix Socket MCP Hub。必要行为有证据前应保留实验性标记，不可从单元测试通过推断功能对等。

## 提交 PR 前自检

运行仓库自检门禁与离线单元测试：

```sh
python3 scripts/check_repo.py
python3 -m unittest discover -s tests -v
```

禁止提交真实凭据、`~/.gemini/agy-gateway.env`、`.cache/` 或 `templates/*/stock/PROMPT.md` 中未脱敏的个人技能与规则。
