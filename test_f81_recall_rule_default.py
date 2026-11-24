"""F81 Recall rule on by default (0.19.0, hooks 1.21.0). Code-blind: written from the F81 text of the contract only.
F81.a: a default install writes the marker `<hooks dir>/.recall-rules`; `--no-recall-rules` skips it for that run;
`--save-defaults --no-recall-rules` saves `recall_rules=0`; a re-install never removes a marker except with
`--no-recall-rules --save-defaults` (prints `recall-rules: removed`); uninstall removes it; `--dry-run` lists it;
`HANDOFF_RECALL_RULES=0` turns the line off at run time; `--recall-rules` stays valid and changes nothing.
F81.b: the rule line text, in the same places as F68.b, directly after the recall line; none without the marker or with
HANDOFF_RECALL_RULES=0. F81.c: version 0.19.0, hooks 1.21.0; F64 lists the rule as part of the default install; README
and `install.sh --help` say the rule is on by default and how to turn it off."""
import json, os, re, shutil, tempfile, unittest

from helpers import HOOKS_DIR, REPO, installed_home, run_install, run_uninstall
from levers_common import RULE_SENTENCE, additional_context
from test_f64_minimal_install import Base as InstBase, DEFAULTS_REL, tree
from test_f68_recall_rules import Base as RulesBase

H = ".claude/hooks/"
MARKER = ".recall-rules"
LINE = (
    "- recall rule: if your context does not clearly show an earlier number, path, name, command or decision, run "
    "the recall command above before you answer. Copy it exactly: full path, no cd. A failed or denied command is "
    "not \"not found\": run the exact command again. If no search can run, say so.")


class Install(InstBase):
    def run_i(self, *args, home=None):
        r = run_install(home or self.home, *args)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.wait_first_index()
        return r

    def marker(self, home=None):
        return os.path.join(home or self.home, H + MARKER)

    def defaults(self, home=None):
        return os.path.join(home or self.home, DEFAULTS_REL)

    def test_f81_a_default_install_writes_the_marker(self):
        home, _ = installed_home()
        self.assertTrue(os.path.isfile(os.path.join(home, H + MARKER)))

    def test_f81_a_no_recall_rules_skips_the_marker_for_that_run(self):
        self.run_i("--no-recall-rules")
        self.assertFalse(os.path.exists(self.marker()))

    def test_f81_a_save_defaults_with_no_recall_rules_saves_zero_and_later_default_installs_skip_the_marker(self):
        self.run_i("--no-recall-rules", "--save-defaults")
        with open(self.defaults()) as f:
            self.assertIn("recall_rules=0", f.read().split("\n"))
        home2 = os.path.join(self.tmp, "home2")
        os.makedirs(os.path.join(home2, ".config", "lossless-handoff"))
        shutil.copy(self.defaults(), self.defaults(home2))
        self.run_i(home=home2)
        self.assertFalse(os.path.exists(self.marker(home2)))

    def test_f81_a_a_reinstall_never_removes_an_installed_marker(self):
        self.run_i()
        self.assertTrue(os.path.exists(self.marker()))
        self.run_i()
        self.assertTrue(os.path.exists(self.marker()))
        self.run_i("--no-recall-rules")
        self.assertTrue(os.path.exists(self.marker()), "--no-recall-rules alone does not remove an installed marker")

    def test_f81_a_no_recall_rules_with_save_defaults_removes_the_marker_and_says_so(self):
        self.run_i()
        r = self.run_i("--no-recall-rules", "--save-defaults")
        self.assertIn("recall-rules: removed", r.stdout + r.stderr)
        self.assertFalse(os.path.exists(self.marker()))

    def test_f81_a_removed_line_is_not_printed_when_there_was_no_marker(self):
        r = self.run_i("--no-recall-rules", "--save-defaults")
        self.assertNotIn("recall-rules: removed", r.stdout + r.stderr)

    def test_f81_a_uninstall_removes_the_marker(self):
        self.run_i()
        r = run_uninstall(self.home)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(os.path.exists(self.marker()))

    def test_f81_a_dry_run_lists_the_marker_and_writes_nothing(self):
        r = run_install(self.home, "--dry-run")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        plan = "\n".join(l for l in (r.stdout + r.stderr).split("\n") if "not selected" not in l)
        self.assertIn(MARKER, plan)
        self.assertEqual(sorted(x for x in os.listdir(self.home) if x != "Library"), [])

    def test_f81_a_dry_run_with_no_recall_rules_does_not_list_it(self):
        r = run_install(self.home, "--dry-run", "--no-recall-rules")
        plan = "\n".join(l for l in (r.stdout + r.stderr).split("\n") if "not selected" not in l)
        self.assertNotIn(MARKER, plan)

    def test_f81_a_the_recall_rules_flag_stays_valid_and_changes_nothing(self):
        base, _ = installed_home()
        r = self.run_i("--recall-rules")
        self.assertEqual(r.returncode, 0)
        self.assertTrue(os.path.exists(self.marker()))
        extra = {x for x in tree(self.home) - tree(base) if x.startswith(".claude/")}
        self.assertEqual(extra, set(), "--recall-rules adds nothing to a default install")

    def test_f81_a_the_marker_is_empty_and_is_not_a_hook(self):
        self.run_i()
        with open(self.marker()) as f:
            f.read()
        with open(os.path.join(self.home, ".claude", "settings.json")) as f:
            self.assertNotIn("recall-rules", json.dumps(json.load(f)))


class Line(RulesBase):
    """F81.b: the exact line, in the F68.b places (see test_f68_recall_rules.py for the full set of places)."""

    def test_f81_b_the_rule_line_text_is_exact(self):
        self.assertEqual(RULE_SENTENCE, LINE)

    def test_f81_b_the_session_start_output_has_the_line_directly_after_the_recall_line_with_the_marker(self):
        self.marker()
        ctx = additional_context(self.part1())
        lines = ctx.split("\n")
        self.assertEqual(lines.count(LINE), 1)
        i = lines.index(LINE)
        self.assertRegex(lines[i - 1], r"^- recall: earlier chats in this project are searchable word for word")

    def test_f81_b_no_marker_gives_no_rule_line(self):
        self.marker(False)
        self.assertNotIn("- recall rule:", additional_context(self.part1()))

    def test_f81_b_the_off_switch_gives_no_rule_line(self):
        self.marker()
        self.assertNotIn("- recall rule:", additional_context(self.part1(extra={"HANDOFF_RECALL_RULES": "0"})))

    def test_f81_b_the_subagent_start_output_has_the_line_with_the_marker_only(self):
        self.marker()
        self.assertIn(LINE, additional_context(self.sub()))
        self.assertNotIn("- recall rule:", additional_context(self.sub(extra={"HANDOFF_RECALL_RULES": "0"})))
        self.marker(False)
        self.assertNotIn("- recall rule:", self.sub())


class Docs(unittest.TestCase):
    def test_f81_c_help_says_the_rule_is_on_by_default_and_how_to_turn_it_off(self):
        home = os.path.realpath(tempfile.mkdtemp(prefix="f81-help-"))
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        r = run_install(home, "--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("--no-recall-rules", r.stdout)
        block = " ".join(l for l in r.stdout.split("\n") if "recall-rules" in l or "recall rule" in l.lower())
        self.assertRegex(block, r"(?i)\bdefault\b")

    def test_f81_c_readme_says_the_rule_is_on_by_default_and_how_to_turn_it_off(self):
        with open(os.path.join(REPO, "README.md")) as f:
            text = f.read()
        self.assertIn("--no-recall-rules", text)
        near = [l for l in text.split("\n") if re.search(r"(?i)recall.rule", l) and re.search(r"(?i)\bdefault\b|on by default", l)]
        self.assertTrue(near, "the README must say that the recall rule is on by default")

    def test_f81_c_f64_lists_the_recall_rule_in_the_default_install(self):
        with open(os.path.join(REPO, "docs", "spec.md")) as f:
            spec = f.read()
        m = re.search(r"(?m)^#+ F64\b.*$", spec)
        self.assertTrue(m)
        nxt = re.search(r"(?m)^## F\d+", spec[m.end():])
        sec = spec[m.end():m.end() + (nxt.start() if nxt else len(spec))]
        self.assertRegex(sec, r"(?i)recall.rule")


if __name__ == "__main__":
    unittest.main()
