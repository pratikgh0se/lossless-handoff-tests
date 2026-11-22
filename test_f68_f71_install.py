"""Install, uninstall, dry-run, saved defaults and the kept line for the four levers of 0.16.0 (F68-F71), plus the
versions (0.16.0 / 1.18.0). Code-blind: written from contract-0.16.md. Every lever is opt-in and follows the F64 rules.
`claude mcp add` is tested with a fake `claude` on PATH that records its arguments, and with no `claude` on PATH."""
import json, os, re, shutil, stat, tempfile, unittest

from helpers import HOOKS_DIR, REPO, installed_home, run_install, run_uninstall
from test_f64_minimal_install import Base as InstBase, DEFAULTS_REL, read_settings, tree

H = ".claude/hooks/"
SAFE_PATH = "/usr/bin:/bin"
MCP_ADD = "claude mcp add --scope user lossless-recall -- python3 %s/recall-mcp.py"
NOT_FOUND = re.compile(r"recall-mcp: claude CLI not found; register it later with: "
                       r"claude mcp add --scope user lossless-recall -- python3 (\S+)/recall-mcp\.py")


def entries(settings, script):
    out = []
    for ev, groups in (settings.get("hooks") or {}).items():
        for g in groups:
            for h in g.get("hooks", []):
                if script in h.get("command", ""):
                    out.append((ev, g, h))
    return out


class LeverInstall:
    """Mixin: the F64 opt-in rules for one lever. Subclasses set the class fields."""
    flag = key = name = file = None
    event = matcher = None  # None: no settings entry
    timeout = None

    def fake_claude(self):
        d = os.path.join(self.tmp, "fakebin")
        os.makedirs(d)
        self.claude_log = os.path.join(self.tmp, "claude.log")
        p = os.path.join(d, "claude")
        with open(p, "w") as f:
            f.write("#!/bin/sh\nprintf '%%s\\n' \"claude $*\" >> %s\nexit 0\n" % self.claude_log)
        os.chmod(p, 0o755)
        return d + ":" + SAFE_PATH

    def run_i(self, *args, path=None):
        r = run_install(self.home, *args, path=path or self.path)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.wait_first_index()
        return r

    def run_u(self, *args, path=None):
        r = run_uninstall(self.home, *args, path=path or self.path)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r

    def defaults(self, home=None):
        return os.path.join(home or self.home, DEFAULTS_REL)

    def lines_of_defaults(self):
        with open(self.defaults()) as f:
            return f.read().split("\n")

    def setUp(self):
        super().setUp()
        self.path = self.fake_claude()

    # --- default install
    def test_default_install_has_no_lever(self):
        home, _ = installed_home()
        self.assertFalse(os.path.exists(os.path.join(home, H + self.file)))
        s = json.dumps(read_settings(home))
        self.assertNotIn(self.file, s)

    # --- flag
    def test_flag_installs_the_part(self):
        self.run_i(self.flag)
        self.assertTrue(os.path.exists(self.p(H + self.file)))
        if self.file.endswith(".py"):
            with open(os.path.join(HOOKS_DIR, self.file), "rb") as a, open(self.p(H + self.file), "rb") as b:
                self.assertEqual(a.read(), b.read())

    def test_flag_registers_the_settings_entry(self):
        self.run_i(self.flag)
        es = entries(read_settings(self.home), self.file)
        if self.event is None:
            self.assertEqual(es, [])
            return
        self.assertEqual(len(es), 1, es)
        ev, g, h = es[0]
        self.assertEqual(ev, self.event)
        self.assertEqual(h.get("type"), "command")
        self.assertEqual(h.get("timeout"), self.timeout)
        self.assertEqual(g.get("matcher"), self.matcher)
        self.assertRegex(h["command"], r"^python3 \S+/\.claude/hooks/%s$" % re.escape(self.file))

    def test_flag_adds_only_its_own_part(self):
        base, _ = installed_home()
        self.run_i(self.flag)
        extra = {x for x in tree(self.home) - tree(base) if x.startswith(".claude/")}
        self.assertTrue(os.path.exists(self.p(H + self.file)))
        if not self.file.startswith("."):
            self.assertIn(H + self.file, extra)
        for other in ("recall-mcp.py", "reanchor.py", "claim-guard.py", ".recall-rules", "auto-recall.py"):
            if other != self.file:
                self.assertNotIn(H + other, extra, other)
                self.assertFalse(os.path.exists(self.p(H + other)), other)

    def test_flag_lists_in_dry_run_only_when_given(self):
        r = run_install(self.home, "--dry-run", self.flag, path=self.path)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(self.file, r.stdout + r.stderr)
        self.assertEqual(sorted(x for x in os.listdir(self.home) if x != "Library"), [])
        r = run_install(self.home, "--dry-run", path=self.path)
        plan = "\n".join(l for l in (r.stdout + r.stderr).split("\n") if "not selected" not in l)
        self.assertNotIn(self.file, plan)

    def test_help_lists_both_flags(self):
        r = run_install(self.home, "--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn(self.flag, r.stdout)
        self.assertIn("--no-" + self.flag[2:], r.stdout)

    # --- saved defaults
    def test_save_defaults_writes_the_key_and_a_plain_run_applies_it(self):
        self.run_i(self.flag, "--save-defaults")
        self.assertIn(self.key + "=1", self.lines_of_defaults())
        home2 = os.path.join(self.tmp, "home2")
        os.makedirs(os.path.join(home2, ".config", "lossless-handoff"))
        shutil.copy(self.defaults(), self.defaults(home2))
        r = run_install(home2, path=self.path)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(os.path.exists(os.path.join(home2, H + self.file)))

    def test_no_flag_turns_a_saved_default_off_for_one_run(self):
        self.run_i(self.flag, "--save-defaults")
        home2 = os.path.join(self.tmp, "home2")
        os.makedirs(os.path.join(home2, ".config", "lossless-handoff"))
        shutil.copy(self.defaults(), self.defaults(home2))
        r = run_install(home2, "--no-" + self.flag[2:], path=self.path)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(os.path.exists(os.path.join(home2, H + self.file)))
        with open(self.defaults(home2)) as f:
            self.assertIn(self.key + "=1", f.read().split("\n"), "the file is unchanged")

    def test_save_defaults_with_no_flag_removes_the_line_and_keeps_the_part(self):
        self.run_i(self.flag, "--save-defaults")
        self.run_i("--no-" + self.flag[2:], "--save-defaults")
        self.assertNotIn(self.key + "=1", self.lines_of_defaults())
        self.assertTrue(os.path.exists(self.p(H + self.file)))

    def test_without_save_defaults_no_line_is_written(self):
        self.run_i(self.flag)
        if os.path.exists(self.defaults()):
            self.assertNotIn(self.key + "=1", self.lines_of_defaults())

    # --- re-install
    def test_rerun_keeps_the_part_and_prints_the_kept_line_once(self):
        self.run_i(self.flag)
        r = self.run_i()
        kept = "%s: already installed, kept" % self.name
        lines = [l for l in (r.stdout + r.stderr).split("\n") if l.startswith(kept)]
        self.assertEqual(len(lines), 1, r.stdout + r.stderr)
        self.assertTrue(os.path.exists(self.p(H + self.file)))
        self.run_i("--no-" + self.flag[2:])
        self.assertTrue(os.path.exists(self.p(H + self.file)))
        if self.event:
            self.assertEqual(len(entries(read_settings(self.home), self.file)), 1)

    def test_rerun_with_the_flag_does_not_register_twice(self):
        self.run_i(self.flag)
        self.run_i(self.flag)
        if self.event:
            self.assertEqual(len(entries(read_settings(self.home), self.file)), 1)

    def test_no_kept_line_without_an_install(self):
        r = self.run_i()
        self.assertNotIn("%s: already installed" % self.name, r.stdout + r.stderr)
        r = self.run_i(self.flag)
        self.assertNotIn("%s: already installed" % self.name, r.stdout + r.stderr)

    # --- uninstall
    def test_uninstall_removes_the_file_and_the_entry_and_keeps_other_settings(self):
        before = {"permissions": {"allow": ["Bash(ls:*)"]},
                  "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo mine"}]}]}}
        self.put_settings(before)
        self.run_i(self.flag)
        self.run_u()
        self.assertFalse(os.path.exists(self.p(H + self.file)))
        with open(self.sp()) as f:
            self.assertEqual(json.load(f), before)


class RecallRules(LeverInstall, InstBase):
    flag, key, name, file = "--recall-rules", "recall_rules", "recall-rules", ".recall-rules"

    def test_marker_file_is_empty_or_text_and_not_a_hook(self):
        self.run_i(self.flag)
        self.assertTrue(os.path.isfile(self.p(H + ".recall-rules")))
        self.assertEqual(entries(read_settings(self.home), "recall-rules"), [])

    def test_marker_is_removed_by_uninstall_even_without_settings_changes(self):
        self.run_i(self.flag)
        self.run_u()
        self.assertFalse(os.path.exists(self.p(H + ".recall-rules")))


class Reanchor(LeverInstall, InstBase):
    flag, key, name, file = "--reanchor", "reanchor", "reanchor", "reanchor.py"
    event, matcher, timeout = "PostToolUse", "*", 5


class ClaimGuard(LeverInstall, InstBase):
    flag, key, name, file = "--claim-guard", "claim_guard", "claim-guard", "claim-guard.py"
    event, timeout = "Stop", 5
    matcher = None


class RecallMcp(LeverInstall, InstBase):
    flag, key, name, file = "--recall-mcp", "recall_mcp", "recall-mcp", "recall-mcp.py"

    def calls(self):
        if not os.path.exists(self.claude_log):
            return []
        return [l for l in open(self.claude_log).read().split("\n") if l]

    def test_install_registers_with_claude_mcp_add(self):
        self.run_i(self.flag)
        hooks_dir = os.path.join(self.home, ".claude", "hooks")
        adds = [c for c in self.calls() if c.startswith("claude mcp add")]
        self.assertEqual(adds, [MCP_ADD % hooks_dir], self.calls())

    def test_install_never_edits_claude_json(self):
        self.run_i(self.flag)
        self.assertFalse(os.path.exists(self.p(".claude.json")))

    def test_uninstall_runs_claude_mcp_remove(self):
        self.run_i(self.flag)
        self.run_u()
        self.assertIn("claude mcp remove lossless-recall --scope user", self.calls())
        self.assertFalse(os.path.exists(self.p(H + "recall-mcp.py")))

    def test_default_install_does_not_call_claude_mcp(self):
        self.run_i()
        self.assertEqual([c for c in self.calls() if "mcp" in c], [])

    def test_no_claude_on_path_prints_the_register_later_line_and_still_installs(self):
        r = run_install(self.home, self.flag, path=SAFE_PATH)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        m = NOT_FOUND.search(r.stdout + r.stderr)
        self.assertTrue(m, r.stdout + r.stderr)
        self.assertEqual(m.group(1), os.path.join(self.home, ".claude", "hooks"))
        self.assertTrue(os.path.exists(self.p(H + "recall-mcp.py")))

    def test_found_claude_does_not_print_the_register_later_line(self):
        r = self.run_i(self.flag)
        self.assertNotIn("claude CLI not found", r.stdout + r.stderr)

    def test_uninstall_without_claude_on_path_exits_0(self):
        self.run_i(self.flag)
        r = run_uninstall(self.home, path=SAFE_PATH)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(os.path.exists(self.p(H + "recall-mcp.py")))

    def test_uninstall_ignores_a_failing_claude(self):
        self.run_i(self.flag)
        with open(os.path.join(self.tmp, "fakebin", "claude"), "w") as f:
            f.write("#!/bin/sh\nexit 1\n")
        r = run_uninstall(self.home, path=self.path)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(os.path.exists(self.p(H + "recall-mcp.py")))

    def test_a_failing_add_prints_one_line_with_the_command_and_exits_0(self):
        with open(os.path.join(self.tmp, "fakebin", "claude"), "w") as f:
            f.write("#!/bin/sh\nexit 1\n")
        r = run_install(self.home, self.flag, path=self.path)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        hooks_dir = os.path.join(self.home, ".claude", "hooks")
        lines = [l for l in (r.stdout + r.stderr).split("\n") if (MCP_ADD % hooks_dir) in l]
        self.assertEqual(len(lines), 1, r.stdout + r.stderr)
        self.assertTrue(os.path.exists(self.p(H + "recall-mcp.py")))

    def test_dry_run_lists_the_command(self):
        r = run_install(self.home, "--dry-run", self.flag, path=self.path)
        self.assertIn("claude mcp add --scope user lossless-recall -- python3", r.stdout + r.stderr)

    def test_dry_run_does_not_call_claude(self):
        run_install(self.home, "--dry-run", self.flag, path=self.path)
        self.assertEqual(self.calls(), [])


class AllTogether(InstBase):
    def test_all_four_flags_install_and_uninstall_cleanly(self):
        base, _ = installed_home()
        d = os.path.join(self.tmp, "fakebin")
        os.makedirs(d)
        with open(os.path.join(d, "claude"), "w") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.chmod(os.path.join(d, "claude"), 0o755)
        path = d + ":" + SAFE_PATH
        r = run_install(self.home, "--recall-rules", "--recall-mcp", "--reanchor", "--claim-guard", path=path)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.wait_first_index()
        for n in (".recall-rules", "recall-mcp.py", "reanchor.py", "claim-guard.py"):
            self.assertTrue(os.path.exists(self.p(H + n)), n)
        r = run_uninstall(self.home, path=path)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for n in (".recall-rules", "recall-mcp.py", "reanchor.py", "claim-guard.py"):
            self.assertFalse(os.path.exists(self.p(H + n)), n)
        s = json.dumps(read_settings(self.home))
        for n in ("reanchor.py", "claim-guard.py", "recall-mcp.py"):
            self.assertNotIn(n, s)


class Versions(unittest.TestCase):
    def test_install_sh_version_is_0_16_0(self):
        home = os.path.realpath(tempfile.mkdtemp(prefix="lev-v-"))
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        r = run_install(home, "--version")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("0.16.0", r.stdout + r.stderr)

    def test_installed_manifest_version_is_1_18_0(self):
        home, _ = installed_home()
        with open(os.path.join(home, ".claude", "hooks", ".handoff-manifest.json")) as f:
            self.assertEqual(json.load(f)["version"], "1.18.0")

    def test_changelog_has_0_16_0_first(self):
        with open(os.path.join(REPO, "CHANGELOG.md")) as f:
            heads = re.findall(r"(?m)^## \[([0-9.]+)\]", f.read())
        self.assertEqual(heads[0], "0.16.0")

    def test_hook_version_constants_are_1_18_0_in_every_hook_that_has_one(self):
        for n in ("precompact-handoff.py", "postcompact-inject.py", "auto-recall.py", "recall-mcp.py", "reanchor.py",
                  "claim-guard.py"):
            p = os.path.join(HOOKS_DIR, n)
            self.assertTrue(os.path.isfile(p), n)
            with open(p) as f:
                self.assertRegex(f.read(), r"""HOOK_VERSION\s*=\s*["']1\.18\.0["']""", n)

    def test_levers_are_in_the_manifest_when_installed(self):
        home, _ = installed_home("--reanchor", "--claim-guard")
        with open(os.path.join(home, ".claude", "hooks", ".handoff-manifest.json")) as f:
            files = json.load(f)["files"]
        self.assertIn("reanchor.py", files)
        self.assertIn("claim-guard.py", files)


if __name__ == "__main__":
    unittest.main()
