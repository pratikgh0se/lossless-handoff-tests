"""F86 A check that gives correct advice (0.20.1, hooks 1.22.1). Code-blind: written from the F86 text only.
F86.a: install problems end with the installer advice, data problems never do, both classes give the two-class line.
F86.b: `--check --verbose` prints `ok:` / `problem:` lines, three `info:` lines and a last line. F86.c: the installer's last
line. F86.d: docs and the README version line. F86.e.6: the pins are in test_versions_0202.py."""
import glob, hashlib, json, os, re, subprocess, sys, tempfile, shutil, stat, time, unittest

from helpers import REPO, HOOKS_DIR, copy_hook_scripts, installed_settings, installed_home, run_install
from test_f47_proof_receipts import ProofBase, BTS
from test_f45_no_silent_miss import BOUNDARY, iso
from test_f44_recall import slug
from helpers import user

ADVICE = "Run the installer again, then restart Claude Code."
RULE = "Bash(python3 ~/.claude/hooks/recall.py:*)"


def hook_version(hooks):
    src = open(os.path.join(hooks, "precompact-handoff.py")).read()
    return re.search(r"""HOOK_VERSION\s*=\s*["']([^"']+)["']""", src).group(1)


class Fix(ProofBase):
    def setUp(self):
        super().setUp()
        self.hooks_home = os.path.join(self.home, ".claude", "hooks")
        os.makedirs(self.hooks_home)
        copy_hook_scripts(self.hooks_home)
        self.settings = os.path.join(self.home, ".claude", "settings.json")
        self.write_settings()
        self.write_manifest()
        open(os.path.join(self.hooks_home, ".recall-rules"), "w").close()

    def write_settings(self, mutate=None):
        d = dict(installed_settings(self.home), cleanupPeriodDays=365)
        if mutate:
            mutate(d)
        json.dump(d, open(self.settings, "w"))

    def write_manifest(self):
        files = {n: hashlib.sha256(open(os.path.join(self.hooks_home, n), "rb").read()).hexdigest()
                 for n in sorted(os.listdir(self.hooks_home))
                 if n.endswith(".py") and os.path.isfile(os.path.join(self.hooks_home, n))}
        json.dump({"version": hook_version(self.hooks_home), "installed_at": iso(), "files": files},
                  open(os.path.join(self.hooks_home, ".handoff-manifest.json"), "w"))

    def run_check(self, *args, cwd=None, path=None):
        env = self.env(None)
        if path is not None:
            env["PATH"] = path
        t = time.time()
        r = subprocess.run([sys.executable, os.path.join(self.hooks_home, "postcompact-inject.py"), "--check", *args],
                           input="", capture_output=True, text=True, env=env, timeout=30, cwd=cwd or self.home)
        self.elapsed = time.time() - t
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def missed(self, n=2):
        os.makedirs(self.hd, exist_ok=True)
        json.dump({"ts": iso(), "days": 2, "compactions": n + 3, "handoffs": 3, "recovered": 0, "missed": n,
                   "missed_interactive": n, "missed_headless": 0, "killed": 0, "sessions": []},
                  open(os.path.join(self.hd, "reconcile.json"), "w"))

    def failed_proof(self):
        # one verdict with one failed check, written as `--prove` writes it (F47 b); no claims run, so no claims line
        os.makedirs(self.hd, exist_ok=True)
        with open(os.path.join(self.hd, "proofs.jsonl"), "w") as f:
            f.write(json.dumps({"ts": iso(), "receipt_ts": iso(-100), "sid": "S", "agent_id": None,
                                "checks": {"lossless": "pass", "delivered": "fail"},
                                "details": {"delivered": "head not found"}}) + "\n")
        with open(os.path.join(self.hd, "proof-report.md"), "w") as f:
            f.write("proof 7d: receipts 1 · failed 1\n")


class Classes(Fix):
    def test_f86_e1_only_a_failed_proof_prints_the_data_line_without_installer_advice(self):
        self.failed_proof()
        out = self.run_check()
        self.assertEqual(out, "HANDOFF CHECK: proof failed: 1 checks; see proof-report.md.\n")
        self.assertNotIn("installer", out)
        self.assertEqual(self.run_check(), "", "shown once")

    def test_f86_a_only_missed_compactions_prints_a_data_line_without_installer_advice(self):
        self.missed(2)
        out = self.run_check()
        self.assertRegex(out, r"^HANDOFF CHECK: .*2 compactions without a handoff.*\.\n$")
        self.assertEqual(out.count("\n"), 1, out)
        self.assertNotIn("installer", out)
        self.assertNotIn("restart", out)

    def test_f86_a_only_an_install_problem_ends_with_the_installer_advice(self):
        os.remove(os.path.join(self.hooks_home, "handoff-nudge.py"))
        out = self.run_check()
        self.assertRegex(out, r"^HANDOFF CHECK: .+\. " + re.escape(ADVICE) + r"\n$")
        self.assertEqual(out.count("\n"), 1, out)
        self.assertIn("handoff-nudge.py", out)
        self.assertNotIn("Also:", out)

    def test_f86_e2_a_missing_hook_file_and_two_missed_compactions_print_the_two_class_line(self):
        os.remove(os.path.join(self.hooks_home, "handoff-nudge.py"))
        self.missed(2)
        out = self.run_check()
        m = re.match(r"^HANDOFF CHECK: (?P<inst>.+)\. " + re.escape(ADVICE) + r" Also: (?P<data>.+)\.\n$", out)
        self.assertTrue(m, out)
        self.assertEqual(out.count("\n"), 1, out)
        self.assertIn("handoff-nudge.py", m.group("inst"))
        self.assertIn("2 compactions without a handoff", m.group("data"))

    def test_f86_a_unreadable_settings_is_an_install_problem(self):
        open(self.settings, "w").write("{ not json")
        out = self.run_check()
        self.assertIn("settings.json unreadable", out)
        self.assertIn(ADVICE, out)

    def test_f86_a_a_hook_that_is_not_wired_is_an_install_problem(self):
        self.write_settings(lambda d: d["hooks"].pop("PreCompact", None))
        out = self.run_check()
        self.assertIn("PreCompact", out)
        self.assertIn(ADVICE, out)

    def test_f86_a_a_file_that_differs_from_the_manifest_is_an_install_problem(self):
        with open(os.path.join(self.hooks_home, "recall.py"), "a") as f:
            f.write("\n# changed after install\n")
        out = self.run_check()
        self.assertIn("recall.py", out)
        self.assertIn(ADVICE, out)

    def test_f86_a_a_missing_recall_py_is_an_install_problem(self):
        os.remove(os.path.join(self.hooks_home, "recall.py"))
        out = self.run_check()
        self.assertIn("recall.py", out)
        self.assertIn(ADVICE, out)

    def test_f86_e3_no_allow_rule_for_recall_is_an_install_problem_that_names_the_rule(self):
        def drop(d):
            d["permissions"]["allow"] = [a for a in d["permissions"]["allow"] if "recall.py" not in a]
        self.write_settings(drop)
        out = self.run_check()
        self.assertIn(RULE, out)
        self.assertIn(ADVICE, out)
        self.assertTrue(out.startswith("HANDOFF CHECK: "), out)

    def test_f86_a_a_failed_proof_beside_an_install_problem_uses_the_also_form(self):
        os.remove(os.path.join(self.hooks_home, "handoff-nudge.py"))
        self.failed_proof()
        out = self.run_check()
        self.assertRegex(out, r"^HANDOFF CHECK: .+\. " + re.escape(ADVICE) + r" Also: proof failed: 1 checks; see proof-report\.md\.\n$")


class Verbose(Fix):
    def test_f86_e4_a_healthy_fixture_prints_nothing_with_check(self):
        self.assertEqual(self.run_check(), "")

    def test_f86_e4_a_healthy_fixture_prints_only_ok_and_info_lines_with_verbose(self):
        out = self.run_check("--verbose")
        lines = out.rstrip("\n").split("\n")
        self.assertTrue(re.match(r"^HANDOFF CHECK: all ok \((\d+) checks\)$", lines[-1]), out)
        body = lines[:-1]
        self.assertTrue(body)
        for l in body:
            self.assertRegex(l, r"^(ok: .+|info: .+)$", out)
        self.assertEqual([l for l in body if l.startswith("problem:")], [])
        n = int(re.match(r"^HANDOFF CHECK: all ok \((\d+) checks\)$", lines[-1]).group(1))
        self.assertEqual(n, len([l for l in body if l.startswith("ok: ")]), "the count is the number of ok lines")
        self.assertLess(self.elapsed, 5)

    def test_f86_b_three_info_lines(self):
        out = self.run_check("--verbose")
        self.assertEqual(sum(1 for l in out.split("\n") if l.startswith("info: recall rule ")), 1)
        self.assertIn("info: recall rule on", out)
        self.assertEqual(sum(1 for l in out.split("\n") if l.startswith("info: claude on PATH: ")), 1)
        self.assertEqual(sum(1 for l in out.split("\n") if l.startswith("info: recall covers ")), 1)

    def test_f86_b_recall_rule_off_without_the_marker(self):
        os.remove(os.path.join(self.hooks_home, ".recall-rules"))
        self.assertIn("info: recall rule off", self.run_check("--verbose"))

    def test_f86_b_recall_covers_counts_the_sessions_of_the_current_folder(self):
        proj = os.path.join(self.tmp, "proj86")
        os.makedirs(proj)
        subprocess.run(["git", "init", "-q"], cwd=proj, check=True)
        d = os.path.join(self.home, ".claude", "projects", slug(os.path.realpath(proj)))
        os.makedirs(d)
        for i in range(2):
            sid = "86%06d-0000-4000-8000-%012d" % (i, i)
            with open(os.path.join(d, sid + ".jsonl"), "w") as f:
                f.write(json.dumps({"type": "user", "sessionId": sid, "cwd": os.path.realpath(proj), "timestamp": iso(-100 - i),
                                    "message": {"role": "user", "content": "A message long enough to count here %d" % i}}) + "\n")
        out = self.run_check("--verbose", cwd=proj)
        m = re.search(r"^info: recall covers (\d+) sessions for (.+)$", out, re.M)
        self.assertTrue(m, out)
        self.assertEqual(int(m.group(1)), 2)
        self.assertTrue(os.path.samefile(m.group(2), proj), m.group(2))

    def test_f86_b_claude_on_path_yes_and_no_and_no_model_call(self):
        shim_dir = os.path.join(self.tmp, "claude-shim")
        os.makedirs(shim_dir)
        called = os.path.join(self.tmp, "claude-called")
        shim = os.path.join(shim_dir, "claude")
        open(shim, "w").write("#!/bin/sh\necho called >> %s\nexit 0\n" % called)
        os.chmod(shim, 0o755)
        base = os.path.dirname(sys.executable) + ":/usr/bin:/bin"
        yes = self.run_check("--verbose", path=shim_dir + ":" + base)
        self.assertIn("info: claude on PATH: yes", yes)
        self.assertFalse(os.path.exists(called), "--check --verbose must not call claude")
        empty = os.path.join(self.tmp, "nopath")
        os.makedirs(empty)
        no = self.run_check("--verbose", path=empty + ":" + os.path.dirname(sys.executable))
        self.assertIn("info: claude on PATH: no", no)

    def test_f86_b_a_problem_gives_a_problem_line_and_the_f86a_line_last(self):
        os.remove(os.path.join(self.hooks_home, "handoff-nudge.py"))
        out = self.run_check("--verbose")
        lines = out.rstrip("\n").split("\n")
        self.assertTrue([l for l in lines if l.startswith("problem: ")], out)
        self.assertTrue([l for l in lines if l.startswith("ok: ")], out)
        self.assertRegex(lines[-1], r"^HANDOFF CHECK: .+\. " + re.escape(ADVICE) + r"$")
        self.assertEqual([l for l in lines if l.startswith("info: ")][:1] != [], True)

    def test_f86_b_verbose_prints_every_time_not_only_once(self):
        self.missed(2)
        a = self.run_check("--verbose")
        b = self.run_check("--verbose")
        self.assertIn("2 compactions without a handoff", a)
        self.assertEqual(a.split("\n")[-2][:14], b.split("\n")[-2][:14])


class Installer(unittest.TestCase):
    def test_f86_c_the_last_line_of_a_real_install_is_the_verbose_check(self):
        home, r = installed_home()
        last = [l for l in r.stdout.split("\n") if l.strip()][-1]
        self.assertEqual(last, "Check: python3 ~/.claude/hooks/postcompact-inject.py --check --verbose")


class Docs(unittest.TestCase):
    def read(self, *parts):
        with open(os.path.join(REPO, *parts)) as f:
            return f.read()

    def test_f86_e5_the_readme_versions_line_equals_install_sh_and_hook_version(self):
        t = self.read("README.md")
        lines = [l for l in t.split("\n") if re.search(r"(?i)current versions", l)]
        self.assertTrue(lines, 'README has no "Current versions" line')
        home = os.path.realpath(tempfile.mkdtemp(prefix="v86-"))
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        r = run_install(home, "--version")
        self.assertEqual(r.returncode, 0, r.stderr)
        product = re.search(r"\d+\.\d+\.\d+", r.stdout + r.stderr).group(0)
        hook = hook_version(HOOKS_DIR)
        for l in lines:
            self.assertIn(product, l, l)
            self.assertIn(hook, l, l)
            self.assertEqual(set(re.findall(r"\d+\.\d+\.\d+", l)), {product, hook}, l)

    def test_f86_d_troubleshooting_gives_advice_for_each_class(self):
        t = self.read("docs", "troubleshooting.md")
        self.assertIn("--check --verbose", t)
        self.assertRegex(t, r"(?i)install problem")
        self.assertRegex(t, r"(?i)data problem")
        self.assertIn("installer", t)
        self.assertRegex(t, r"(?i)proof")
        self.assertRegex(t, r"(?i)without a handoff|missed compaction")

    def test_f86_d_the_cut_handoff_line_has_counts_dates_and_the_first_cut_rule(self):
        for parts in (("README.md",), ("docs", "limitations.md")):
            t = self.read(*parts)
            with self.subTest(parts):
                cut = [l for l in t.split("\n") if re.search(r"(?i)\bcut\b", l) and re.search(r"(?i)handoff", l)]
                self.assertTrue(cut, "no line about cut handoffs")
                block = " ".join(cut)
                self.assertGreaterEqual(len(re.findall(r"\d{4}-\d\d-\d\d", block)), 2, block)
                self.assertRegex(block, r"(?i)subagent")
                self.assertRegex(block, r"(?i)main")
                self.assertRegex(t, r"(?i)only auto-extracted fact sections are cut first|auto-extracted")

    def test_f86_d_f44_5_names_a_measured_time_and_a_session_count(self):
        t = self.read("docs", "spec.md")
        m = re.search(r"(?m)^.*F44\.5.*$", t)
        self.assertTrue(m)
        start = m.start()
        block = t[start:start + 1500]
        self.assertRegex(block, r"(?i)measured")
        self.assertRegex(block, r"\d[\d,]* sessions")


if __name__ == "__main__":
    unittest.main()
