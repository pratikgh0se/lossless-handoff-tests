"""F75 Auto-recall identifier history mode (amends F67.c; the F67.b trigger does not change). Code-blind: written from
contract-0.17.md only. An identifier is a token in backticks, or a token of 3+ characters with `-`, `_`, `.` or `/` inside
(a URL is not one). With 1+ identifiers the hook injects the F73 history of the first 3 (1,500 characters each, 4,000 in
total); with none it runs the F67.c word search without the stop-list words. The health row adds `mode` and
`identifiers` (a count, never the text)."""
import json, os, re, shutil, subprocess, sys, time, unittest

from history_common import (Lab, ENTRY_RE, OMIT_RE, HIST_LINE1, NO_MENTIONS, SID1, SID2, ts, entry, bash_call, tool_result,
                            injection)
from test_f67_auto_recall import HEADER as WORD_HEADER, HIT_RE as WORD_HIT_RE

HIST_HEADER = ("Lossless Handoff auto-recall: the history of the identifiers in your prompt, oldest first. A later mention "
               "can be rejected, a dry run or undone. This can be partial; search for the rest.")
FULL_RE = re.compile(r"^Full history: python3 (?P<hooks>\S+)/recall\.py history (?P<ident>\S+) --all$")
BLOCK_RE = re.compile(r"^history of (?P<ident>\S+?):")
STOP = ["previous", "replaced", "rejected", "proposal", "remember", "current", "earlier", "value", "values", "answer",
        "answers", "setting", "settings", "before", "which", "there", "their", "about", "would", "could", "should"]


class Base(Lab):
    def run_hook(self, prompt, raw=None, extra=None, transcript=True):
        path = os.path.join(self.tdir, SID1 + ".jsonl")
        payload = {"session_id": SID1, "transcript_path": path if transcript else os.path.join(self.tmp, "none.jsonl"),
                   "cwd": self.proj, "prompt": prompt, "hook_event_name": "UserPromptSubmit"}
        t0 = time.time()
        r = subprocess.run([sys.executable, os.path.join(self.hooks, "auto-recall.py")],
                           input=json.dumps(payload) if raw is None else raw, capture_output=True, text=True,
                           env=self.env(extra), cwd=self.tmp, timeout=30)
        self.elapsed = time.time() - t0
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    @staticmethod
    def context(stdout):
        s = stdout.strip("\n")
        if s.startswith("{"):
            try:
                return json.loads(s)["hookSpecificOutput"]["additionalContext"].strip("\n")
            except (ValueError, KeyError, TypeError):
                pass
        return s

    def ctx(self, prompt, **kw):
        return self.context(self.run_hook(prompt, **kw))

    def rows(self):
        p = os.path.join(self.hd, "auto-recall.jsonl")
        return [json.loads(l) for l in open(p) if l.strip()] if os.path.exists(p) else []

    def chain(self, key, n=3, tag=None, start=0):
        return [entry("user" if i % 2 == 0 else "assistant", "%s step %s%d is the value" % (key, tag or "", i),
                      "%s-%d" % (key, i), ts(start + i)) for i in range(n)]

    def blocks(self, out):
        return [m.group("ident") for m in (BLOCK_RE.match(l) for l in out.split("\n")) if m]


class Identifiers(Base):
    def test_f75_regex_identifier_gives_the_history_mode_output(self):
        self.put(SID1, self.chain("invoice-mailer", 3) + [entry("user", "what did we decide about invoice-mailer", "cur", ts(20))])
        out = self.ctx("what did we decide about invoice-mailer")
        ls = out.split("\n")
        self.assertEqual(ls[0], HIST_HEADER)
        self.assertEqual(ls[1], HIST_LINE1 % ("invoice-mailer", 3))
        self.assertEqual(len([l for l in ls if ENTRY_RE.match(l)]), 3)
        m = FULL_RE.match(ls[-1])
        self.assertTrue(m, ls[-1])
        self.assertEqual(m.group("ident"), "invoice-mailer")
        self.assertEqual(m.group("hooks"), "~/.claude/hooks")

    def test_f75_entries_are_oldest_first(self):
        self.put(SID1, self.chain("invoice-mailer", 4) + [entry("user", "what did we decide about invoice-mailer", "cur", ts(20))])
        out = self.ctx("what did we decide about invoice-mailer")
        steps = [int(re.search(r"step (\d)", l).group(1)) for l in out.split("\n") if ENTRY_RE.match(l)]
        self.assertEqual(steps, [0, 1, 2, 3])

    def test_f75_the_current_prompt_is_not_in_the_history(self):
        self.put(SID1, self.chain("invoice-mailer", 2) + [entry("user", "what did we decide about invoice-mailer CURRENTMARK", "cur", ts(20))])
        out = self.ctx("what did we decide about invoice-mailer CURRENTMARK")
        self.assertNotIn("CURRENTMARK", out)
        self.assertEqual(out.split("\n")[1], HIST_LINE1 % ("invoice-mailer", 2))

    def test_f75_backtick_token_is_an_identifier_even_without_a_separator(self):
        self.put(SID1, [entry("user", "Zeta is set to one", "u1", ts(1)), entry("user", "Zeta moved to two", "u2", ts(2)),
                        entry("user", "what did we decide about `Zeta`", "cur", ts(9))])
        out = self.ctx("what did we decide about `Zeta`")
        self.assertEqual(out.split("\n")[0], HIST_HEADER)
        self.assertEqual(out.split("\n")[1], HIST_LINE1 % ("Zeta", 2))

    def test_f75_each_separator_makes_an_identifier(self):
        for ident in ("alpha_beta", "alpha.beta", "alpha/beta", "alpha-beta"):
            with self.subTest(ident):
                self.put(SID1, [entry("user", "%s is set to one" % ident, "u1", ts(1)),
                                entry("user", "what did we decide about %s" % ident, "cur", ts(9))])
                out = self.ctx("what did we decide about %s" % ident)
                self.assertEqual(out.split("\n")[0], HIST_HEADER, out)
                self.assertIn(HIST_LINE1 % (ident, 1), out)

    def test_f75_a_url_is_not_an_identifier(self):
        self.put(SID1, [entry("user", "see https://example.com/some-page for the billing database notes", "u1", ts(1)),
                        entry("user", "what did we decide about https://example.com/some-page billing database", "cur", ts(9))])
        out = self.ctx("what did we decide about https://example.com/some-page billing database")
        self.assertNotEqual(out.split("\n")[0], HIST_HEADER)
        self.assertNotIn("history of", out)

    def test_f75_first_three_identifiers_in_prompt_order_without_duplicates(self):
        recs = []
        for i, k in enumerate(("beta-two", "alpha-one", "gamma-three", "delta-four")):
            recs += self.chain(k, 2, start=i * 3)
        self.put(SID1, recs + [entry("user", "x", "cur", ts(30))])
        out = self.ctx("what did we decide about beta-two and alpha-one and beta-two and gamma-three and delta-four")
        self.assertEqual(self.blocks(out), ["beta-two", "alpha-one", "gamma-three"], out)
        self.assertNotIn("delta-four", out)

    def test_f75_an_identifier_without_mentions_is_left_out(self):
        self.put(SID1, self.chain("real-key", 2) + [entry("user", "x", "cur", ts(30))])
        out = self.ctx("what did we decide about real-key and ghost-key")
        self.assertEqual(self.blocks(out), ["real-key"])
        self.assertNotIn("ghost-key", out)
        self.assertNotIn("no mentions", out)

    def test_f75_sibling_keys_do_not_leak_into_the_block(self):
        self.put(SID1, self.chain("invoice-mailer", 2) + [entry("user", "invoice-mailer-eu SIBLINGLEAK", "s1", ts(10)),
                                                        entry("user", "x", "cur", ts(30))])
        out = self.ctx("what did we decide about invoice-mailer")
        self.assertNotIn("SIBLINGLEAK", out)

    def test_f75_no_mentions_at_all_falls_back_to_the_word_search(self):
        self.put(SID1, [entry("user", "We decided to use the postgres database for the billing service", "u1", ts(1)),
                        entry("user", "what did i say about ghost-key postgres database billing", "cur", ts(9))])
        out = self.ctx("what did i say about ghost-key postgres database billing")
        self.assertTrue(out.startswith(WORD_HEADER), out[:200])
        self.assertTrue(any(WORD_HIT_RE.match(l) for l in out.split("\n")))
        self.assertEqual(self.rows()[-1]["mode"], "search")

    def test_f75_history_uses_the_f73_exclusions_and_fork_dedupe(self):
        base = self.chain("invoice-mailer", 2)
        self.put(SID1, base + [bash_call("python3 ~/.claude/hooks/recall.py history invoice-mailer", "b1", ts(5), tid="t1"),
                               tool_result("invoice-mailer RESULTLEAK", "r1", ts(6), tid="t1"),
                               injection("Lossless Handoff auto-recall: invoice-mailer INJLEAK", "i1", ts(7)),
                               entry("user", "x", "cur", ts(30))])
        self.put(SID2, [dict(r, sessionId=SID2) for r in base])
        out = self.ctx("what did we decide about invoice-mailer")
        self.assertEqual(out.split("\n")[1], HIST_LINE1 % ("invoice-mailer", 2))
        for leak in ("RESULTLEAK", "INJLEAK"):
            self.assertNotIn(leak, out)


class Caps(Base):
    def long(self, key, n=40, start=0):
        return [entry("user", "%s step %03d %s" % (key, i, "x" * 150), "%s-%d" % (key, i), ts((start + i) % 60, hour=1 + (start + i) // 60))
                for i in range(n)]

    def test_f75_one_identifier_block_is_at_most_1500_characters_with_the_middle_cut(self):
        self.put(SID1, self.long("invoice-mailer") + [entry("user", "x", "cur", ts(0, day=3))])
        out = self.ctx("what did we decide about invoice-mailer")
        ls = out.split("\n")
        start = ls.index(HIST_LINE1 % ("invoice-mailer", 40))
        end = max(i for i, l in enumerate(ls) if OMIT_RE.match(l) or ENTRY_RE.match(l))
        block = "\n".join(ls[start:end + 1])
        self.assertLessEqual(len(block), 1500, len(block))
        self.assertEqual(len([l for l in ls if OMIT_RE.match(l)]), 1, out)
        self.assertIn("step 000", ls[start + 1])
        self.assertIn("step 001", ls[start + 2])
        self.assertIn("step 039", ls[end], "the newest entry is kept")
        self.assertTrue(FULL_RE.match(ls[-1]))

    def test_f75_three_identifiers_stay_within_4000_characters_in_total(self):
        recs = []
        for i, k in enumerate(("alpha-one", "beta-two", "gamma-three")):
            recs += self.long(k, 40, start=i * 40)
        self.put(SID1, recs + [entry("user", "x", "cur", ts(0, day=3))])
        out = self.ctx("what did we decide about alpha-one beta-two gamma-three")
        self.assertLessEqual(len(out), 4000, len(out))
        got = self.blocks(out)
        self.assertEqual(got, ["alpha-one", "beta-two", "gamma-three"][:len(got)], "blocks keep prompt order")
        self.assertGreaterEqual(len(got), 2, "1,500 + 1,500 fit in 4,000")
        self.assertEqual(out.split("\n")[0], HIST_HEADER)
        self.assertTrue(FULL_RE.match(out.split("\n")[-1]))

    def test_f75_the_hooks_override_path_is_in_the_last_line(self):
        self.put(SID1, self.chain("invoice-mailer", 2) + [entry("user", "x", "cur", ts(30))])
        out = self.ctx("what did we decide about invoice-mailer", extra={"HANDOFF_HOOKS_HOME": self.hooks})
        m = FULL_RE.match(out.split("\n")[-1])
        self.assertTrue(m, out)
        self.assertEqual(m.group("hooks"), self.hooks)


class StopList(Base):
    def setUp(self):
        super().setUp()
        self.put(SID1, [entry("user", "postgres %s" % " ".join(STOP), "u1", ts(1)),
                        entry("user", "postgres billing database notes", "u2", ts(2)),
                        entry("user", "x", "cur", ts(30))])

    def test_f75_stop_list_words_are_left_out_of_the_query(self):
        for w in STOP:
            with self.subTest(w):
                out = self.run_hook("what did i say about postgres %s" % w)
                self.assertEqual(out.strip(), "", "only one query word is left, so there must be no output")

    def test_f75_control_two_real_words_still_fire(self):
        out = self.ctx("what did i say about postgres billing")
        self.assertTrue(out.startswith(WORD_HEADER), out[:200])

    def test_f75_only_stop_words_gives_no_output(self):
        self.assertEqual(self.run_hook("what did i say about the previous replaced rejected proposal").strip(), "")


class Health(Base):
    def test_f75_history_row_has_mode_and_the_identifier_count_and_no_text(self):
        self.put(SID1, self.chain("invoice-mailer", 2) + self.chain("billing-db", 2, start=5) + [entry("user", "x", "cur", ts(30))])
        self.ctx("what did we decide about invoice-mailer and billing-db")
        row = self.rows()[-1]
        self.assertTrue({"ts", "session_id", "fired", "cue", "hits", "ms", "timed_out", "mode", "identifiers"} <= set(row), row)
        self.assertEqual((row["mode"], row["identifiers"]), ("history", 2))
        self.assertIs(type(row["identifiers"]), int)
        text = open(os.path.join(self.hd, "auto-recall.jsonl")).read()
        for w in ("invoice-mailer", "billing-db", "invoice", "billing"):
            self.assertNotIn(w, text)

    def test_f75_search_row_has_mode_search_and_zero_identifiers(self):
        self.put(SID1, [entry("user", "We decided to use the postgres database for the billing service", "u1", ts(1))])
        self.ctx("what did i say about the postgres database billing")
        row = self.rows()[-1]
        self.assertEqual((row["mode"], row["identifiers"]), ("search", 0))

    def test_f75_one_identifier_counts_one(self):
        self.put(SID1, self.chain("invoice-mailer", 2) + [entry("user", "x", "cur", ts(30))])
        self.ctx("what did we decide about invoice-mailer")
        self.assertEqual(self.rows()[-1]["identifiers"], 1)


class Errors(Base):
    def test_f75_no_transcripts_at_all_gives_no_output_and_exit_0(self):
        out = self.run_hook("what did we decide about invoice-mailer", transcript=False)
        self.assertEqual(out.strip(), "")

    def test_f75_a_missing_transcript_path_and_no_project_transcripts_gives_no_output(self):
        shutil.rmtree(self.tdir)
        self.assertEqual(self.run_hook("what did we decide about invoice-mailer").strip(), "")

    def test_f75_bad_input_gives_no_output_and_exit_0(self):
        for raw in ("{not json", "", "[]", "{}", json.dumps({"prompt": 5})):
            with self.subTest(raw[:12]):
                self.assertEqual(self.run_hook("x", raw=raw).strip(), "")

    def test_f75_the_trigger_is_unchanged_an_identifier_alone_does_not_fire(self):
        self.put(SID1, self.chain("invoice-mailer", 2) + [entry("user", "x", "cur", ts(30))])
        self.assertEqual(self.run_hook("please deploy invoice-mailer now").strip(), "")
        self.assertEqual(self.run_hook("/recall what did we decide about invoice-mailer").strip(), "")

    def test_f75_runs_inside_the_time_budget(self):
        self.put(SID1, self.chain("invoice-mailer", 30) + [entry("user", "x", "cur", ts(59))])
        self.run_hook("what did we decide about invoice-mailer")
        self.assertLess(self.elapsed, 5.0)
        self.assertIs(self.rows()[-1]["timed_out"], False)


if __name__ == "__main__":
    unittest.main()
