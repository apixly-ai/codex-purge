"""Codex named-profile management. Python stdlib only; macOS and Linux."""
from __future__ import annotations

import argparse
import contextlib
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import uuid

from . import __version__


class Conflict(Exception):
    """An unmanaged file or a user's subsequent edit must be preserved."""


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest(path: Path) -> str | None:
    if path.is_symlink():
        raise Conflict(f"Refusing managed symlink: {path}")
    return sha(path.read_bytes()) if path.exists() else None


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise Conflict(f"Refusing managed symlink: {path}")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        # Persist the directory entry as well as the file contents.
        if hasattr(os, "O_DIRECTORY"):
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_json(path: Path, value: dict) -> None:
    atomic_write(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())


def read_toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def quote(value: str) -> str:
    # JSON basic strings are valid TOML for our UTF-8 text values.
    return json.dumps(value, ensure_ascii=False)


class Manager:
    def __init__(self, home: Path, state_root: Path, name: str = "codex-purge"):
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", name):
            raise ValueError("Profile name must be 1-64 lowercase letters, digits, '_' or '-'.")
        self.home = home.expanduser().resolve()
        self.name = name
        identity = sha(str(self.home).encode())[:20]
        self.root = state_root.expanduser().resolve() / identity / name
        self.target = self.home / f"{name}.config.toml"
        self.manifest = self.root / "state.json"
        self.pending = self.root / "pending.json"

    def empty(self) -> dict:
        return {"schema": 1, "home": str(self.home), "name": self.name,
                "history": [], "active": None}

    def state(self) -> dict:
        state = json.loads(self.manifest.read_text()) if self.manifest.exists() else self.empty()
        if state.get("schema") != 1 or state.get("home") != str(self.home) or state.get("name") != self.name:
            raise Conflict("State identity or schema does not match this installation.")
        return state

    @contextlib.contextmanager
    def locked(self):
        if os.name != "posix":
            raise ValueError("v0.1 supports macOS and Linux; Windows is not validated.")
        import fcntl
        self.root.mkdir(parents=True, exist_ok=True)
        lock = self.root / "lock"
        if lock.is_symlink():
            raise Conflict("Refusing lock symlink.")
        with lock.open("a+b") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            self.recover()
            yield

    def recover(self):
        if not self.pending.exists():
            return
        transaction = json.loads(self.pending.read_text())
        current = digest(self.target)
        if current == transaction["after_sha"]:
            write_json(self.manifest, transaction["state"])
        elif current != transaction["before_sha"]:
            raise Conflict("Interrupted transaction conflicts with a subsequent edit; preserve pending.json for review.")
        self.pending.unlink()

    def transact(self, before: str | None, config: str | None, state: dict):
        if digest(self.target) != before:
            raise Conflict("Profile changed during operation; no overwrite performed.")
        after = sha(config.encode()) if config is not None else None
        write_json(self.pending, {"before_sha": before, "after_sha": after, "state": state})
        if digest(self.target) != before:
            raise Conflict("Profile changed after transaction preparation.")
        if config is None:
            self.target.unlink()
        else:
            atomic_write(self.target, config.encode())
        write_json(self.manifest, state)
        self.pending.unlink()

    def assert_owned(self, state: dict):
        active = state["active"]
        current = digest(self.target)
        expected = active["config_sha256"] if active else None
        if current != expected:
            raise Conflict("Managed profile drift or unmanaged name collision. Your file was preserved.")
        if active:
            prompt = Path(active["prompt_path"])
            if digest(prompt) != active["prompt_sha256"]:
                raise Conflict("Managed prompt drift. Your file was preserved.")

    def apply(self, plan: dict) -> dict:
        with self.locked():
            state = self.state()
            self.assert_owned(state)
            active = state["active"]
            if active and active["config_sha256"] == plan["config_sha256"]:
                return {"ok": True, "changed": False, "version": active["id"], "profile_path": str(self.target)}
            prompt_path = Path(plan["prompt_path"])
            if prompt_path.exists() and digest(prompt_path) != plan["prompt_sha256"]:
                raise Conflict("Content-addressed prompt has been modified.")
            if not prompt_path.exists():
                atomic_write(prompt_path, plan["prompt"].encode())
            entry = {k: v for k, v in plan.items() if k not in ("prompt", "base_sources")}
            entry.update(id=uuid.uuid4().hex, parent_id=active["id"] if active else None,
                         created_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
            state["history"].append(entry)
            state["active"] = entry
            self.transact(active["config_sha256"] if active else None, plan["config"], state)
            return {"ok": True, "changed": True, "version": entry["id"], "profile_path": str(self.target),
                    "activate": ["codex", "--profile", self.name]}

    def rollback(self) -> dict:
        with self.locked():
            state = self.state()
            self.assert_owned(state)
            active = state["active"]
            if not active:
                return {"ok": True, "changed": False}
            previous = next((entry for entry in state["history"] if entry["id"] == active["parent_id"]), None)
            if previous and digest(Path(previous["prompt_path"])) != previous["prompt_sha256"]:
                raise Conflict("Previous prompt snapshot has drifted.")
            state["active"] = previous
            self.transact(active["config_sha256"], previous["config"] if previous else None, state)
            return {"ok": True, "changed": True, "version": previous["id"] if previous else None,
                    "active": bool(previous)}

    def restore(self) -> dict:
        with self.locked():
            state = self.state()
            self.assert_owned(state)
            active = state["active"]
            if not active:
                return {"ok": True, "changed": False}
            state["active"] = None
            self.transact(active["config_sha256"], None, state)
            return {"ok": True, "changed": True, "active": False, "snapshots_retained": True}

    def status(self) -> dict:
        state = self.state()
        try:
            self.assert_owned(state)
            clean, error = True, None
        except Conflict as exc:
            clean, error = False, str(exc)
        return {"ok": clean and not self.pending.exists(), "active": bool(state["active"]),
                "profile_path": str(self.target), "state_dir": str(self.root),
                "pending_transaction": self.pending.exists(), "versions": len(state["history"]),
                "current": {k: v for k, v in (state["active"] or {}).items() if k != "config"},
                "error": error}


def make_plan(manager: Manager, args) -> dict:
    base_config = read_toml(manager.home / "config.toml")
    model = args.model or base_config.get("model")
    if model is not None and (not isinstance(model, str) or not model.strip()):
        raise ValueError("model must be a non-empty string.")
    catalog_path = Path(args.catalog).expanduser().resolve() if args.catalog else Path(__file__).parent / "presets/catalog.json"
    catalog = json.loads(catalog_path.read_text())
    preset = args.preset
    if preset == "auto":
        preset = next((r["preset"] for r in catalog.get("rules", [])
                       if model and fnmatch.fnmatchcase(model, r["pattern"])), catalog["default"])
    if args.prompt:
        source = Path(args.prompt).expanduser().resolve()
        selected = "custom"
    else:
        if preset not in catalog["presets"]:
            raise ValueError(f"Unknown preset: {preset}")
        source = (catalog_path.parent / catalog["presets"][preset]["file"]).resolve()
        selected = preset
    text = source.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError("The instruction file must not be empty.")
    base_sources = []
    base = ""
    if args.base:
        base_path = Path(args.base).expanduser().resolve()
        base, base_sources = base_path.read_text().strip(), [str(base_path)]
    elif args.mode == "append":
        base = base_config.get("developer_instructions", "")
        if not isinstance(base, str):
            raise ValueError("developer_instructions must be a string.")
        if base:
            base_sources = [str(manager.home / "config.toml") + ":developer_instructions"]
    prompt = (base + "\n\n" if base else "") + text + "\n"
    checksum = sha(prompt.encode())
    prompt_path = manager.root / "prompts" / f"{checksum}.md"
    key = "developer_instructions" if args.mode == "append" else "model_instructions_file"
    value = prompt if args.mode == "append" else str(prompt_path)
    config = "# Managed by codex-purge; inspect with codex-purge status.\n" + f"{key} = {quote(value)}\n"
    if model:
        config += f"model = {quote(model)}\n"
    # Validate what will be written before touching any files.
    tomllib.loads(config)
    return {"preset": selected, "mode": args.mode, "model": model, "source": str(source),
            "base_sources": base_sources, "prompt": prompt, "prompt_sha256": checksum,
            "prompt_path": str(prompt_path), "config": config, "config_sha256": sha(config.encode()),
            "profile_path": str(manager.target)}


def public_plan(plan: dict, show_prompt: bool = False) -> dict:
    return {k: v for k, v in plan.items() if k != "config" and (k != "prompt" or show_prompt)}


def doctor(binary: str) -> dict:
    executable = shutil.which(binary)
    if not executable:
        return {"ok": False, "error": f"Codex executable not found: {binary}"}
    version = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=15)
    help_result = subprocess.run([executable, "--help"], capture_output=True, text=True, timeout=15)
    standalone = "--profile" in help_result.stdout and ".config.toml" in help_result.stdout
    return {"ok": version.returncode == 0 and help_result.returncode == 0 and standalone,
            "codex": executable, "version": version.stdout.strip(), "standalone_profile_supported": standalone,
            "python": sys.version.split()[0], "platform": sys.platform,
            "effectiveness": "configuration compatibility only; model behavior needs a separate E2E"}


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Inspectable, reversible instruction profiles for Codex CLI")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--codex-home", default=os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    checkout = Path(__file__).resolve().parents[2]
    default_state = checkout / ".state" if (checkout / "pyproject.toml").is_file() else Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "codex-purge"
    p.add_argument("--state-dir", default=os.environ.get("CODEX_PURGE_STATE", str(default_state)))
    p.add_argument("--name", default="codex-purge")
    p.add_argument("--codex", default="codex")
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("preview", "apply", "launch"):
        q = sub.add_parser(name)
        q.add_argument("--preset", default="auto")
        q.add_argument("--catalog")
        q.add_argument("--prompt", help="Use your own UTF-8 instruction file")
        q.add_argument("--base", help="Explicit base instructions to compose before the selected prompt")
        q.add_argument("--mode", choices=("append", "replace"), default="append")
        q.add_argument("--model")
        q.add_argument("--dry-run", action="store_true")
        q.add_argument("--show-prompt", action="store_true")
        if name == "launch":
            q.add_argument("codex_args", nargs=argparse.REMAINDER)
    for name in ("status", "rollback", "restore", "doctor", "presets"):
        sub.add_parser(name)
    return p


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        manager = Manager(Path(args.codex_home), Path(args.state_dir), args.name)
        if args.command == "doctor":
            result = doctor(args.codex)
        elif args.command == "presets":
            result = json.loads((Path(__file__).parent / "presets/catalog.json").read_text())
        elif args.command == "status":
            result = manager.status()
        elif args.command == "rollback":
            result = manager.rollback()
        elif args.command == "restore":
            result = manager.restore()
        else:
            plan = make_plan(manager, args)
            if args.command == "preview" or args.dry_run:
                result = {"ok": True, "dry_run": True, **public_plan(plan, args.show_prompt)}
            else:
                report = doctor(args.codex)
                if not report["ok"]:
                    raise ValueError("This Codex CLI does not advertise standalone named profiles. Run doctor.")
                if args.command == "launch":
                    extra = args.codex_args[1:] if args.codex_args[:1] == ["--"] else args.codex_args
                    for i, token in enumerate(extra):
                        if token == "--ignore-user-config" or token.startswith("--remote"):
                            raise ValueError("This option bypasses local profile loading and cannot be verified by this launcher.")
                        if token in ("-p", "--profile", "-m", "--model") or token.startswith(("--profile=", "--model=")):
                            raise ValueError("Use codex-purge --name / launch --model instead of overriding the managed profile/model.")
                        if (token.startswith("-p") or token.startswith("-m")) and not token.startswith("--"):
                            raise ValueError("Use codex-purge's profile and model options instead of a combined Codex short flag.")
                        if token.startswith(("developer_instructions=", "model_instructions_file=")):
                            raise ValueError("Forwarded instruction overrides would invalidate this profile.")
                        if re.match(r"^(?:-c|--config)=?(?:developer_instructions|model_instructions_file)=", token):
                            raise ValueError("Forwarded instruction overrides would invalidate this profile.")
                result = manager.apply(plan)
                if args.command == "launch":
                    print(json.dumps(result, ensure_ascii=False), file=sys.stderr)
                    environment = dict(os.environ, CODEX_HOME=str(manager.home))
                    return subprocess.run([args.codex, "--profile", manager.name, *extra], env=environment).returncode
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok", True) else 2
    except (Conflict, ValueError, OSError, KeyError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
