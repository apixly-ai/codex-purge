<p align="center"><img src="docs/banner.svg" alt="Codex Purge" width="100%"></p>

<p align="center"><b>看得清、能切换、可验证、可回滚的 Codex 指令管理工具。</b></p>
<p align="center"><a href="README.md">English</a> · <a href="docs/research.md">实现研究</a> · <a href="NOTICE.md">来源署名</a></p>

> **实验预览。** 当前已验证配置管理和回滚，尚未验证真实任务中的拒答改善或服务端破限效果；发布版本已标记为预发布。

Codex Purge 通过 Codex 官方配置入口管理提示词和模型配置。第一版是 CLI，
把独立命名配置、预览、自检、备份、冲突保护和回滚做好。

```bash
git clone https://github.com/apixly-ai/codex-purge.git
cd codex-purge
./bin/codex-purge doctor
./bin/codex-purge preview --preset engineering
./bin/codex-purge launch --preset engineering
```

需要 Python 3.11+、支持独立命名配置文件的 Codex CLI，以及 macOS 或 Linux。
运行时零第三方 Python 依赖。

| 命令 | 用途 |
| --- | --- |
| `preview` | 只读查看提示词来源、模式、模型和 SHA256；加 `--show-prompt` 查看全文 |
| `apply` | 写入独立的 `codex-purge.config.toml`，随后通过 `codex --profile codex-purge` 使用 |
| `launch` | 应用后启动 Codex，`--` 后可以透传 Codex 参数 |
| `status` | 检查当前版本、文件哈希与人工修改 |
| `rollback` | 退回上一份受管版本 |
| `restore` | 移除当前受管配置并保留历史快照 |
| `doctor` | 检查本地 Codex 版本与配置格式支持情况 |

默认 `append` 保留 Codex 内置指令，并把用户配置中的 developer 指令与新提示词组合。
`--mode replace` 明确使用 `model_instructions_file` 替换内置指令；
`--base FILE` 可以选择需要先组合的基础文本。使用自己的提示词：

```bash
./bin/codex-purge launch --prompt ./my-instructions.md --model YOUR_MODEL
```

工具管理单独的命名配置，不重写基础 `config.toml`、凭证、供应商、权限、Hook 或已有 Skill。
如果受管文件被人改过，会停止覆盖或回滚，并报告冲突。写入具备文件锁、原子替换和中断恢复。
项目层已有 developer 指令时，应明确使用 `--base` 选择组合内容；不要假设所有层自动合并。

源码运行的状态默认保存在项目 `.state/`；可用 `CODEX_PURGE_STATE` 指向外置固态。
安装后的默认状态位置为 `$XDG_STATE_HOME/codex-purge`（通常是 `~/.local/state/codex-purge`）。
全局选项 `--codex-home`、`--state-dir`、`--name` 放在子命令之前。

验证包含单元测试，以及真实 Codex 的基线、追加、替换、恢复四组 E2E：
真实工具读取随机文件，最终文本逐字匹配，同时检查基础配置没有变化、临时配置已经清理。
[公开结果](artifacts/live-e2e.json)只包含脱敏信息；原始日志保存在 Git 忽略的私有目录。
这个结果能证明指令确实生效、工具还能使用、恢复有效，不能当成服务端限制已经解除的证据。

另做了 [16 次真实边界回归](docs/boundary-evaluation.md)：四种模式下，正常安全知识问题均能回答，
两种非操作性的有害鼓励请求均被拒绝或安全引导。**本轮没有观察到安全边界被改变，不能宣称破除服务端限制。**
具体限制由哪一层执行，单凭当前 CLI 终态输出仍无法归因。

随后也测试了 [第三方原版提示词和 CLI 组合](docs/third-party-comparison.md)：
当前 GPT‑6.1 上未观察到优于基线的效果；匹配 GPT‑5.6 的补测因持续 429 中断，不能下有效或无效的结论。

[DSH Purge 方案移植实测](docs/dsh-ported-comparison.md)采用作者原始默认内容和组装函数：
原版正常组装仍安全引导暴力用例，凭证用例返回网络安全风险／访问拦截；其余真实模型变体在该拦截后未继续运行。

参考项目与署名见 [NOTICE](NOTICE.md)。由 [Apixly](https://github.com/apixly-ai) 独立维护。
