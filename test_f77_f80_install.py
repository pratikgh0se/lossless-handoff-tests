"""Install, uninstall, dry-run, saved defaults and the kept line for the history guard (F77, `--history-guard`, key
`history_guard`, a Stop hook with timeout 5) and the action guard (F80, `--action-guard`, key `action_guard`). Code-blind:
written from contract-0.18.md: the F64 opt-in rules apply. The two guards are separate files and can be installed with or
without claim-guard. The product spec pins the F80 event: PostToolBatch, no matcher, timeout 5."""
import json, os, re, unittest

from helpers import installed_home, run_install, run_uninstall
from test_f64_minimal_install import Base as InstBase, read_settings
from test_f68_f71_install import LeverInstall, entries, H


class HistoryGuard(LeverInstall, InstBase):
    flag, key, name, file = "--history-guard", "history_guard", "history-guard", "history-guard.py"
    event, timeout = "Stop", 5
    matcher = None

    def test_it_installs_with_and_without_claim_guard_as_separate_files(self):
        self.run_i(self.flag)
        self.assertFalse(os.path.exists(self.p(H + "claim-guard.py")))
        self.run_i("--claim-guard")
        self.assertTrue(os.path.exists(self.p(H + "claim-guard.py")))
        self.assertTrue(os.path.exists(self.p(H + "history-guard.py")))
        self.assertEqual(len(entries(read_settings(self.home), "history-guard.py")), 1)
        self.assertEqual(len(entries(read_settings(self.home), "claim-guard.py")), 1)
        self.run_u()
        self.assertFalse(os.path.exists(self.p(H + "history-guard.py")))
        self.assertFalse(os.path.exists(self.p(H + "claim-guard.py")))

    def test_the_two_guards_with_every_lever_install_and_uninstall_cleanly(self):
        self.run_i(self.flag, "--action-guard", "--claim-guard", "--reanchor")
        s = read_settings(self.home)
        for f in ("history-guard.py", "action-guard.py", "claim-guard.py", "reanchor.py"):
            self.assertEqual(len(entries(s, f)), 1, f)
        self.run_u()
        for f in ("history-guard.py", "action-guard.py", "claim-guard.py", "reanchor.py"):
            self.assertFalse(os.path.exists(self.p(H + f)), f)
        self.assertEqual(entries(read_settings(self.home), "guard.py"), [])


class ActionGuard(LeverInstall, InstBase):
    flag, key, name, file = "--action-guard", "action_guard", "action-guard", "action-guard.py"
    event = "(builder's choice)"  # makes the mixin check the kept-line registration count
    matcher = timeout = None

    def test_flag_registers_the_settings_entry(self):
        self.run_i(self.flag)
        es = entries(read_settings(self.home), self.file)
        self.assertEqual(len(es), 1, es)
        ev, g, h = es[0]
        self.assertEqual(ev, "PostToolBatch")
        self.assertNotIn("matcher", g, "the event has no matcher")
        self.assertEqual(h.get("type"), "command")
        self.assertEqual(h.get("timeout"), 5)
        self.assertRegex(h["command"], r"^python3 \S+/\.claude/hooks/action-guard\.py$")

    def test_each_guard_installs_guard_common_py(self):
        for flag in ("--action-guard", "--history-guard"):
            self.run_i(flag)
            self.assertTrue(os.path.exists(self.p(H + "guard_common.py")), flag)

    def test_rerun_keeps_the_part_and_prints_the_kept_line_once(self):
        self.run_i(self.flag)
        r = self.run_i()
        kept = "%s: already installed, kept" % self.name
        self.assertEqual(len([l for l in (r.stdout + r.stderr).split("\n") if l.startswith(kept)]), 1, r.stdout + r.stderr)
        self.assertEqual(len(entries(read_settings(self.home), self.file)), 1)
        self.run_i("--no-action-guard")
        self.assertTrue(os.path.exists(self.p(H + self.file)))

    def test_rerun_with_the_flag_does_not_register_twice(self):
        self.run_i(self.flag)
        self.run_i(self.flag)
        self.assertEqual(len(entries(read_settings(self.home), self.file)), 1)

    def test_uninstall_removes_the_file_and_the_entry_and_keeps_other_settings(self):
        before = {"permissions": {"allow": ["Bash(ls:*)"]},
                  "hooks": {"PostToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "echo mine"}]}]}}
        self.put_settings(before)
        self.run_i(self.flag)
        self.run_u()
        self.assertFalse(os.path.exists(self.p(H + self.file)))
        with open(self.sp()) as f:
            self.assertEqual(json.load(f), before)


if __name__ == "__main__":
    unittest.main()
