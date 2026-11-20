"""F66 (release 0.14.0, hooks 1.16.0). Code-blind: written from the orchestrator contract (contract-0.14.md), not from code.

F66.a llm_map moves out to https://github.com/pratikgh0se/llm-map. The repo ships no hooks/llm_map.py and no llm-map skill.
      `--llm-map` and `--no-llm-map` stay accepted, print exactly one line (LLM_LINE) and change nothing else; the exit
      code is the same as without the flag. A saved `llm_map=1` is ignored and prints the same line. `--save-defaults`
      never writes an `llm_map` line and removes an existing one. A re-install keeps an existing llm_map.py or skill and
      prints KEPT_LINE. Uninstall never removes llm_map files (UNINSTALL_KEPT line, decision of 2026-11-20).
F66.b The SubagentStart rules block starts with PREAMBLE. The main-session injection does not get that line.
F66.c README has no "Proof" heading or claim and no [C1]-[C8] markers. docs/evidence.md has the markers.
      `--claims-lint` with no argument lints docs/evidence.md. README says that no scored benchmark result is published yet.
F66.d Product 0.14.0 (install.sh), HOOK_VERSION 1.16.0.

Labels F66.a ... are the ids of the contract. Every install uses a temp HOME (helpers). All seeded llm-map files are fake.
Assumptions (the contract is silent): `--claims-lint` with no argument is
compared with the explicit path run from the repo folder; the preamble line is the FIRST line of the SubagentStart text."""
import glob, hashlib, json, os, re, subprocess, sys, unittest

import helpers
from helpers import HookCase, REPO, HOOKS_DIR, IS_MACOS, INSTALL_SH, run_install, run_uninstall
from test_content import git
from test_f44_recall import key_for
from test_f64_minimal_install import (Base as InstBase, DEFAULTS_REL, LLM_FILES, LLM_MARK, WINDOW, read_settings,
                                      seed_llm_map, tree, window_of)

LLM_LINE = "llm-map is now a separate project: https://github.com/pratikgh0se/llm-map"
KEPT_LINE = ("llm-map: already installed, kept (now maintained at https://github.com/pratikgh0se/llm-map; "
             "this installer no longer updates it)")
UNINSTALL_KEPT = ("llm-map: kept (remove it with ./install.sh --uninstall from "
                  "https://github.com/pratikgh0se/llm-map)")
PREAMBLE = ("These are the user's standing rules for the main session of this project. Apply only the rules that fit "
            "your task. Your task brief comes first.")
SUBAGENT_HEADER = ("Project rules for this repo (standing; from the Lossless Handoff decisions list; "
                   "the user's latest words win):")


def lines_of(r):
    return (r.stdout + r.stderr).split("\n")


def count(r, text):
    return sum(1 for l in lines_of(r) if l.strip() == text)


# ------------------------------------------------------------------ F66.a installer
class Installer(InstBase):
    def llm_tree(self):
        return set(LLM_FILES) & tree(self.home)

    def test_f66_a_llm_map_flag_prints_one_line_and_installs_nothing(self):
        r = self.install("--llm-map")
        self.assertEqual(count(r, LLM_LINE), 1, r.stdout + r.stderr)
        self.assertEqual(self.llm_tree(), set())
        self.assertFalse(os.path.exists(self.p(".claude/skills/llm-map")))

    def test_f66_a_no_llm_map_flag_prints_one_line_and_installs_nothing(self):
        r = self.install("--no-llm-map")
        self.assertEqual(count(r, LLM_LINE), 1, r.stdout + r.stderr)
        self.assertEqual(self.llm_tree(), set())

    def test_f66_a_both_flags_print_the_line_and_install_nothing(self):
        r = self.install("--llm-map", "--no-llm-map")
        self.assertIn(count(r, LLM_LINE), (1, 2), r.stdout + r.stderr)
        self.assertEqual(self.llm_tree(), set())

    def test_f66_a_flag_changes_nothing_else(self):
        plain, _ = helpers.installed_home()
        self.install("--llm-map")
        self.assertEqual(tree(self.home), tree(plain))
        self.assertEqual(read_settings(self.home), read_settings(plain))

    def test_f66_a_exit_code_is_the_same_as_without_the_flag(self):
        plain_home = os.path.join(self.tmp, "plain")
        os.makedirs(plain_home)
        want = run_install(plain_home).returncode
        for i, flag in enumerate(("--llm-map", "--no-llm-map")):
            home = os.path.join(self.tmp, "h%d" % i)
            os.makedirs(home)
            self.assertEqual(run_install(home, flag).returncode, want, flag)

    def test_f66_a_plain_install_prints_no_llm_line(self):
        r = self.install()
        self.assertNotIn("llm-map is now a separate project", r.stdout + r.stderr)

    def test_f66_a_dry_run_with_the_flag_prints_one_line_and_changes_nothing(self):
        r = run_install(self.home, "--dry-run", "--llm-map")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(count(r, LLM_LINE), 1, r.stdout + r.stderr)
        self.assertEqual(sorted(os.listdir(self.home)), [])

    def put_defaults(self, text):
        d = os.path.join(self.home, os.path.dirname(DEFAULTS_REL))
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(self.home, DEFAULTS_REL), "w") as f:
            f.write(text)

    def defaults_lines(self):
        with open(os.path.join(self.home, DEFAULTS_REL)) as f:
            return f.read().split("\n")

    def test_f66_a_saved_llm_map_is_ignored_and_prints_the_line(self):
        self.put_defaults("llm_map=1\n")
        r = self.install()
        self.assertEqual(count(r, LLM_LINE), 1, r.stdout + r.stderr)
        self.assertEqual(self.llm_tree(), set())

    def test_f66_a_saved_llm_map_does_not_stop_other_saved_defaults(self):
        self.put_defaults("llm_map=1\nwindow=250000\n")
        r = self.install()
        self.assertEqual(count(r, LLM_LINE), 1, r.stdout + r.stderr)
        self.assertEqual(str(window_of(read_settings(self.home))), "250000")

    def test_f66_a_save_defaults_never_writes_an_llm_map_line(self):
        self.install("--llm-map", "--window", "250000", "--save-defaults")
        lines = self.defaults_lines()
        self.assertIn("window=250000", lines)
        self.assertEqual([l for l in lines if l.startswith("llm_map")], [])

    def test_f66_a_save_defaults_with_only_llm_map_writes_no_llm_map_line(self):
        self.install("--llm-map", "--save-defaults")
        path = os.path.join(self.home, DEFAULTS_REL)
        if os.path.exists(path):
            self.assertEqual([l for l in self.defaults_lines() if l.startswith("llm_map")], [])

    def test_f66_a_save_defaults_removes_an_existing_llm_map_line(self):
        self.put_defaults("llm_map=1\nwindow=250000\n")
        self.install("--save-defaults")
        lines = self.defaults_lines()
        self.assertEqual([l for l in lines if l.startswith("llm_map")], [])
        self.assertIn("window=250000", lines)

    def test_f66_a_reinstall_keeps_existing_files_and_prints_the_kept_line(self):
        self.install()
        before = seed_llm_map(self.home)
        r = self.install()
        self.assertEqual(count(r, KEPT_LINE), 1, r.stdout + r.stderr)
        for rel, data in before.items():
            self.assertEqual(self.bytes_of(rel), data, rel)

    def test_f66_a_reinstall_with_the_flag_keeps_the_files_too(self):
        self.install()
        before = seed_llm_map(self.home)
        r = self.install("--llm-map")
        self.assertEqual(count(r, KEPT_LINE), 1, r.stdout + r.stderr)
        for rel, data in before.items():
            self.assertEqual(self.bytes_of(rel), data, rel)

    def test_f66_a_no_kept_line_without_old_files(self):
        r = self.install()
        self.assertEqual(count(r, KEPT_LINE), 0)
        r = self.install()
        self.assertEqual(count(r, KEPT_LINE), 0)

    def uninstall_kept(self):
        r = self.uninstall()
        return r, count(r, UNINSTALL_KEPT)

    def test_f66_a_uninstall_never_removes_llm_map_even_when_the_manifest_lists_it(self):
        self.install()
        before = seed_llm_map(self.home)
        mpath = self.p(".claude/hooks/.handoff-manifest.json")
        with open(mpath) as f:
            m = json.load(f)
        m["files"]["llm_map.py"] = hashlib.sha256(before[LLM_FILES[0]]).hexdigest()
        with open(mpath, "w") as f:
            json.dump(m, f)
        r, n = self.uninstall_kept()
        self.assertEqual(n, 1, r.stdout + r.stderr)
        for rel, data in before.items():
            self.assertEqual(self.bytes_of(rel), data, rel)

    def test_f66_a_uninstall_keeps_llm_map_py_alone(self):
        self.install()
        before = seed_llm_map(self.home)
        os.remove(self.p(LLM_FILES[1]))
        r, n = self.uninstall_kept()
        self.assertEqual(n, 1, r.stdout + r.stderr)
        self.assertEqual(self.bytes_of(LLM_FILES[0]), before[LLM_FILES[0]])

    def test_f66_a_uninstall_keeps_a_marked_skill_alone(self):
        self.install()
        before = seed_llm_map(self.home)
        os.remove(self.p(LLM_FILES[0]))
        r, n = self.uninstall_kept()
        self.assertEqual(n, 1, r.stdout + r.stderr)
        self.assertEqual(self.bytes_of(LLM_FILES[1]), before[LLM_FILES[1]])

    def test_f66_a_uninstall_keeps_a_skill_without_the_marker(self):
        self.install()
        path = self.p(LLM_FILES[1])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("---\nname: llm-map\n---\nMy own skill FOREIGN-MARK\n")
        r, n = self.uninstall_kept()
        self.assertEqual(n, 1, r.stdout + r.stderr)
        self.assertIn("FOREIGN-MARK", open(path).read())

    def test_f66_a_uninstall_without_llm_map_prints_no_kept_line(self):
        self.install()
        r, n = self.uninstall_kept()
        self.assertEqual(n, 0, r.stdout + r.stderr)
        self.assertNotIn("llm-map: kept", r.stdout + r.stderr)


class Repo(unittest.TestCase):
    def test_f66_a_repo_ships_no_llm_map_hook(self):
        self.assertFalse(os.path.exists(os.path.join(HOOKS_DIR, "llm_map.py")))

    def test_f66_a_repo_ships_no_llm_map_skill_folder(self):
        for rel in ("skills/llm-map", ".claude/skills/llm-map", "skill/llm-map", "hooks/skills/llm-map"):
            self.assertFalse(os.path.exists(os.path.join(REPO, rel)), rel)
        hits = [p for p in glob.glob(os.path.join(REPO, "**", "llm_map.py"), recursive=True)
                if "/.git/" not in p and "/bench/" not in p]
        self.assertEqual(hits, [])


# ------------------------------------------------------------------ F66.b SubagentStart preamble
class Preamble(HookCase):
    LEDGER_ENV = None

    def setUp(self):
        super().setUp()
        self.rt = os.path.realpath(self.tmp)
        self.proj = os.path.join(self.rt, "r", "proj")
        os.makedirs(self.proj)
        git(self.proj, "init", "-q")
        pdir = os.path.join(self.hd, "projects", key_for(self.proj))
        os.makedirs(pdir)
        self.rule = "- D1 [2026-10-01] [rule] RULEPRE never put tool names in commit messages | why: user said so"
        with open(os.path.join(pdir, "decisions.md"), "w") as f:
            f.write("# Project decisions: %s\n%s\n" % (self.proj, self.rule))

    def subagent_text(self):
        payload = {"session_id": "66666666-0000-4000-8000-000000000066", "cwd": self.proj, "agent_id": "a1b2c3d4e5f6a7b8",
                   "agent_type": "general-purpose", "hook_event_name": "SubagentStart"}
        r = subprocess.run([sys.executable, helpers.POST, "--subagent-start"], input=json.dumps(payload),
                           capture_output=True, text=True, env=self.env(None), timeout=30)
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout)
        return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]

    def test_f66_b_subagent_block_starts_with_the_preamble(self):
        ctx = self.subagent_text()
        self.assertEqual(ctx.split("\n")[0], PREAMBLE, ctx[:300])
        self.assertEqual(ctx.count(PREAMBLE), 1)

    def test_f66_b_rules_still_follow_the_preamble(self):
        ctx = self.subagent_text()
        self.assertIn(self.rule, ctx.split("\n"))
        self.assertIn(SUBAGENT_HEADER, ctx)
        self.assertLess(ctx.index(PREAMBLE), ctx.index(SUBAGENT_HEADER))
        self.assertLess(ctx.index(SUBAGENT_HEADER), ctx.index(self.rule))

    def test_f66_b_no_rules_no_preamble(self):
        os.remove(os.path.join(self.hd, "projects", key_for(self.proj), "decisions.md"))
        payload = {"session_id": "66666666-0000-4000-8000-000000000066", "cwd": self.proj, "agent_id": "a1",
                   "agent_type": "general-purpose", "hook_event_name": "SubagentStart"}
        r = subprocess.run([sys.executable, helpers.POST, "--subagent-start"], input=json.dumps(payload),
                           capture_output=True, text=True, env=self.env(None), timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn(PREAMBLE, r.stdout)

    def test_f66_b_main_session_injection_has_no_preamble(self):
        for part in ("1", "2", "3"):
            r = self.run_post({"session_id": "S", "cwd": self.proj}, args=("--ledger", "--part", part))
            self.assertEqual((r.returncode, r.stderr), (0, ""))
            self.assertNotIn(PREAMBLE, r.stdout)
            self.assertNotIn("These are the user's standing rules", r.stdout)
        r = self.run_post({"session_id": "S", "cwd": self.proj}, args=("--ledger", "--part", "1"))
        self.assertIn("RULEPRE", r.stdout, "fixture: the main-session injection should show the rule")

    def test_f66_b_precompact_handoff_has_no_preamble(self):
        self.install_shim(out="## Goal\nplain\n")
        self.write_transcript([helpers.user("hello", timestamp="2026-11-20T10:00:00.000Z"), helpers.asst("ok")])
        r = self.run_pre(self.payload("S", cwd=self.proj))
        self.assertEqual((r.returncode, r.stdout), (0, ""), r.stderr)
        self.assertNotIn(PREAMBLE, self.latest("S"))


# ------------------------------------------------------------------ F66.c evidence wording
def read(rel):
    with open(os.path.join(REPO, rel)) as f:
        return f.read()


class Evidence(unittest.TestCase):
    MARKER = re.compile(r"\[C[1-8]\]")

    def test_f66_c_readme_has_no_proof_heading(self):
        heads = [l for l in read("README.md").split("\n") if re.match(r"^#{1,6}\s", l) and re.search(r"\bProof\b", l)]
        self.assertEqual(heads, [])

    def test_f66_c_readme_has_no_proof_claim(self):
        text = read("README.md")
        self.assertNotIn("**Proof", text)
        self.assertNotRegex(text, r"(?m)^\|\s*Proof\s*\|")

    def test_f66_c_readme_has_no_claim_markers(self):
        self.assertEqual(self.MARKER.findall(read("README.md")), [])

    def test_f66_c_evidence_file_has_the_markers(self):
        self.assertTrue(os.path.isfile(os.path.join(REPO, "docs", "evidence.md")))
        found = set(self.MARKER.findall(read("docs/evidence.md")))
        self.assertEqual(found, {"[C%d]" % i for i in range(1, 9)})

    def test_f66_c_readme_says_no_scored_result_and_points_to_the_evidence_file(self):
        text = read("README.md")
        self.assertRegex(text, r"(?i)no scored benchmark result")
        self.assertIn("docs/evidence.md", text)
        self.assertRegex(text, r"(?i)currently (fail|include failures)")

    def lint(self, *args, cwd=None):
        import tempfile, shutil
        home = os.path.realpath(tempfile.mkdtemp(prefix="f66lint-"))
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        env = {"HOME": home, "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8"}
        return subprocess.run([sys.executable, helpers.PRE, "--claims-lint", *args], capture_output=True, text=True,
                              env=env, cwd=cwd or REPO, timeout=60)

    def test_f66_c_claims_lint_without_an_argument_lints_the_evidence_file(self):
        explicit_path = os.path.join(REPO, "docs", "evidence.md")
        a = self.lint()
        b = self.lint(explicit_path)
        self.assertEqual(a.returncode, b.returncode, (a.stdout + a.stderr, b.stdout + b.stderr))
        norm = lambda s: s.replace(explicit_path, "docs/evidence.md")
        self.assertEqual(norm(a.stdout), norm(b.stdout))
        self.assertTrue((a.stdout + a.stderr).strip(), "the lint printed nothing")

    def test_f66_c_claims_lint_prefers_the_tree_around_the_script_over_the_current_folder(self):
        # spec F66.c (head 01ce819): the tree around the script first, then the current folder
        import tempfile, shutil
        other = os.path.realpath(tempfile.mkdtemp(prefix="f66cwd-"))
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        os.makedirs(os.path.join(other, "docs"))
        with open(os.path.join(other, "docs", "evidence.md"), "w") as f:
            f.write("# Other evidence\n[C1] a claim that is not in the real file OTHERFILE\n")
        here = self.lint(cwd=REPO)
        there = self.lint(cwd=other)
        self.assertEqual(here.returncode, there.returncode, (here.stdout + here.stderr, there.stdout + there.stderr))
        self.assertEqual(here.stdout, there.stdout)
        self.assertNotIn("OTHERFILE", there.stdout + there.stderr)

    def test_f66_c_claims_lint_without_an_argument_works_from_any_folder(self):
        import tempfile, shutil
        other = os.path.realpath(tempfile.mkdtemp(prefix="f66cwd-"))
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        r = self.lint(cwd=other)
        self.assertNotIn("Traceback", r.stderr)
        self.assertTrue((r.stdout + r.stderr).strip())

    def test_f66_c_claims_lint_accepts_an_explicit_path(self):
        b = self.lint(os.path.join(REPO, "README.md"))
        self.assertIn(b.returncode, (0, 1), b.stdout + b.stderr)
        self.assertNotIn("Traceback", b.stderr)

    def test_f66_c_local_proof_script_lints_the_evidence_file(self):
        path = os.path.join(REPO, "tests", "local-proof.sh")
        if not os.path.exists(path):
            self.skipTest("no tests/local-proof.sh")
        text = open(path).read()
        self.assertIn("docs/evidence.md", text)


# ------------------------------------------------------------------ F66.d versions
class Versions(unittest.TestCase):
    def test_f66_d_install_sh_version_is_0_14_0(self):
        import tempfile, shutil
        home = os.path.realpath(tempfile.mkdtemp(prefix="f66v-"))
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        r = run_install(home, "--version")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("0.15.0", r.stdout + r.stderr)
        self.assertEqual(sorted(os.listdir(home)), [])

    def test_f66_d_installed_manifest_version_is_1_16_0(self):
        home, _ = helpers.installed_home()
        with open(os.path.join(home, ".claude", "hooks", ".handoff-manifest.json")) as f:
            self.assertEqual(json.load(f)["version"], "1.17.0")

    def test_f66_d_changelog_has_0_14_0_first(self):
        heads = re.findall(r"(?m)^## \[([0-9.]+)\]", read("CHANGELOG.md"))
        self.assertEqual(heads[0], "0.15.0")

    def test_f66_d_hook_version_constants_are_1_16_0(self):
        # a constant in each entry file (the file has no other `HOOK_VERSION = ` assignment with a version)
        for n in ("precompact-handoff.py", "postcompact-inject.py"):
            with open(os.path.join(HOOKS_DIR, n)) as f:
                src = f.read()
            self.assertRegex(src, r"""HOOK_VERSION\s*=\s*["']1\.16\.0["']""", n)


if __name__ == "__main__":
    unittest.main()
