# 参与贡献与支持新版 `agy`

[English](CONTRIBUTING.md) | 中文

`agy-patch` 面向闭源 Go Mach-O 二进制（`darwin/arm64`）。项目可持续性依赖**fail-closed 升级机制**：绝不把旧版本偏移量盲目套用到新版上游二进制上。

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

## 提交 PR 前自检

运行仓库自检门禁与离线单元测试：

```sh
python3 scripts/check_repo.py
python3 -m unittest discover -s tests -v
```

禁止提交真实凭据、`~/.gemini/agy-gateway.env`、`.cache/` 或 `templates/*/stock/PROMPT.md` 中未脱敏的个人技能与规则。
