"""F52 Protect the store: ACs 218-228 of docs/spec.md. Code-blind: written from the spec only.
Part 1: `postcompact-inject.py --check` and the installer flag `--keep-transcripts` (temp HOME,
LOSSLESS_HANDOFF_NO_LAUNCHCTL=1, RECALL_EMBED_URL on a closed port, stdin not a terminal).
Part 2: the handoff file cleanup of `precompact-handoff.py` (HANDOFF_RETENTION_DAYS)."""
import json, os, shutil, subprocess, sys, tempfile, time, unittest

from helpers import HookCase, POST, run_install, run_uninstall, user, asst

MANAGED = "/Library/Application Support/ClaudeCode/managed-settings.json"


def line(n):
    return ('HANDOFF CHECK: Claude Code deletes chat transcripts after %s days (cleanupPeriodDays), so recall loses '
            'older messages. Set "cleanupPeriodDays": 365 in ~/.claude/settings.json, or run '
            './install.sh --keep-transcripts.' % n)


MARK = "HANDOFF CHECK: Claude Code deletes chat transcripts"


def managed_sets_value():
    """True if the real managed settings file is readable and has the key. Then the tests cannot control the value."""
    try:
        with open(MANAGED) as f:
            return "cleanupPeriodDays" in json.load(f)
    except Exception:
        return False


class Base(unittest.TestCase):
    def setUp(self):
        if managed_sets_value():
            self.skipTest("the managed settings file on this machine sets cleanupPeriodDays; the spec has no test "
                          "override for its path, so the value cannot be controlled")
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="f52-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(os.path.join(self.home, ".claude"))
        self.sp = os.path.join(self.home, ".claude", "settings.json")
        self.hooks = os.path.join(self.home, ".claude", "hooks")

    def write_settings(self, obj=None, raw=None):
        with open(self.sp, "w") as f:
            f.write(raw if raw is not None else json.dumps(obj))

    def read_bytes(self):
        with open(self.sp, "rb") as f:
            return f.read()

    def settings(self):
        return json.loads(self.read_bytes())

    def wait_index(self):
        log = os.path.join(self.home, ".local", "state", "claude-handoffs", "recall", "index-all.log")
        end = time.time() + 20
        while time.time() < end and not (os.path.exists(log) and os.path.getsize(log) > 0):
            time.sleep(0.2)
        time.sleep(0.5)

    def install(self, *args, expect=0):
        r = run_install(self.home, "--no-nightly", *args)
        self.assertEqual(r.returncode, expect, r.stdout + r.stderr)
        if expect == 0 and "--dry-run" not in args:
            self.wait_index()
        return r

    def uninstall(self):
        r = run_uninstall(self.home)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r


class Check(Base):
    """--check needs the hooks of the repo and a temp HOME only (no install)."""

    def check(self):
        r = subprocess.run([sys.executable, POST, "--check"], input="{}", capture_output=True, text=True, timeout=30,
                           env={"HOME": self.home, "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                                "LANG": "C.UTF-8", "RECALL_EMBED_URL": "http://127.0.0.1:9"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("Traceback", r.stdout + r.stderr)
        return r.stdout

    def assert_warns(self, n):
        out = self.check()
        lines = out.splitlines()
        self.assertEqual([l for l in lines if l.startswith(MARK)], [line(n)], out)

    def assert_silent(self):
        self.assertNotIn(MARK, self.check())

    def test_ac218_value_30(self):
        self.write_settings({"cleanupPeriodDays": 30})
        self.assert_warns(30)

    def test_ac219_no_key(self):
        self.write_settings({"theme": "dark"})
        self.assert_warns(30)

    def test_ac219_no_settings_file(self):
        self.assertFalse(os.path.exists(self.sp))
        self.assert_warns(30)

    def test_ac220_value_90(self):
        self.write_settings({"cleanupPeriodDays": 90})
        self.assert_silent()

    def test_ac220_value_365(self):
        self.write_settings({"cleanupPeriodDays": 365})
        self.assert_silent()

    def test_ac220_partner_90_silent_but_30_warns(self):
        # positive partner: in the same HOME, 90 is silent and 30 warns
        self.write_settings({"cleanupPeriodDays": 90})
        self.assert_silent()
        self.write_settings({"cleanupPeriodDays": 30})
        self.assert_warns(30)

    def test_ac220_value_89_warns(self):
        # boundary: the floor is 90, so 89 is below it
        self.write_settings({"cleanupPeriodDays": 89})
        self.assert_warns(89)

    def test_ac221_value_string(self):
        self.write_settings({"cleanupPeriodDays": "abc"})
        self.assert_warns(30)

    def test_ac221_value_negative(self):
        self.write_settings({"cleanupPeriodDays": -5})
        self.assert_warns(30)

    def test_ac221_invalid_json(self):
        self.write_settings(raw="{this is not json")
        self.assert_warns(30)

    def test_ac218_managed_settings_branch(self):
        self.skipTest("the spec defines no test override for the managed settings path "
                      "(/Library/Application Support/ClaudeCode/managed-settings.json), so the managed branch of "
                      "F52.a and the installer rule 'do not override a managed value' cannot be tested safely")


class Installer(Base):
    def seed(self, value=30):
        s = {"cleanupPeriodDays": value, "env": {"FOO": "1"}, "permissions": {"allow": ["Bash(ls:*)"]}}
        self.write_settings(s)
        return s

    def assert_others_kept(self):
        s = self.settings()
        self.assertEqual(s["env"].get("FOO"), "1")
        self.assertIn("Bash(ls:*)", s["permissions"]["allow"])

    def test_ac222_raises_to_365_and_is_idempotent(self):
        self.seed(30)
        self.install("--keep-transcripts")
        self.assertEqual(self.settings()["cleanupPeriodDays"], 365)
        self.assert_others_kept()
        after = self.read_bytes()
        self.install("--keep-transcripts")
        self.assertEqual(self.read_bytes(), after)

    def test_ac222_sets_value_when_key_missing(self):
        self.write_settings({"env": {"FOO": "1"}, "permissions": {"allow": ["Bash(ls:*)"]}})
        self.install("--keep-transcripts")
        self.assertEqual(self.settings()["cleanupPeriodDays"], 365)
        self.assert_others_kept()

    def test_ac223_never_lowers(self):
        self.seed(400)
        self.install("--keep-transcripts=120")
        self.assertEqual(self.settings()["cleanupPeriodDays"], 400)
        self.assert_others_kept()

    def test_ac222_custom_days_raises(self):
        self.seed(30)
        self.install("--keep-transcripts=120")
        self.assertEqual(self.settings()["cleanupPeriodDays"], 120)

    def test_ac224_days_below_90(self):
        self.seed(30)
        before = self.read_bytes()
        self.install("--keep-transcripts=10", expect=2)
        self.assertEqual(self.read_bytes(), before)
        self.assertFalse(os.path.exists(self.hooks), "usage error must change nothing")

    def test_ac224_days_not_integer(self):
        self.seed(30)
        before = self.read_bytes()
        self.install("--keep-transcripts=abc", expect=2)
        self.assertEqual(self.read_bytes(), before)
        self.assertFalse(os.path.exists(self.hooks), "usage error must change nothing")

    def test_ac224_partner_valid_value_works_in_same_setup(self):
        self.seed(30)
        self.install("--keep-transcripts=10", expect=2)
        self.install("--keep-transcripts=120")
        self.assertEqual(self.settings()["cleanupPeriodDays"], 120)
        self.assert_others_kept()

    def test_ac225_dry_run(self):
        self.seed(30)
        before = self.read_bytes()
        r = self.install("--keep-transcripts", "--dry-run")
        self.assertEqual(self.read_bytes(), before)
        self.assertIn("cleanupPeriodDays", r.stdout + r.stderr)

    def test_ac226_non_interactive_no_flag(self):
        self.seed(30)
        r = self.install()  # run_install gives stdin=DEVNULL: not a terminal
        self.assertEqual(self.settings()["cleanupPeriodDays"], 30)
        self.assert_others_kept()
        self.assertIn(line(30), r.stdout + r.stderr)

    def test_ac226_no_warning_when_value_is_high(self):
        self.seed(365)
        r = self.install()
        self.assertEqual(self.settings()["cleanupPeriodDays"], 365)
        self.assertNotIn(MARK, r.stdout + r.stderr)

    def test_ac227_uninstall_keeps_value(self):
        self.seed(30)
        self.install("--keep-transcripts")
        r = self.uninstall()
        self.assertEqual(self.settings()["cleanupPeriodDays"], 365)
        self.assertIn("cleanupPeriodDays was left at 365", r.stdout + r.stderr)

    def test_ac227_uninstall_silent_when_installer_did_not_raise(self):
        self.seed(365)
        self.install()
        r = self.uninstall()
        self.assertEqual(self.settings()["cleanupPeriodDays"], 365)
        self.assertNotIn("cleanupPeriodDays was left at", r.stdout + r.stderr)


DAY = 86400


class Retention(HookCase):
    def setUp(self):
        super().setUp()
        os.makedirs(self.hd, exist_ok=True)

    def put(self, name, age_days, body="x\n"):
        p = os.path.join(self.hd, name)
        with open(p, "w") as f:
            f.write(body)
        t = time.time() - age_days * DAY
        os.utime(p, (t, t))
        return p

    def run_once(self, extra=None):
        self.write_transcript([user("Please remember that the retention rule is important for this test."),
                               asst("Understood, I will keep it in mind.")])
        r = self.run_pre(self.payload("S"), extra=extra)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_ac228_default_retention(self):
        p20 = self.put("old20.md", 20)
        p400 = self.put("old400.md", 400)
        self.run_once()
        self.assertTrue(os.path.exists(p20))
        self.assertFalse(os.path.exists(p400))

    def test_ac228_zero_keeps_forever(self):
        p20 = self.put("old20.md", 20)
        p400 = self.put("old400.md", 400)
        self.run_once({"HANDOFF_RETENTION_DAYS": "0"})
        self.assertTrue(os.path.exists(p20))
        self.assertTrue(os.path.exists(p400))

    def test_ac228_invalid_value_counts_as_365(self):
        p20 = self.put("old20.md", 20)
        p400 = self.put("old400.md", 400)
        self.run_once({"HANDOFF_RETENTION_DAYS": "abc"})
        self.assertTrue(os.path.exists(p20))
        self.assertFalse(os.path.exists(p400))

    def test_ac228_custom_value(self):
        p20 = self.put("old20.md", 20)
        p5 = self.put("old5.md", 5)
        self.run_once({"HANDOFF_RETENTION_DAYS": "10"})
        self.assertFalse(os.path.exists(p20))
        self.assertTrue(os.path.exists(p5))

    def test_ac228_pending_json_keeps_14_day_rule(self):
        pend20 = self.put("Z-pending.json", 20, "{}")
        pend5 = self.put("Y-pending.json", 5, "{}")
        self.run_once()
        self.assertFalse(os.path.exists(pend20))
        self.assertTrue(os.path.exists(pend5))

    def test_ac228_pending_json_removed_even_with_retention_zero(self):
        pend20 = self.put("Z-pending.json", 20, "{}")
        self.run_once({"HANDOFF_RETENTION_DAYS": "0"})
        self.assertFalse(os.path.exists(pend20))

    def test_ac228_degraded_and_health_json_keep_14_day_rule(self):
        d20 = self.put("Q-degraded.json", 20, "{}")
        h20 = self.put("Q-last-health.json", 20, "{}")
        self.run_once()
        self.assertFalse(os.path.exists(d20))
        self.assertFalse(os.path.exists(h20))

    def test_ac228_projects_folder_untouched(self):
        proj = os.path.join(self.hd, "projects")
        os.makedirs(proj, exist_ok=True)
        f = os.path.join(proj, "ledger.md")
        with open(f, "w") as fh:
            fh.write("keep\n")
        t = time.time() - 800 * DAY
        os.utime(f, (t, t))
        self.run_once()
        self.assertTrue(os.path.exists(f))


if __name__ == "__main__":
    unittest.main()
