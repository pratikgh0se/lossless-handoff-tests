"""F50 Install without the nudge: ACs 208-211 of docs/spec.md. Temp HOME, LOSSLESS_HANDOFF_NO_LAUNCHCTL=1 (set by the
helpers), RECALL_EMBED_URL on a closed port."""
import collections, json, os, shutil, subprocess, sys, tempfile, time, unittest

from helpers import run_install, run_uninstall, installed_settings

NUDGE = "handoff-nudge.py"


def commands(settings, home, drop_nudge=False):
    """Multiset of (event, matcher, command) with HOME replaced by <H>."""
    c = collections.Counter()
    for ev, groups in settings.get("hooks", {}).items():
        for g in groups:
            for h in g.get("hooks", []):
                cmd = h.get("command", "").replace(home, "<H>")
                if drop_nudge and NUDGE in cmd:
                    continue
                c[(ev, g.get("matcher"), cmd)] += 1
    return c


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="nn-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self.hooks = os.path.join(self.home, ".claude", "hooks")
        self.sp = os.path.join(self.home, ".claude", "settings.json")

    def install(self, *args):
        r = run_install(self.home, *args)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.wait_first_index()
        return r

    def wait_first_index(self):
        log = os.path.join(self.home, ".local", "state", "claude-handoffs", "recall", "index-all.log")
        end = time.time() + 20
        while time.time() < end and not (os.path.exists(log) and os.path.getsize(log) > 0):
            time.sleep(0.2)
        time.sleep(0.5)

    def settings(self):
        with open(self.sp) as f:
            return json.load(f)

    def check(self):
        r = subprocess.run([sys.executable, os.path.join(self.hooks, "postcompact-inject.py"), "--check"],
                           input="{}", capture_output=True, text=True, timeout=30,
                           env={"HOME": self.home, "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8"})
        self.assertEqual(r.returncode, 0, r.stderr)
        # F52.b: a fresh temp HOME has no cleanupPeriodDays, so --check adds that one line. It is not under test here.
        return "".join(l for l in r.stdout.splitlines(True) if not l.startswith("HANDOFF CHECK: Claude Code deletes chat"))

    def assert_no_nudge_but_all_else(self):
        self.assertFalse(os.path.exists(os.path.join(self.hooks, NUDGE)))
        s = self.settings()
        self.assertFalse(any(NUDGE in c[2] for c in commands(s, self.home)), "nudge entry still in settings.json")
        plain = commands(installed_settings("<H>"), "<H>", drop_nudge=True)  # plain install, HOME replaced by <H>
        self.assertEqual(commands(s, self.home), plain)
        for ev in ("PreCompact", "SessionEnd"):
            self.assertTrue(s["hooks"].get(ev), ev)
        matchers = {g.get("matcher") for g in s["hooks"]["SessionStart"]}
        self.assertTrue({"compact", "startup", "resume"} <= matchers, matchers)
        self.assertEqual(self.check(), "")


class Fresh(Base):
    def test_ac208_no_nudge_file_or_entry(self):
        self.install("--no-nightly", "--no-nudge")
        self.assert_no_nudge_but_all_else()

    def test_ac208_plain_install_has_nudge(self):
        # control: the plain install does carry the nudge, so the checks above mean something
        self.install("--no-nightly")
        self.assertTrue(os.path.isfile(os.path.join(self.hooks, NUDGE)))
        self.assertTrue(any(NUDGE in c[2] for c in commands(self.settings(), self.home)))


class Upgrade(Base):
    def test_ac209_plain_then_no_nudge(self):
        self.install("--no-nightly")
        self.assertTrue(os.path.isfile(os.path.join(self.hooks, NUDGE)))
        self.install("--no-nightly", "--no-nudge")
        self.assert_no_nudge_but_all_else()


class Uninstall(Base):
    def test_ac210_no_nudge_then_uninstall_restores_settings(self):
        os.makedirs(os.path.dirname(self.sp))
        before = {"hooks": {"PreCompact": [{"hooks": [{"type": "command", "command": "echo other"}]}]},
                  "permissions": {"allow": ["Bash(ls:*)"]}, "env": {"FOO": "1"}}
        json.dump(before, open(self.sp, "w"))
        self.install("--no-nightly", "--no-nudge")
        r = run_uninstall(self.home)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.settings(), before)


class DryRun(Base):
    def test_ac211_dry_run_changes_nothing(self):
        os.makedirs(os.path.dirname(self.sp))
        text = json.dumps({"permissions": {"allow": ["Bash(ls:*)"]}}, indent=1) + "\n"
        open(self.sp, "w").write(text)
        r = run_install(self.home, "--dry-run", "--no-nudge")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(open(self.sp, "rb").read(), text.encode())
        created = os.listdir(self.hooks) if os.path.isdir(self.hooks) else []
        self.assertEqual(created, [], "files created under ~/.claude/hooks/")


class Help(unittest.TestCase):
    def test_help_lists_no_nudge(self):
        from helpers import INSTALL_SH
        r = subprocess.run(["bash", INSTALL_SH, "--help"], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0)
        self.assertIn("--no-nudge", r.stdout)


if __name__ == "__main__":
    unittest.main()
