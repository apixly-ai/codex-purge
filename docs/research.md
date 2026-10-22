# From harness patching to supported Codex profiles

Inspected 2026-10-22. Seven alternative repositories were cloned with full Git
history; the original dsh-purge mirror was already available locally. Exact
revisions and source attribution are recorded in [NOTICE](../NOTICE.md).

## What transfers

DSH Purge's useful engineering patterns are explicit application, compatibility
checks, inspectable status, snapshots and restore. Its JavaScript package paths,
Cordis service injection and renderer patches are specific to DSH and do not
transfer to Codex CLI.

Codex Red-Team Mode demonstrates a working configuration entry point:
`model_instructions_file`. Its larger runtime, MCP broker and rewrite proxy solve
different problems from this initial profile manager. We use a small supported
configuration layer rather than carrying that runtime into every session.

## Decisions

| Area | Reference pattern | Codex Purge decision |
| --- | --- | --- |
| Instruction delivery | Red-Team Mode's file-based instructions | Standalone named config profile; append or explicit replacement |
| Existing config | Ownership-aware installation and uninstall | Own a separate `<name>.config.toml`; leave base config bytes intact |
| Persistence | Purge Community's atomic helper and content hashes | fsync + rename, immutable prompt snapshots, per-profile advisory lock |
| Recovery | Backups before changing host state | Pending transaction journal; recover after target write or stop on conflict |
| Rollback | Restore only managed content | Require matching profile and prompt hashes; preserve later user edits |
| Model selection | Per-model prompt catalogs | User-defined wildcard catalog plus explicit fallback; no invented model-specific efficacy |
| Evaluation | Jailbench's repeatable test battery | Exact harmless nonce + real shell read + baseline / append / replace / restore |
| Host changes | DSH source/runtime patch tables | Supported Codex configuration only; no binary patch tables in v0.1 |

## Evaluation boundaries

Configuration parsing, request instruction delivery, model behavior and
server-side policy are distinct. A configured profile passing a health check
does not establish that a model followed it. Conversely, one harmless formatting
check establishes an observable configuration effect, not a general jailbreak
success rate. Empty replies and failed tool runs never count as passes.

The first live harness invocation used an approval flag in the wrong CLI position;
that invocation failed before inference. A subsequent attempt found that
`--ignore-user-config` suppressed the selected profile. Both were corrected and
the launcher now rejects options that bypass its managed profile. Failed live
attempt receipts remain in `artifacts/` alongside the final result.

## Compatibility

The reference host is Codex CLI 0.159.2 on macOS, Python 3.14.2. The package supports
Python 3.11+ on macOS/Linux. CI tests run on both operating systems. Current CLI
help must advertise standalone `<name>.config.toml` profiles; earlier profile-table
formats are not silently rewritten. Desktop UI integration, Windows writes and
model-specific jailbreak claims are outside v0.1's verified scope.

In append mode, existing user-level `developer_instructions` are composed before
the selected prompt. Named-profile precedence still follows Codex. Project-local
developer-instruction overrides and additional CLI instruction overrides require
care: do not assume a named profile automatically merges every configuration
layer. An explicit `--base` file lets the user choose the composed text.

## Official references

- [Configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference): `developer_instructions`, `model_instructions_file`.
- [Advanced configuration](https://learn.chatgpt.com/docs/config-file/config-advanced): standalone named profiles and precedence.
- [Hooks](https://learn.chatgpt.com/docs/hooks): independent hook loading and review; v0.1 installs no hooks.
