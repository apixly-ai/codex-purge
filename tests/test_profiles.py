import argparse
import contextlib
import io
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from codex_purge.cli import Conflict, Manager, make_plan, sha, write_json, main


class ProfilesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home with spaces"
        self.home.mkdir()
        self.manager = Manager(self.home, self.root / "state")

    def plan(self, text="Diagnostic instruction", **kwargs):
        prompt = self.root / "custom.md"
        prompt.write_text(text)
        args = argparse.Namespace(model=None, catalog=None, preset="auto", prompt=str(prompt),
                                  base=None, mode="append")
        for key, value in kwargs.items():
            setattr(args, key, value)
        return make_plan(self.manager, args)

    def test_preview_is_read_only(self):
        plan = self.plan()
        self.assertFalse(self.manager.root.exists())
        self.assertEqual(tomllib.loads(plan["config"])["developer_instructions"], "Diagnostic instruction\n")

    def test_apply_idempotence_and_restore_preserve_user_config(self):
        original = b'# Existing comment\nmodel = "gpt-6.1-sol"\n'
        (self.home / "config.toml").write_bytes(original)
        plan = self.plan()
        first = self.manager.apply(plan)
        self.assertTrue(first["changed"])
        self.assertFalse(self.manager.apply(plan)["changed"])
        self.assertEqual(len(self.manager.state()["history"]), 1)
        self.manager.restore()
        self.assertFalse(self.manager.target.exists())
        self.assertEqual((self.home / "config.toml").read_bytes(), original)

    def test_collision_does_not_overwrite(self):
        self.manager.target.write_text("# User owned\n")
        with self.assertRaises(Conflict):
            self.manager.apply(self.plan())
        self.assertEqual(self.manager.target.read_text(), "# User owned\n")

    def test_config_and_prompt_drift_block_mutation(self):
        self.manager.apply(self.plan())
        original = self.manager.target.read_bytes()
        self.manager.target.write_bytes(original + b"# User edit\n")
        with self.assertRaises(Conflict):
            self.manager.restore()
        self.manager.target.write_bytes(original)
        Path(self.manager.state()["active"]["prompt_path"]).write_text("Changed")
        with self.assertRaises(Conflict):
            self.manager.rollback()

    def test_rollback_follows_parent_after_branch(self):
        a = self.manager.apply(self.plan("A"))["version"]
        self.manager.apply(self.plan("B"))
        self.assertEqual(self.manager.rollback()["version"], a)
        self.manager.apply(self.plan("C"))
        self.assertEqual(self.manager.rollback()["version"], a)
        self.assertFalse(self.manager.rollback()["active"])

    def test_concurrent_identical_apply_has_one_version(self):
        plan = self.plan()
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _: self.manager.apply(plan), range(6)))
        self.assertEqual(sum(row["changed"] for row in results), 1)
        self.assertEqual(len(self.manager.state()["history"]), 1)

    def test_append_preserves_existing_developer_text(self):
        (self.home / "config.toml").write_text('developer_instructions = "Existing policy"\n')
        plan = self.plan("New preference")
        self.assertEqual(plan["prompt"], "Existing policy\n\nNew preference\n")

    def test_replace_uses_absolute_immutable_prompt(self):
        plan = self.plan(mode="replace")
        self.manager.apply(plan)
        config = tomllib.loads(self.manager.target.read_text())
        self.assertNotIn("developer_instructions", config)
        self.assertTrue(Path(config["model_instructions_file"]).is_absolute())
        self.assertEqual(Path(config["model_instructions_file"]).read_text(), plan["prompt"])

    def test_recover_completed_target_write(self):
        self.manager.apply(self.plan("A"))
        state = self.manager.state()
        before = sha(self.manager.target.read_bytes())
        config = self.plan("B")["config"]
        state["recovery_test"] = True
        write_json(self.manager.pending, {"before_sha": before, "after_sha": sha(config.encode()), "state": state})
        self.manager.target.write_text(config)
        with self.manager.locked():
            pass
        self.assertTrue(self.manager.state()["recovery_test"])
        self.assertFalse(self.manager.pending.exists())

    def test_interrupted_transaction_preserves_external_edit(self):
        self.manager.apply(self.plan())
        write_json(self.manager.pending, {"before_sha": "a", "after_sha": "b", "state": self.manager.state()})
        with self.assertRaises(Conflict):
            with self.manager.locked():
                pass
        self.assertTrue(self.manager.pending.exists())

    def test_names_symlinks_and_empty_prompt_are_rejected(self):
        with self.assertRaises(ValueError):
            Manager(self.home, self.root, "../escape")
        with self.assertRaises(ValueError):
            self.plan("  ")
        other = self.root / "precious"
        other.write_text("Keep")
        self.manager.target.symlink_to(other)
        with self.assertRaises(Conflict):
            self.manager.apply(self.plan())
        self.assertEqual(other.read_text(), "Keep")

    def test_custom_catalog_model_match_and_unicode(self):
        prompt = self.root / "研究.md"
        prompt.write_text('第一行\n"quoted"\\path\n')
        catalog = self.root / "catalog.json"
        catalog.write_text(json.dumps({"default": "x", "rules": [{"pattern": "gpt-6*", "preset": "six"}],
            "presets": {"six": {"file": prompt.name}, "x": {"file": prompt.name}}}))
        args = argparse.Namespace(model="gpt-6.1-sol", catalog=str(catalog), preset="auto", prompt=None,
                                  base=None, mode="append")
        plan = make_plan(self.manager, args)
        self.assertEqual(plan["preset"], "six")
        self.assertEqual(tomllib.loads(plan["config"])["developer_instructions"], prompt.read_text())

    def test_launch_rejects_profile_bypass_before_writing(self):
        options = ["--ignore-user-config", "--profile=other", "-pother", "-mother",
                   "--config=developer_instructions=other", "--remote=ws://example.invalid"]
        for option in options:
            with self.subTest(option=option), patch("codex_purge.cli.doctor", return_value={"ok": True}):
                with contextlib.redirect_stderr(io.StringIO()):
                    result = main(["--codex-home", str(self.home), "--state-dir", str(self.root / "state"),
                                   "launch", "--", option])
                self.assertEqual(result, 2)
                self.assertFalse(self.manager.target.exists())

    def test_invalid_model_config_fails_cleanly(self):
        (self.home / "config.toml").write_text("model = true\n")
        with self.assertRaises(ValueError):
            self.plan()


if __name__ == "__main__":
    unittest.main()
