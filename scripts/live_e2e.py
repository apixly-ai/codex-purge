#!/usr/bin/env python3
"""Opt-in E2E using authenticated Codex. Makes four small real model calls."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from codex_purge.cli import Manager, make_plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--codex-home", default=os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    parser.add_argument("--codex", default="codex")
    args = parser.parse_args()
    run_id = uuid.uuid4().hex[:12]
    root = ROOT / "artifacts/private" / ("live-" + run_id)
    root.mkdir(parents=True, mode=0o700)
    workspace = root / "workspace"
    workspace.mkdir()
    proof = "file-proof-" + uuid.uuid4().hex
    marker = "profile-" + run_id
    (workspace / "proof.txt").write_text(proof + "\n")
    prompt_file = root / "diagnostic.md"
    prompt_file.write_text("You are a coding assistant performing a harmless configuration diagnostic. "
        "Use the available shell tool to read the requested file. "
        f"For this session's final answer, return exactly {marker}| followed by the file's contents, "
        "on a single line with no other text.\n")
    home = Path(args.codex_home).expanduser().resolve()
    config = home / "config.toml"
    config_before = config.read_bytes() if config.exists() else None
    name = "codex-purge-e2e-" + run_id
    manager = Manager(home, root / "state", name)
    common = [args.codex, "--no-daemon", "--ask-for-approval", "never"]
    tail = ["exec", "--ephemeral", "--skip-git-repo-check", "--json",
            "--cd", str(workspace), "--sandbox", "read-only",
            "Read proof.txt using the available shell tool. Return its exact contents as a single line, without quotes or explanation."]
    rows = []
    started = time.monotonic()
    try:
        for mode in ("baseline", "append", "replace", "restored"):
            if mode in ("append", "replace"):
                options = argparse.Namespace(model=args.model, catalog=None, preset="auto", prompt=str(prompt_file), base=None, mode=mode)
                manager.apply(make_plan(manager, options))
            elif mode == "restored":
                manager.restore()
            if mode in ("append", "replace"):
                command = [sys.executable, str(ROOT / "bin/codex-purge"), "--codex-home", str(home),
                    "--state-dir", str(root / "state"), "--name", name, "--codex", args.codex,
                    "launch", "--model", args.model, "--prompt", str(prompt_file), "--mode", mode,
                    "--", "--no-daemon", "--ask-for-approval", "never", *tail]
            else:
                command = common + ["--model", args.model] + tail
            then = time.monotonic()
            process = subprocess.run(command, cwd=workspace, stdin=subprocess.DEVNULL,
                capture_output=True, text=True, timeout=180,
                env=dict(os.environ, CODEX_HOME=str(home)))
            (root / f"{mode}.stdout.jsonl").write_text(process.stdout)
            (root / f"{mode}.stderr.log").write_text(process.stderr)
            events = []
            for line in process.stdout.splitlines():
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
            messages = [e["item"]["text"] for e in events if e.get("type") == "item.completed"
                        and e.get("item", {}).get("type") == "agent_message"]
            tool_calls = [e for e in events if e.get("type") == "item.completed"
                          and e.get("item", {}).get("type") == "command_execution"]
            final = messages[-1].strip() if messages else ""
            expected = marker + "|" + proof if mode in ("append", "replace") else proof
            row = {"mode": mode, "passed": process.returncode == 0 and final == expected and len(tool_calls) > 0,
                   "exit_code": process.returncode, "terminal_exact_match": final == expected,
                   "shell_tool_calls": len(tool_calls), "elapsed_seconds": round(time.monotonic() - then, 2),
                   "usage": [e.get("usage") for e in events if e.get("type") == "turn.completed"],
                   "final_sha256": hashlib.sha256(final.encode()).hexdigest()}
            rows.append(row)
            print(json.dumps(row), flush=True)
            if not row["passed"]:
                raise RuntimeError(f"{mode} failed. Inspect private artifacts: {root}")
    finally:
        try:
            manager.restore()
        finally:
            config_unchanged = (config.read_bytes() if config.exists() else None) == config_before
            cleanup_ok = not manager.target.exists()
            report = {"schema": 1, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "codex_version": subprocess.check_output([args.codex, "--version"], text=True).strip(),
                "model": args.model, "provider": "configured Codex account authentication and provider",
                "test": "Actual model response + real shell file read + exact final output; four modes",
                "cases": rows, "user_config_unchanged": config_unchanged, "profile_removed": cleanup_ok,
                "elapsed_seconds": round(time.monotonic() - started, 2),
                "all_passed": len(rows) == 4 and all(r["passed"] for r in rows) and config_unchanged and cleanup_ok,
                "scope": "Proves instruction delivery and observable formatting changes, tool continuity and restore. Does not measure server-side safety bypass."}
            write = ROOT / "artifacts" / "live-e2e.json"
            write.write_text(json.dumps(report, indent=2) + "\n")
            (ROOT / "artifacts" / f"live-e2e-attempt-{run_id}.json").write_text(json.dumps(report, indent=2) + "\n")
            print(json.dumps({"report": str(write), "passed": report["all_passed"]}), flush=True)
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
