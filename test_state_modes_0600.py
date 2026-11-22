"""Spec 3.3a File mode. All files the hooks write under the state folder (handoffs, health log, decisions list, state,
backups, recall index) have mode 0600, and new folders have mode 0700. The hooks set `umask 077`. `install.sh` sets
existing files to 0600 (not `managed-settings.json`, and not in dry-run: PR description). Code-blind: written from
docs/spec.md 3.3a and the PR description only. The merge model is stubbed with the `claude` shim."""
import os, stat, unittest

from helpers import *
from test_f39_ledger import F39, ts, key_for
from test_f64_minimal_install import Base as InstBase
import history_common as hc


def snapshot(root):
    out = {}
    for d, dirs, files in os.walk(root):
        for n in dirs + files:
            p = os.path.join(d, n)
            out[p] = os.lstat(p)
    return out


def mode(p):
    return stat.S_IMODE(os.lstat(p).st_mode)


class Umask:
    def __init__(self, m):
        self.m = m

    def __enter__(self):
        self.old = os.umask(self.m)

    def __exit__(self, *a):
        os.umask(self.old)


class Modes(F39):
    def new_paths(self, before):
        after = snapshot(self.hd)
        return {p: st for p, st in after.items() if p not in before}

    def check_new(self, before):
        new = self.new_paths(before)
        self.assertTrue(new, "the run wrote nothing")
        for p, st in sorted(new.items()):
            if stat.S_ISDIR(st.st_mode):
                self.assertEqual(stat.S_IMODE(st.st_mode), 0o700, "dir " + p)
            elif stat.S_ISREG(st.st_mode):
                self.assertEqual(stat.S_IMODE(st.st_mode), 0o600, "file " + p)

    def run_modes(self, um):
        before = {}
        with Umask(um):
            self.go()
        self.check_new(before)

    def test_mode_precompact_run_with_the_default_umask(self):
        self.run_modes(0o022)

    def test_mode_precompact_run_with_an_open_umask(self):
        self.run_modes(0o000)

    def test_mode_named_files_after_a_handoff_and_a_merge(self):
        with Umask(0o022):
            self.go()
        for rel in ("S-latest.md", "health.jsonl", "projects/%s/decisions.md" % key_for(self.repo_root),
                    "projects/%s/decisions.state.json" % key_for(self.repo_root),
                    "projects/%s/decisions.lock" % key_for(self.repo_root)):
            p = os.path.join(self.hd, rel)
            self.assertTrue(os.path.exists(p), rel)
            self.assertEqual(mode(p), 0o600, rel)

    def test_mode_new_folders_are_0700(self):
        with Umask(0o022):
            self.go()
        for d in (self.hd, os.path.join(self.hd, "projects"), self.pdir()):
            self.assertEqual(mode(d), 0o700, d)

    def test_mode_ledger_backup_and_second_merge_files(self):
        with Umask(0o022):
            self.go()
            before = snapshot(self.hd)
            self.write_transcript(self.convo() + self.convo(start=30, tag="-2", qid="q2"))
            self.set_shim("merge", out="- D3 [2026-10-25] Second batch rule | why: later\n")
            self.go()
        self.assertTrue(self.backups(), "the second merge makes a backup of the first ledger")
        for b in self.backups():
            self.assertEqual(mode(os.path.join(self.pdir(), b)), 0o600, b)
        for p, st in snapshot(self.hd).items():
            if stat.S_ISREG(st.st_mode):
                self.assertEqual(stat.S_IMODE(st.st_mode), 0o600, p)

    def test_mode_every_file_under_the_state_folder_after_two_runs(self):
        with Umask(0o022):
            self.go()
            self.go(sid="T")
        for p, st in snapshot(self.hd).items():
            if stat.S_ISREG(st.st_mode):
                self.assertEqual(stat.S_IMODE(st.st_mode), 0o600, p)
            elif stat.S_ISDIR(st.st_mode):
                self.assertEqual(stat.S_IMODE(st.st_mode), 0o700, p)

    def test_mode_a_rewritten_existing_file_keeps_0600(self):
        with Umask(0o022):
            self.go()
            p = os.path.join(self.hd, "S-latest.md")
            self.assertEqual(mode(p), 0o600)
            self.go()
        self.assertEqual(mode(p), 0o600)


class RecallModes(hc.Lab):
    def test_mode_recall_search_and_index_files(self):
        self.put(hc.SID1, [hc.entry("user", "invoice-mailer is on", "u1", hc.ts(1)),
                           hc.entry("assistant", "ok invoice-mailer noted", "a1", hc.ts(2))])
        before = snapshot(self.hd) if os.path.isdir(self.hd) else {}
        with Umask(0o022):
            self.run_recall("search", "invoice-mailer")
            self.run_recall("index")
            self.run_recall("map")
        if not os.path.isdir(self.hd):
            self.skipTest("recall wrote no state under the state folder")
        for p, st in snapshot(self.hd).items():
            if p in before:
                continue
            if stat.S_ISREG(st.st_mode):
                self.assertEqual(stat.S_IMODE(st.st_mode), 0o600, p)
            elif stat.S_ISDIR(st.st_mode):
                self.assertEqual(stat.S_IMODE(st.st_mode), 0o700, p)


class InstallModes(InstBase):
    def state_dir(self):
        return self.p(".local/state/claude-handoffs")

    def make(self, rel, content="x\n", m=0o644):
        p = os.path.join(self.state_dir(), rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(content)
        os.chmod(p, m)
        return p

    def test_mode_install_sets_existing_state_files_to_0600(self):
        files = [self.make("S-latest.md"), self.make("health.jsonl", "{}\n"), self.make("S-agent.md"),
                 self.make("projects/k-12345678/decisions.md"), self.make("projects/k-12345678/decisions.state.json", "{}"),
                 self.make("projects/k-12345678/decisions.20261001T000000Z.md"), self.make("recall/state.json", "{}")]
        r = run_install(self.home)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.wait_first_index()
        for p in files:
            self.assertEqual(mode(p), 0o600, p)

    def test_mode_install_dry_run_changes_no_mode(self):
        p = self.make("S-latest.md")
        r = run_install(self.home, "--dry-run")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(mode(p), 0o644)

    def test_mode_install_leaves_managed_settings_json_alone(self):
        p = self.make("managed-settings.json", "{}")
        r = run_install(self.home)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.wait_first_index()
        self.assertEqual(mode(p), 0o644)

    def test_mode_a_second_install_keeps_0600(self):
        p = self.make("S-latest.md")
        run_install(self.home)
        self.wait_first_index()
        run_install(self.home)
        self.wait_first_index()
        self.assertEqual(mode(p), 0o600)


if __name__ == "__main__":
    unittest.main()
