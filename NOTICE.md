# Sources and implementation lineage

Codex Purge is an independent Apixly project. It is not affiliated with or endorsed
by OpenAI or DeepSeek. Codex and DeepSeek Harness are their respective products.

We studied these projects before implementing this tool. The source and prompt
files in this repository were written for Codex Purge; no upstream jailbreak
prompt collection or vendor runtime is bundled.

| Source | What informed this implementation | Inspected revision | License at inspection |
| --- | --- | --- | --- |
| [chAng-L19/codex-redteam-mode](https://github.com/chAng-L19/codex-redteam-mode) | Explicit instruction-file delivery, model profiles, ownership-aware uninstall | `cd8db548fd37` | MIT |
| [kingcharleslzy-ai/dsh-purge](https://github.com/kingcharleslzy-ai/dsh-purge) | Atomic writes, content-addressed snapshots, maintenance locking, self-check separation | `4ddd4a728d26` | MIT; original copyright 2026 小杨 |
| [luowang-ui/dsh-purge-plus](https://github.com/luowang-ui/dsh-purge-plus) | Host compatibility boundaries and restore behavior | `111ebe489308` | MIT |
| [mortyandtimo/dsh-purge-plus](https://github.com/mortyandtimo/dsh-purge-plus) | Idempotent patch anchors and host version drift | `35c6bf3a12b3` | MIT |
| [YuJunZhiXue/dsh-purge](https://github.com/mmparko/dsh-purge) | Original Purge concept; author 小杨 / YuJunZhiXue, available through a mirror | `033e6bd` | MIT |
| [xsser/codex-jailbreak-guide](https://github.com/xsser/codex-jailbreak-guide) | Configuration-entry research only | `16e4faccb5cf` | No license file found; no content copied |
| [elder-plinius/L1B3RT4S](https://github.com/elder-plinius/L1B3RT4S) | Prompt-library comparison only | `64960b783249` | AGPL-3.0; no content copied |
| [hermes-labs-ai/hermes-jailbench](https://github.com/hermes-labs-ai/hermes-jailbench) | Reproducible evaluation and explicit scorer limitations | `4af699364b22` | Apache-2.0 on inspected main; no content copied |

Implementation choices and deviations are documented in [the research notes](docs/research.md).
