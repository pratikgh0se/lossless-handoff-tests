"""F49 Uninstall: ACs 202-207 of docs/spec.md. Every run uses a temp HOME and LOSSLESS_HANDOFF_NO_LAUNCHCTL=1,
except the second half of AC 207, which uses a FAKE launchctl first on PATH (macOS only)."""
import json, os, shutil, stat, subprocess, sys, tempfile, unittest

from helpers import (IS_MACOS, LABEL_PREFIX, run_install, run_uninstall, CANARY_RUN)

HOOK_FILES = ("precompact-handoff.py", "postcompact-inject.py", "handoff-nudge.py", "recall.py", "claims.json",
              ".handoff-manifest.json", ".claude-handoff-install.json")


def snapshot(root):
    out = {}
    for d, _, files in os.walk(root):
        for n in files:
            p = os.path.join(d, n)
            rel = os.path.relpath(p, root)
            out[rel] = os.readlink(p) if os.path.islink(p) else open(p, "rb").read()
    return out


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="un-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self.hooks = os.path.join(self.home, ".claude", "hooks")
        self.state = os.path.join(self.home, ".local", "state", "claude-handoffs")
        self.agents = os.path.join(self.home, "Library", "LaunchAgents")

    def install(self, *args, **kw):
        r = run_install(self.home, *args, **kw)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.wait_first_index()
        return r

    def wait_first_index(self):
        """install.sh starts a first recall index in the background; wait until it has written its log, so that it
        cannot change a file while a test compares snapshots."""
        import time
        log = os.path.join(self.state, "recall", "index-all.log")
        end = time.time() + 20
        while time.time() < end:
            if os.path.exists(log) and os.path.getsize(log) > 0:
                break
            time.sleep(0.2)
        time.sleep(0.5)

    def uninstall(self, *args, **kw):
        r = run_uninstall(self.home, *args, **kw)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r


class Settings(Base):
    def test_ac202_settings_restored(self):
        os.makedirs(os.path.join(self.home, ".claude"))
        before = {"hooks": {"PreCompact": [{"hooks": [{"type": "command", "command": "echo other"}]}]},
                  "permissions": {"allow": ["Bash(ls:*)"]}, "env": {"FOO": "1"}}
        sp = os.path.join(self.home, ".claude", "settings.json")
        json.dump(before, open(sp, "w"))
        self.install("--no-nightly")
        self.assertNotEqual(json.load(open(sp)), before)
        self.uninstall()
        self.assertEqual(json.load(open(sp)), before)


class Files(Base):
    def test_ac203_files_removed_state_kept(self):
        self.install("--no-nightly")
        os.makedirs(self.state, exist_ok=True)
        extra = os.path.join(self.state, "S-latest.md")
        open(extra, "w").write("KEEP ME\n")
        self.assertTrue(os.path.isfile(os.path.join(self.hooks, "precompact-handoff.py")))
        state_before = snapshot(self.state)
        self.assertIn("S-latest.md", state_before)
        self.uninstall()
        for n in HOOK_FILES:
            self.assertFalse(os.path.exists(os.path.join(self.hooks, n)), n)
        self.assertEqual(snapshot(self.state), state_before)

    def test_ac203_custom_state_dir_kept(self):
        custom = os.path.join(self.tmp, "mystate")
        os.makedirs(custom)
        open(os.path.join(custom, "S-latest.md"), "w").write("KEEP\n")
        self.install("--no-nightly", extra={"HANDOFF_STATE_DIR": custom})
        before = snapshot(custom)
        self.uninstall(extra={"HANDOFF_STATE_DIR": custom})
        self.assertEqual(snapshot(custom), before)
        self.assertEqual(open(os.path.join(custom, "S-latest.md")).read(), "KEEP\n")


class Idempotent(Base):
    def test_ac204_second_uninstall_changes_nothing(self):
        self.install("--no-nightly")
        self.uninstall()
        after1 = snapshot(self.home)
        self.uninstall()
        self.assertEqual(snapshot(self.home), after1)

    def test_ac204_dry_run_changes_nothing(self):
        self.install("--no-nightly")
        before = snapshot(self.home)
        self.uninstall("--dry-run")
        self.assertEqual(snapshot(self.home), before)


def fake_bin(tmp):
    d = os.path.join(tmp, "fakebin")
    os.makedirs(d)
    log = os.path.join(tmp, "launchctl.log")
    p = os.path.join(d, "launchctl")
    open(p, "w").write('#!/bin/sh\necho "$@" >> "%s"\nexit 0\n' % log)
    os.chmod(p, 0o755)
    return d, log


class Canary(Base):
    def test_ac205_canary_removed_state_kept(self):
        self.install("--no-nightly", "--canary")
        cdir = os.path.join(self.hooks, "handoff-canary")
        self.assertTrue(os.path.isdir(cdir))
        # run the canary once, with a stub `claude`, so Python writes handoff-canary/__pycache__/
        fb, _ = fake_bin(self.tmp)
        os.remove(os.path.join(fb, "launchctl"))
        open(os.path.join(fb, "claude"), "w").write("#!/bin/sh\nexit 1\n")
        os.chmod(os.path.join(fb, "claude"), 0o755)
        tmpdir = os.path.join(self.tmp, "t")
        os.makedirs(tmpdir)
        env = {"HOME": self.home, "PATH": fb + ":/usr/bin:/bin", "TMPDIR": tmpdir, "LANG": "C.UTF-8",
               "HANDOFF_CANARY_NOTIFY": "0", "HANDOFF_CANARY_TIMEOUT_S": "30"}
        subprocess.run(["/bin/bash", os.path.join(cdir, "run.sh")], env=env, stdin=subprocess.DEVNULL,
                       capture_output=True, text=True, timeout=120)
        subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, %r); import check" % cdir],
                       env=env, capture_output=True, timeout=30)
        self.assertTrue(os.path.isdir(os.path.join(cdir, "__pycache__")), "fixture: no __pycache__ was written")
        cstate = os.path.join(self.home, ".local", "state", "handoff-canary")
        os.makedirs(cstate, exist_ok=True)
        open(os.path.join(cstate, "keep.txt"), "w").write("KEEP\n")
        before = snapshot(cstate)
        self.uninstall()
        self.assertFalse(os.path.exists(cdir))
        self.assertFalse(os.path.exists(os.path.join(self.hooks, "handoff-canary.sh")))
        if IS_MACOS:
            self.assertFalse(os.path.exists(os.path.join(self.agents, LABEL_PREFIX + ".handoff-canary.plist")))
        self.assertEqual(snapshot(cstate), before)


@unittest.skipUnless(IS_MACOS, "LaunchAgents exist on macOS only")
class LaunchAgents(Base):
    def test_ac206_launchagents_removed(self):
        self.install("--nightly")  # F64.a: the nightly jobs are opt-in
        names = [LABEL_PREFIX + ".recall-index.plist", LABEL_PREFIX + ".handoff-reconcile.plist"]
        for n in names:
            self.assertTrue(os.path.isfile(os.path.join(self.agents, n)), n)
        self.uninstall()
        for n in names:
            self.assertFalse(os.path.exists(os.path.join(self.agents, n)), n)


class NoLaunchctl(Base):
    def setUp(self):
        super().setUp()
        self.fb, self.log = fake_bin(self.tmp)
        self.path = self.fb + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin")

    def test_ac207_variable_set_never_calls_launchctl(self):
        self.assertEqual(os.path.realpath(shutil.which("launchctl", path=self.path)),
                         os.path.realpath(os.path.join(self.fb, "launchctl")))
        self.install("--canary", "--nightly", path=self.path)
        if IS_MACOS:
            for j in ("recall-index", "handoff-reconcile", "handoff-canary"):
                self.assertTrue(os.path.isfile(os.path.join(self.agents, "%s.%s.plist" % (LABEL_PREFIX, j))), j)
        self.uninstall(path=self.path)
        if IS_MACOS:
            for j in ("recall-index", "handoff-reconcile", "handoff-canary"):
                self.assertFalse(os.path.exists(os.path.join(self.agents, "%s.%s.plist" % (LABEL_PREFIX, j))), j)
        self.assertTrue(not os.path.exists(self.log) or open(self.log).read().strip() == "",
                        open(self.log).read() if os.path.exists(self.log) else "")

    @unittest.skipUnless(IS_MACOS, "the launchctl calls happen on macOS only")
    def test_ac207_variable_unset_calls_fake_launchctl_bootstrap(self):
        # SAFETY: run_install checks that the FAKE launchctl is first on PATH, then drops the variable. Temp HOME.
        self.assertEqual(os.path.realpath(shutil.which("launchctl", path=self.path)),
                         os.path.realpath(os.path.join(self.fb, "launchctl")))
        r = run_install(self.home, "--canary", "--nightly", path=self.path, fake_launchctl=self.fb)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(os.path.exists(self.log), "the fake launchctl was never called")
        calls = [l.split() for l in open(self.log).read().split("\n") if l.strip()]
        self.assertTrue(any("bootstrap" in c for c in calls), calls)


if __name__ == "__main__":
    unittest.main()
