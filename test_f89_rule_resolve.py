"""F89 End a rule with the user's words (0.21.1, hooks 1.23.1). Code-blind: written from the F89 text only.
F89.a-c / f.1-f.6: a rule RESOLVE needs a `| user: "<quote>"` part that the code finds in a user message of the new
conversation. F89.d / f.8: the merge prompt. F89.e / f.7: `--ledger-maintain` never resolves a rule. F89.f.9: the pins are in
test_versions_0211.py. The merge model is the `claude` shim of the suite (`set_shim("merge", out=...)`)."""
import json, os, re, subprocess, sys, unittest

from helpers import PRE, asst, user
from test_f39_ledger import check_merge_prompt, today_dates, ts
from test_f42_lossless_rules import F42, RESOLVED_RE, TODAY

SEED = ["- D1 [2026-10-20] [rule] Use spaces | why: style",
        "- D2 [2026-10-21] [rule] Never ship on Friday | why: rule",
        "- D3 [2026-10-22] [task] Approve release 1.2 | why: user ok"]
SAY = "D2 has ended, the date is past"
OLD = "[rule] Never ship on Friday | why: rule"


def tool_result(text, t):
    return {"type": "user", "timestamp": t, "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "toolu_f89", "content": text}]}}


def asst_at(text, t):
    return dict(asst(text), timestamp=t)


class Rule(F42):
    def run_merge(self, convo, out, seed=None):
        self.seed(seed or SEED)
        self.write_transcript(convo)
        self.set_shim("merge", out=out)
        self.go()
        return self.ledger_lines(), self.health()

    def said(self, text=SAY):
        return [user(text, timestamp=ts(0)), asst_at("ok, noted", ts(1)), user("Thanks, please continue with the work", timestamp=ts(2))]

    def applied(self, lines, n, reason, quote=None):
        pat = (r"^- D%d \[(\d{4}-\d\d-\d\d)\] RESOLVED \[(\d{4}-\d\d-\d\d)\]: %s \(user: \"%s\"\) \| was: (.*)$"
               % (n, re.escape(reason), re.escape(quote) if quote else r"[^\"]+"))
        m = re.match(pat, lines[n - 1])
        self.assertIsNotNone(m, lines[n - 1])
        return m

    def test_f89_f1_a_rule_is_resolved_with_the_user_words(self):
        lines, h = self.run_merge(self.said(), 'RESOLVE D2: date passed | user: "%s"' % SAY)
        self.assertEqual(self.ids(lines), [1, 2, 3])
        m = self.applied(lines, 2, "date passed", SAY)
        self.assertEqual(m.group(1), "2026-10-21")
        self.assertIn(m.group(2), today_dates())
        self.assertEqual(m.group(3), OLD)
        self.assertEqual((lines[0], lines[2]), (SEED[0], SEED[2]))
        self.assertEqual(h["ledger_resolved"], 1)
        self.assertEqual(h["ledger_rule_resolved"], 1)
        self.assertEqual(h.get("ledger_rule_resolve_rejected", 0), 0)
        self.assertEqual(h["ledger_active"], 2)

    def test_f89_f1_the_resolved_rule_is_in_no_injected_part(self):
        self.run_merge(self.said(), 'RESOLVE D2: date passed | user: "%s"' % SAY)
        joined = "".join(self.parts())
        self.assertNotIn("RESOLVED", joined)
        self.assertNotIn("Never ship on Friday", joined)
        self.assertNotRegex(joined, r"(?m)^- D2 ")
        self.assertRegex(joined, r"(?m)^- D1 ")

    def test_f89_f1_the_resolved_line_is_the_f42_form_and_parsing_keeps_working(self):
        lines, _ = self.run_merge(self.said(), 'RESOLVE D2: date passed | user: "%s"' % SAY)
        self.assertRegex(lines[1], RESOLVED_RE.replace("%s", ".*").replace("%d", "2"))
        self.write_transcript(self.convo(start=300, tag="2"))
        self.set_shim("merge", out="NO CHANGES")
        self.go()
        h = self.health()
        self.assertEqual((h["ledger"], h["ledger_active"], h["ledger_resolved"]), ("unchanged", 2, 1))
        self.assertRegex(self.ledger_lines()[1], r"RESOLVED")

    def test_f89_f2_a_quote_found_only_in_an_assistant_message_is_rejected(self):
        convo = [user("Please keep going with the build", timestamp=ts(0)), asst_at(SAY, ts(1)),
                 user("Thanks, please continue with the work", timestamp=ts(2))]
        lines, h = self.run_merge(convo, 'RESOLVE D2: date passed | user: "%s"' % SAY)
        self.assertEqual(lines, SEED)
        self.assertEqual(h["ledger_rule_resolve_rejected"], 1)
        self.assertEqual(h["ledger_resolved"], 0)
        self.assertEqual(h.get("ledger_rule_resolved", 0), 0)

    def test_f89_f2_a_quote_found_only_in_a_tool_result_is_rejected(self):
        convo = [user("Please keep going with the build", timestamp=ts(0)), tool_result(SAY, ts(1)),
                 user("Thanks, please continue with the work", timestamp=ts(2))]
        lines, h = self.run_merge(convo, 'RESOLVE D2: date passed | user: "%s"' % SAY)
        self.assertEqual(lines, SEED)
        self.assertEqual(h["ledger_rule_resolve_rejected"], 1)

    def test_f89_f2_a_quote_found_nowhere_is_rejected(self):
        lines, h = self.run_merge(self.said("The date is not an issue at all today"),
                                  'RESOLVE D2: date passed | user: "%s"' % SAY)
        self.assertEqual(lines, SEED)
        self.assertEqual(h["ledger_rule_resolve_rejected"], 1)

    def test_f89_f3_a_rule_resolve_with_no_user_part_is_ignored(self):
        lines, h = self.run_merge(self.said(), "RESOLVE D2: done")
        self.assertEqual(lines, SEED)
        self.assertEqual((h["ledger_active"], h["ledger_resolved"]), (3, 0))
        self.assertEqual(h.get("ledger_rule_resolved", 0), 0)

    def test_f89_f4_a_quote_of_7_characters_is_ignored(self):
        quote = "ended n"
        self.assertEqual(len(quote), 7)
        lines, h = self.run_merge(self.said("The rule has ended now, thanks"), 'RESOLVE D2: over | user: "%s"' % quote)
        self.assertEqual(lines, SEED)
        self.assertEqual(h["ledger_resolved"], 0)

    def test_f89_f4_a_quote_of_301_characters_is_ignored(self):
        quote = ("lorem ipsum dolor " * 20)[:300] + "x"
        self.assertEqual(len(quote), 301)
        lines, h = self.run_merge(self.said("The rule is over. " + quote), 'RESOLVE D2: over | user: "%s"' % quote)
        self.assertEqual(lines, SEED)
        self.assertEqual(h["ledger_resolved"], 0)

    def test_f89_f4_quotes_of_8_and_300_characters_are_applied(self):
        for quote in ("ended ok", ("lorem ipsum dolor " * 20)[:299] + "x"):
            with self.subTest(n=len(quote)):
                lines, h = self.run_merge(self.said("The rule has ended ok. " + quote), 'RESOLVE D2: over | user: "%s"' % quote)
                self.applied(lines, 2, "over")
                self.assertEqual(h["ledger_rule_resolved"], 1)

    def test_f89_f5_case_and_spacing_do_not_matter(self):
        lines, h = self.run_merge(self.said("D2  has   ENDED,\n the DATE is   past"),
                                  'RESOLVE D2: date passed | user: "d2 has ended, the date is past"')
        self.applied(lines, 2, "date passed")
        self.assertEqual(h["ledger_rule_resolved"], 1)

    def test_f89_d_a_backslash_escaped_quote_is_read_with_the_backslashes_removed(self):
        lines, h = self.run_merge(self.said(), 'RESOLVE D2: date passed | user: \\"%s\\"' % SAY)
        self.applied(lines, 2, "date passed", SAY)
        self.assertNotIn("\\", lines[1])
        self.assertEqual(h["ledger_rule_resolved"], 1)

    def test_f89_f5_a_different_word_is_not_a_match(self):
        lines, h = self.run_merge(self.said("D2 has ended, the date is past"),
                                  'RESOLVE D2: date passed | user: "D2 has ended, the date is not past"')
        self.assertEqual(lines, SEED)
        self.assertEqual(h["ledger_rule_resolve_rejected"], 1)

    def test_f89_f6_a_task_resolve_without_a_quote_still_works(self):
        lines, h = self.run_merge(self.said("Something else was said here today"), "RESOLVE D3: shipped")
        m = re.match(RESOLVED_RE % (3, "shipped"), lines[2])
        self.assertIsNotNone(m, lines[2])
        self.assertNotIn("(user:", lines[2])
        self.assertEqual((lines[0], lines[1]), (SEED[0], SEED[1]))
        self.assertEqual(h["ledger_resolved"], 1)
        self.assertEqual(h.get("ledger_rule_resolved", 0), 0)

    def test_f89_a_only_active_rules_count_a_superseded_or_unknown_id_is_ignored(self):
        seed = SEED + ["- D4 [2026-10-23] SUPERSEDED by D1 [2026-10-24]: [rule] Old rule | because: replaced",
                       "- D5 [2026-10-23] [decision] Use SQLite | why: simple"]
        out = "\n".join('RESOLVE D%d: over | user: "%s"' % (n, SAY) for n in (4, 5, 99))
        lines, h = self.run_merge(self.said(), out, seed=seed)
        self.assertEqual(lines, seed)
        self.assertEqual(h["ledger_resolved"], 0)

    def test_f89_b_one_good_and_one_bad_line_apply_one_and_count_one_rejection(self):
        out = 'RESOLVE D2: date passed | user: "%s"\nRESOLVE D1: gone | user: "this was never said by the user"' % SAY
        lines, h = self.run_merge(self.said(), out)
        self.applied(lines, 2, "date passed", SAY)
        self.assertEqual(lines[0], SEED[0])
        self.assertEqual((h["ledger_rule_resolved"], h["ledger_rule_resolve_rejected"], h["ledger_resolved"]), (1, 1, 1))

    def test_f89_b_an_empty_reason_is_ignored(self):
        lines, h = self.run_merge(self.said(), 'RESOLVE D2:  | user: "%s"' % SAY)
        self.assertEqual(lines, SEED)
        self.assertEqual(h["ledger_resolved"], 0)

    def test_f89_f8_the_merge_prompt_has_the_rule_sentence_and_the_quote_form(self):
        self.go()
        last = self.merge_argv()[-1]
        self.assertIn("Never RESOLVE a rule on your own judgement", last)
        self.assertIn('| user: "', last)
        self.assertNotIn('| user: \\"', last, "the quote in the prompt is a plain quote")
        self.assertIn("NEW CONVERSATION", last)
        check_merge_prompt(self, last)


class Maintain(F42):
    def run_maintain(self, extra=None):
        return subprocess.run([sys.executable, PRE, "--ledger-maintain", self.cwd], input="", capture_output=True,
                              text=True, env=self.env(None, extra), timeout=60, cwd=self.tmp)

    def argv_text(self):
        for name in ("merge.argv0", "argv0"):
            p = os.path.join(self.shimdir, name)
            if os.path.exists(p):
                return open(p, "rb").read().decode("utf-8", "replace")
        self.fail("the model was not called")

    def test_f89_f7_maintain_never_resolves_a_rule_even_with_a_user_part(self):
        seed = ["- D1 [2026-10-20] [rule] Never ship on Friday | why: rule", "- D2 [2026-10-21] [task] Approve release 1.2 | why: ok"]
        self.seed(seed)
        out = 'RESOLVE D1: over | user: "the user said this rule has ended"\n'
        self.set_shim("merge", out=out)
        self.set_shim("summary", out=out)
        r = self.run_maintain()
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertEqual(self.ledger_lines(), seed)
        self.assertRegex(r.stdout.strip(), r"resolved=0")

    def test_f89_e_maintain_still_resolves_a_task(self):
        seed = ["- D1 [2026-10-20] [rule] Never ship on Friday | why: rule", "- D2 [2026-10-21] [task] Approve release 1.2 | why: ok"]
        self.seed(seed)
        out = "RESOLVE D2: done\n"
        self.set_shim("merge", out=out)
        self.set_shim("summary", out=out)
        r = self.run_maintain()
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        lines = self.ledger_lines()
        self.assertEqual(lines[0], seed[0])
        self.assertIsNotNone(re.match(RESOLVED_RE % (2, "done"), lines[1]), lines[1])

    def test_f89_e_the_maintain_prompt_keeps_never_resolve_a_rule(self):
        self.seed(["- D1 [2026-10-20] [rule] Never ship on Friday | why: rule"])
        self.set_shim("merge", out="NO CHANGES")
        self.set_shim("summary", out="NO CHANGES")
        self.run_maintain()
        self.assertIn("never resolve a rule", self.argv_text().lower())


if __name__ == "__main__":
    unittest.main()
