"""F83 Recall robustness and a recovery step (0.19.1, hooks 1.21.1). Code-blind: written from the F83 text of the
contract only.
F83.a: `recall.py` with no `--cwd`, run in the folder that holds `recall.py`, uses `OLDPWD` when it names another
existing folder. F83.b: a `search` that covers 0 sessions prints the wrong-folder line on stdout; the exit code is the
same as for any other search without a hit. F83.c: the recall line ends its first sentence with the new full-path text.
F83.d: the rule line text. F83.e: the MCP tool is named only when the server is registered for the user.
F83.f: the docs name one optional allow rule for ask mode and headless runs. F83.g: the version is in
test_versions_0201.py."""
import glob, json, os, re, subprocess, sys, unittest

from helpers import REPO, installed_home
from history_common import Lab as HistLab, SID1, entry, ts
from levers_common import RULE_SENTENCE, MCP_SUFFIX, RECALL_TAIL, TOOL, register_mcp, additional_context
from test_f44_recall import RECALL_LINE
from test_f68_recall_rules import Base as RulesBase

OLD_TAIL = "(then: recall.py open <id>; recall.py user --last 20)"
F83_TAIL = "(same full path for: open <id>; user --last 20; do not cd)"
ALLOW_RULE = "Bash(python3 ~/.claude/hooks/recall.py:*)"
WORD = "zebrawidget"


class Cli(HistLab):
    def setUp(self):
        super().setUp()
        self.put(SID1, [entry("user", "We chose the %s service for billing today" % WORD, "u1", ts(1)),
                        entry("assistant", "Understood, %s it is" % WORD, "a1", ts(2), parent="u1"),
                        entry("user", "an unrelated closing prompt", "u2", ts(3), parent="a1")])
        self.other = os.path.join(self.tmp, "empty-proj")
        os.makedirs(self.other)
        subprocess.run(["git", "init", "-q"], cwd=self.other, check=True)

    def run_in(self, folder, *args, oldpwd="unset"):
        e = self.env()
        e.pop("OLDPWD", None)
        if oldpwd != "unset":
            e["OLDPWD"] = oldpwd
        return subprocess.run([sys.executable, self.recall, *args], capture_output=True, text=True, env=e, cwd=folder,
                              timeout=60)

    def found(self, r):
        # a hit line holds the message text; the zero-session line only repeats the query words
        return "service for billing today" in r.stdout or "it is" in r.stdout and "Understood" in r.stdout


class FolderFallback(Cli):
    """F83.a"""

    def test_f83_a_in_the_hooks_folder_oldpwd_names_the_project(self):
        r = self.run_in(self.hooks, "search", WORD, oldpwd=self.proj)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(self.found(r), r.stdout + r.stderr)

    def test_f83_a_without_oldpwd_the_hooks_folder_is_the_project_and_finds_nothing(self):
        r = self.run_in(self.hooks, "search", WORD)
        self.assertFalse(self.found(r), r.stdout)

    def test_f83_a_an_oldpwd_that_does_not_exist_is_not_used(self):
        r = self.run_in(self.hooks, "search", WORD, oldpwd=os.path.join(self.tmp, "no-such-folder"))
        self.assertFalse(self.found(r), r.stdout)

    def test_f83_a_an_oldpwd_that_is_a_regular_file_is_not_used(self):
        f = os.path.join(self.tmp, "afile")
        open(f, "w").close()
        r = self.run_in(self.hooks, "search", WORD, oldpwd=f)
        self.assertFalse(self.found(r), r.stdout)

    def test_f83_a_an_oldpwd_that_is_the_hooks_folder_changes_nothing(self):
        r = self.run_in(self.hooks, "search", WORD, oldpwd=self.hooks)
        self.assertFalse(self.found(r), r.stdout)

    def test_f83_a_outside_the_hooks_folder_oldpwd_is_ignored(self):
        r = self.run_in(self.other, "search", WORD, oldpwd=self.proj)
        self.assertFalse(self.found(r), "the current folder is not the hooks folder: OLDPWD must not count\n" + r.stdout)
        r = self.run_in(self.proj, "search", WORD, oldpwd=self.other)
        self.assertTrue(self.found(r), "a project folder keeps working whatever OLDPWD holds\n" + r.stdout + r.stderr)

    def test_f83_a_an_explicit_cwd_wins_over_oldpwd(self):
        r = self.run_in(self.hooks, "search", WORD, "--cwd", self.other, oldpwd=self.proj)
        self.assertFalse(self.found(r), r.stdout)
        r = self.run_in(self.hooks, "search", WORD, "--cwd", self.proj, oldpwd=self.other)
        self.assertTrue(self.found(r), r.stdout + r.stderr)

    def test_f83_a_other_commands_use_the_fallback_too(self):
        r = self.run_in(self.hooks, "user", "--last", "20", oldpwd=self.proj)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("service for billing today", r.stdout)


class ZeroSessions(Cli):
    """F83.b"""
    LINE = re.compile(r'^recall\.py: no sessions for project (?P<root>.+)\. This is the wrong folder, not an empty result\. '
                      r'Run: python3 (?P<path>/\S*recall\.py) search "(?P<words>[^"]*)" --cwd (?P<cwd>\S.*)$', re.M)

    def warn(self, r):
        return self.LINE.search(r.stdout)

    def test_f83_b_a_search_with_no_sessions_prints_the_line_on_stdout(self):
        r = self.run_in(self.other, "search", "alpha beta")
        m = self.warn(r)
        self.assertTrue(m, "stdout:\n%s\nstderr:\n%s" % (r.stdout, r.stderr))
        self.assertEqual(os.path.realpath(m.group("root")), os.path.realpath(self.other))
        self.assertEqual(m.group("words"), "alpha beta")
        self.assertTrue(os.path.samefile(m.group("path"), self.recall), m.group("path"))
        self.assertEqual(m.group("cwd"), "<project folder>")  # F83.b: the text `<project folder>` stays literal

    def test_f83_b_the_text_is_the_exact_wording(self):
        r = self.run_in(self.other, "search", "alpha")
        self.assertIn("This is the wrong folder, not an empty result. Run: python3 ", r.stdout)
        self.assertIn(' search "alpha" --cwd ', r.stdout)
        self.assertIn("recall.py: no sessions for project ", r.stdout)

    def test_f83_b_the_exit_code_does_not_change(self):
        zero = self.run_in(self.other, "search", WORD + "nomatch")
        miss = self.run_in(self.proj, "search", "qqqnomatchqqq")
        self.assertFalse(self.warn(miss), miss.stdout)
        self.assertEqual(zero.returncode, miss.returncode, (zero.stdout, miss.stdout))

    def test_f83_b_no_line_when_the_search_covers_sessions_and_finds_nothing(self):
        r = self.run_in(self.proj, "search", "qqqnomatchqqq")
        self.assertNotIn("no sessions for project", r.stdout)

    def test_f83_b_no_line_when_the_search_finds_hits(self):
        r = self.run_in(self.proj, "search", WORD)
        self.assertTrue(self.found(r))
        self.assertNotIn("no sessions for project", r.stdout)

    def test_f83_b_the_hooks_folder_without_oldpwd_gets_the_line(self):
        r = self.run_in(self.hooks, "search", WORD)
        self.assertTrue(self.warn(r), r.stdout + r.stderr)

    def test_f83_b_the_line_names_the_explicit_cwd_project(self):
        r = self.run_in(self.proj, "search", "alpha", "--cwd", self.other)
        m = self.warn(r)
        self.assertTrue(m, r.stdout + r.stderr)
        self.assertEqual(os.path.realpath(m.group("root")), os.path.realpath(self.other))

    def test_f83_b_the_command_in_the_line_runs_and_finds_the_session(self):
        r = self.run_in(self.other, "search", WORD)
        m = self.warn(r)
        self.assertTrue(m, r.stdout + r.stderr)
        again = self.run_in(self.hooks, "search", WORD, "--cwd", self.proj)
        self.assertTrue(self.found(again))


class RecallLine(RulesBase):
    """F83.c and F83.d"""

    def test_f83_c_the_recall_line_has_the_new_tail_in_every_output(self):
        for name, run in (("compact", lambda: self.part1("compact")), ("startup", lambda: self.part1("startup")),
                          ("resume", lambda: self.part1("resume")), ("sub", lambda: self.sub())):
            with self.subTest(name):
                lines = self.lines_of(run())
                line = lines[self.recall_index(lines)]
                self.assertIn(RECALL_TAIL, line)
                self.assertNotIn(OLD_TAIL, line)
                self.assertNotIn(F83_TAIL, line)  # F84.d replaced the F83.c text
                self.assertNotIn("recall.py open <id>", line)
                self.assertTrue(line.startswith(RECALL_LINE), line[:300])

    def test_f83_c_the_new_tail_follows_the_search_command(self):
        lines = self.lines_of(self.part1())
        line = lines[self.recall_index(lines)]
        self.assertIn('search "<words or regex>" ' + RECALL_TAIL + ". Use it before", line)

    def test_f83_d_the_rule_line_text_and_place(self):
        self.marker()
        for name, run in (("part1", lambda: self.part1()), ("sub", lambda: self.sub())):
            with self.subTest(name):
                lines = self.lines_of(run())
                i = self.recall_index(lines)
                self.assertEqual(lines[i + 1], RULE_SENTENCE)
                self.assertEqual(lines.count(RULE_SENTENCE), 1)

    def test_f83_d_the_old_rule_text_is_gone(self):
        self.marker()
        text = additional_context(self.part1()) + additional_context(self.sub())
        self.assertNotIn("before you state an earlier number", text)
        self.assertNotIn("search before you answer", text)
        self.assertIn("A failed or denied command is not \"not found\": run the exact command again.", text)
        self.assertIn("Copy it exactly: full path, no cd.", text)

    def test_f83_d_no_marker_and_the_off_switch_keep_the_rule_line_out(self):
        self.marker(False)
        self.assertNotIn("recall rule:", additional_context(self.part1()))
        self.marker(True)
        self.assertNotIn("recall rule:", additional_context(self.part1(extra={"HANDOFF_RECALL_RULES": "0"})))
        self.assertNotIn("recall rule:", additional_context(self.sub(extra={"HANDOFF_RECALL_RULES": "0"})))


class McpRegistered(RulesBase):
    """F83.e (more cases are in test_f68_recall_rules.McpSuffix)"""
    keep = ("recall-mcp.py",)

    def test_f83_e_registered_the_recall_line_names_the_tool_and_not_unregistered(self):
        lines = self.lines_of(self.part1())
        self.assertNotIn(TOOL, lines[self.recall_index(lines)])
        register_mcp(self.home)
        lines = self.lines_of(self.part1())
        self.assertIn(TOOL, lines[self.recall_index(lines)])

    def test_f83_e_the_rule_line_is_the_f83_d_line_plus_one_sentence(self):
        self.marker()
        register_mcp(self.home)
        lines = self.lines_of(self.part1())
        i = self.recall_index(lines)
        self.assertEqual(lines[i + 1], RULE_SENTENCE + " If Bash is not allowed, call search_earlier_chat.")
        self.assertEqual(MCP_SUFFIX, " If Bash is not allowed, call search_earlier_chat.")


class Docs(unittest.TestCase):
    """F83.f"""

    def doc_text(self):
        paths = [os.path.join(REPO, "README.md")] + sorted(glob.glob(os.path.join(REPO, "docs", "*.md")))
        return {p: open(p).read() for p in paths if os.path.isfile(p)}

    def test_f83_f_the_recall_docs_name_the_allow_rule(self):
        hits = [p for p, t in self.doc_text().items() if ALLOW_RULE in t]
        self.assertTrue(hits, "no doc names %s" % ALLOW_RULE)

    def test_f83_f_the_docs_say_the_rule_runs_recall_without_a_prompt_in_ask_mode_and_headless_runs(self):
        seen = []
        for p, t in self.doc_text().items():
            for m in re.finditer(re.escape(ALLOW_RULE), t):
                near = t[max(0, m.start() - 700):m.end() + 700].lower()
                if "prompt" in near and "ask" in near and ("headless" in near or "-p" in near):
                    return
                seen.append(p)
        self.assertTrue(seen, "no doc names %s" % ALLOW_RULE)
        self.fail("no doc says the allow rule runs the recall command without a prompt in ask mode and headless runs: %s" % sorted(set(seen)))


if __name__ == "__main__":
    unittest.main()
