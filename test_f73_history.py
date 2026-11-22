"""F73 Key history: `recall.py history <identifier> [--role user|assistant|any] [--all]` and the MCP tool `key_history`.
Code-blind: written from contract-0.17.md only. Fixtures are synthetic transcripts in the real Claude Code jsonl shape.
Rules: whole-token match (boundary chars not in [A-Za-z0-9_./-]), case-insensitive; each match sentence plus the sentence
before and after; exclusions (a) recall's own tool use and results, (b) auto-recall injections, (c) the current prompt
(MCP and auto-recall only), (d) fork duplicates; oldest first; exact header and no-match lines; 4,000-character cap with
the middle cut."""
import json, os, re, sys, time, unittest

from history_common import (Lab, ENTRY_RE, OMIT_RE, HIST_LINE1, NO_MENTIONS, CAP, SID1, SID2, ts, entry, bash_call,
                            mcp_call, tool_result, injection)
from levers_common import Mcp

KEY = "invoice-mailer"


def texts(out):
    return [m.group("text") for m in Lab.entries(out)]


class Match(Lab):
    def test_f73_whole_token_matches_and_siblings_do_not(self):
        msgs = [("user", "set `invoice-mailer` to the eu region", "u1"),
                ("assistant", "the invoice-mailer, as asked, is set", "a1"),
                ("user", "now (invoice-mailer) uses port 25", "u2"),
                ("user", "INVOICE-MAILER is upper case here", "u3"),
                ("user", "invoice-mailer-eu is a sibling service", "s1"),
                ("user", "invoice-mailer.v2 is another sibling", "s2"),
                ("user", "xinvoice-mailer is a look-alike", "s3"),
                ("user", "invoice-mailer_old is also a sibling", "s4"),
                ("user", "invoice-mailer/api is a path sibling", "s5"),
                ("user", "an unrelated message about billing", "n1")]
        self.put(SID1, [entry(r, t, u, ts(i)) for i, (r, t, u) in enumerate(msgs)])
        out = self.history(KEY)
        got = texts(out)
        self.assertEqual(len(got), 4, out)
        self.assertEqual(self.lines(out)[0], HIST_LINE1 % (KEY, 4))
        for sib in ("invoice-mailer-eu", "invoice-mailer.v2", "xinvoice-mailer", "invoice-mailer_old", "invoice-mailer/api"):
            self.assertNotIn(sib, out, sib)
        self.assertTrue(any("eu region" in t for t in got))
        self.assertTrue(any("port 25" in t for t in got))
        self.assertTrue(any("upper case" in t for t in got))

    def test_f73_match_is_case_insensitive_for_the_argument_too(self):
        self.put(SID1, [entry("user", "the Invoice-Mailer is on", "u1", ts(1))])
        self.assertEqual(len(self.entries(self.history("INVOICE-MAILER"))), 1)

    def test_f73_boundary_characters_at_the_start_and_end_of_the_text(self):
        self.put(SID1, [entry("user", "invoice-mailer", "u1", ts(1)), entry("user", "go: invoice-mailer", "u2", ts(2)),
                        entry("user", "invoice-mailer: go", "u3", ts(3)), entry("user", "invoice-mailer.", "u4", ts(4))])
        self.assertEqual(len(self.entries(self.history(KEY))), 4)

    def test_f73_no_match_line(self):
        self.put(SID1, [entry("user", "nothing here about it", "u1", ts(1)), entry("user", "xinvoice-mailer", "u2", ts(2))])
        out = self.history(KEY)
        self.assertEqual(out.strip(), NO_MENTIONS % KEY)

    def test_f73_header_counts_the_entries(self):
        self.put(SID1, [entry("user", "invoice-mailer one", "u1", ts(1)), entry("user", "invoice-mailer two", "u2", ts(2))])
        out = self.history(KEY)
        self.assertEqual(self.lines(out)[0], HIST_LINE1 % (KEY, 2))
        self.assertEqual(len(self.entries(out)), 2)

    def test_f73_role_filter(self):
        self.put(SID1, [entry("user", "invoice-mailer from the user", "u1", ts(1)),
                        entry("assistant", "invoice-mailer from the assistant", "a1", ts(2))])
        out = self.history(KEY, "--role", "user")
        self.assertEqual([m.group("role") for m in self.entries(out)], ["user"])
        out = self.history(KEY, "--role", "assistant")
        self.assertEqual([m.group("role") for m in self.entries(out)], ["assistant"])
        out = self.history(KEY, "--role", "any")
        self.assertEqual([m.group("role") for m in self.entries(out)], ["user", "assistant"])
        self.assertEqual([m.group("role") for m in self.entries(self.history(KEY))], ["user", "assistant"])

    def test_f73_subagent_transcripts_are_searched(self):
        self.put(SID1, [entry("user", "main chat invoice-mailer note", "u1", ts(1))])
        self.put(SID1, [entry("assistant", "subagent invoice-mailer note", "sa1", ts(2), sid=SID1)], sub="a1b2c3d4e5f6a7b8")
        out = self.history(KEY)
        self.assertEqual(len(self.entries(out)), 2, out)

    def test_f73_other_projects_are_not_searched(self):
        other = os.path.join(self.home, ".claude", "projects", "-some-other-project")
        os.makedirs(other)
        with open(os.path.join(other, "x.jsonl"), "w") as f:
            f.write(json.dumps(entry("user", "invoice-mailer of another project", "o1", ts(1), cwd="/some/other/project")) + "\n")
        self.put(SID1, [entry("user", "invoice-mailer of this project", "u1", ts(2))])
        out = self.history(KEY)
        self.assertNotIn("another project", out)
        self.assertEqual(len(self.entries(out)), 1)

    def test_f73_entry_line_format_and_collapsed_whitespace(self):
        self.put(SID1, [entry("user", "invoice-mailer\n\n   has   many\t\tspaces", "u1", ts(7, hour=9))])
        m = self.entries(self.history(KEY))[0]
        self.assertEqual(m.group("ts"), "2026-03-01 09:07")
        self.assertNotRegex(m.group("text"), r"\s{2,}|\t")
        self.assertIn("has many spaces", m.group("text"))

    def test_f73_redaction_runs_on_the_whole_message_before_the_sentence_split(self):
        self.put(SID1, [entry("user", "invoice-mailer uses -----BEGIN PRIVATE KEY-----\nZZsecretlineXYZ123abcdefghij\n"
                                      "QQsecondlineXYZ456abcdefghij\n-----END PRIVATE KEY----- and that is all", "u1", ts(1))])
        out = self.history(KEY)
        self.assertEqual(len(self.entries(out)), 1, out)
        self.assertNotIn("ZZsecretlineXYZ123", out)
        self.assertNotIn("QQsecondlineXYZ456", out)
        self.assertIn("[REDACTED", out)

    def test_f73_text_is_redacted(self):
        key = "sk-" + "FAKEhistory" * 3 + "0001"
        self.put(SID1, [entry("user", "invoice-mailer password=zqhist0042x and key %s end" % key, "u1", ts(1))])
        out = self.history(KEY)
        self.assertIn("[REDACTED:", out)
        self.assertNotIn("zqhist0042x", out)
        self.assertNotIn(key, out)


class Units(Lab):
    def test_f73_sentence_before_and_after_are_included(self):
        self.put(SID1, [entry("user", "First sentence here. Second sentence here. The invoice-mailer is on port 25. "
                                      "Fourth sentence here. Fifth sentence here.", "u1", ts(1))])
        out = self.history(KEY)
        t = texts(out)
        self.assertEqual(len(t), 1, out)
        self.assertIn("Second sentence here", t[0])
        self.assertIn("port 25", t[0])
        self.assertIn("Fourth sentence here", t[0])
        self.assertNotIn("First sentence", t[0])
        self.assertNotIn("Fifth sentence", t[0])
        self.assertLess(t[0].index("Second"), t[0].index("port 25"))
        self.assertLess(t[0].index("port 25"), t[0].index("Fourth"))

    def test_f73_match_in_the_first_and_in_the_last_sentence(self):
        self.put(SID1, [entry("user", "invoice-mailer is first. Second one. Third one.", "u1", ts(1)),
                        entry("user", "One here. Two here. The last is invoice-mailer", "u2", ts(2))])
        t = texts(self.history(KEY))
        self.assertEqual(len(t), 2)
        self.assertIn("Second one", t[0])
        self.assertNotIn("Third one", t[0])
        self.assertIn("Two here", t[1])
        self.assertNotIn("One here", t[1])

    def test_f73_split_on_question_exclamation_and_newline(self):
        self.put(SID1, [entry("user", "Alpha why? Beta invoice-mailer now! Gamma later\nDelta next line", "u1", ts(1))])
        t = texts(self.history(KEY))
        self.assertEqual(len(t), 1)
        self.assertIn("Alpha why", t[0])
        self.assertIn("Gamma later", t[0])
        self.assertNotIn("Delta", t[0])

    def test_f73_a_newline_ends_a_sentence(self):
        self.put(SID1, [entry("user", "Line one\nLine two\ninvoice-mailer on line three\nLine four\nLine five", "u1", ts(1))])
        t = texts(self.history(KEY))
        self.assertEqual(len(t), 1)
        self.assertIn("Line two", t[0])
        self.assertIn("Line four", t[0])
        self.assertNotIn("Line one", t[0])
        self.assertNotIn("Line five", t[0])

    def test_f73_matches_in_one_sentence_give_one_entry(self):
        self.put(SID1, [entry("user", "Before it. invoice-mailer and invoice-mailer again. After it. Far away.", "u1", ts(1))])
        t = texts(self.history(KEY))
        self.assertEqual(len(t), 1, t)

    def test_f73_matches_in_distant_sentences_give_two_entries_without_repeated_text(self):
        self.put(SID1, [entry("user", "A1 start. B1 invoice-mailer first. C1 gap. D1 gap. E1 gap. F1 gap. "
                                      "G1 invoice-mailer second. H1 end.", "u1", ts(1))])
        t = texts(self.history(KEY))
        self.assertEqual(len(t), 2, t)
        self.assertIn("B1", t[0])
        self.assertIn("G1", t[1])
        self.assertNotIn("G1", t[0])
        self.assertNotIn("B1", t[1])


class Excluded(Lab):
    def test_f73_a_recall_tool_use_and_results_are_excluded(self):
        self.put(SID1, [
            entry("user", "keep: invoice-mailer is on", "u1", ts(1)),
            bash_call("python3 ~/.claude/hooks/recall.py search invoice-mailer", "b1", ts(2), tid="t1"),
            tool_result("1 hit: 73000001:1 invoice-mailer RESULTLEAK", "r1", ts(3), tid="t1"),
            mcp_call("mcp__lossless-recall__search_earlier_chat", {"query": "invoice-mailer MCPCALLLEAK"}, "m1", ts(4), tid="t2"),
            tool_result("no matches invoice-mailer MCPRESULTLEAK", "r2", ts(5), tid="t2"),
            mcp_call("mcp__lossless-recall__key_history", {"identifier": "invoice-mailer"}, "m2", ts(6), tid="t3"),
            tool_result("history of invoice-mailer: 1 mention(s) KHRESULTLEAK", "r3", ts(7), tid="t3")])
        out = self.history(KEY)
        self.assertEqual(len(self.entries(out)), 1, out)
        for leak in ("RESULTLEAK", "MCPCALLLEAK", "MCPRESULTLEAK", "KHRESULTLEAK"):
            self.assertNotIn(leak, out)

    def test_f73_other_bash_commands_are_not_excluded(self):
        self.put(SID1, [bash_call("systemctl restart invoice-mailer", "b1", ts(1), tid="t1"),
                        tool_result("restarted invoice-mailer OK", "r1", ts(2), tid="t1")])
        out = self.history(KEY)
        # tool inputs and results of other tools are not messages of the chat; the rule only names recall's own calls
        for m in self.entries(out):
            self.assertNotIn("RESULTLEAK", m.group("text"))

    def test_f73_b_auto_recall_injections_are_excluded(self):
        self.put(SID1, [entry("user", "real: invoice-mailer is on", "u1", ts(1)),
                        injection("Lossless Handoff auto-recall: earlier messages that match your words. Verify them "
                                  "before you rely on them.\n- 73000001:1 2026-03-01 12:01 user: invoice-mailer INJLEAK",
                                  "i1", ts(2))])
        out = self.history(KEY)
        self.assertNotIn("INJLEAK", out)
        self.assertEqual(len(self.entries(out)), 1, out)

    def test_f73_d_fork_copy_with_the_same_uuids_counts_once(self):
        base = [entry("user", "invoice-mailer set to a", "u1", ts(1)), entry("assistant", "invoice-mailer ok a", "a1", ts(2)),
                entry("user", "invoice-mailer set to b", "u2", ts(3))]
        self.put(SID1, base)
        fork = [dict(r, sessionId=SID2) for r in base] + [entry("user", "invoice-mailer set to c", "u3", ts(9), sid=SID2)]
        self.put(SID2, fork)
        out = self.history(KEY)
        self.assertEqual(len(self.entries(out)), 4, out)
        self.assertEqual(self.lines(out)[0], HIST_LINE1 % (KEY, 4))
        for w in ("set to a", "ok a", "set to b", "set to c"):
            self.assertEqual(out.count(w), 1, w)

    def test_f73_d_same_text_and_timestamp_with_different_uuids_counts_once(self):
        self.put(SID1, [entry("user", "invoice-mailer   set  to z", "u1", ts(5))])
        self.put(SID2, [entry("user", "invoice-mailer set to z", "other-uuid", ts(5), sid=SID2)])
        out = self.history(KEY)
        self.assertEqual(len(self.entries(out)), 1, out)

    def test_f73_d_same_text_at_another_time_is_kept(self):
        self.put(SID1, [entry("user", "invoice-mailer set to z", "u1", ts(5))])
        self.put(SID2, [entry("user", "invoice-mailer set to z", "u9", ts(6), sid=SID2)])
        self.assertEqual(len(self.entries(self.history(KEY))), 2)

    def test_f73_the_cli_keeps_the_last_prompt_because_the_current_prompt_rule_is_for_mcp_and_auto_recall(self):
        self.put(SID1, [entry("user", "old: invoice-mailer is on", "u1", ts(1)),
                        entry("user", "what is invoice-mailer set to LASTPROMPT", "u2", ts(9))])
        out = self.history(KEY)
        self.assertIn("LASTPROMPT", out)


class Order(Lab):
    def test_f73_oldest_first_across_files_by_timestamp(self):
        self.put(SID1, [entry("user", "invoice-mailer third", "u3", ts(30)), entry("user", "invoice-mailer fourth", "u4", ts(40))])
        self.put(SID2, [entry("user", "invoice-mailer first", "v1", ts(10), sid=SID2),
                        entry("user", "invoice-mailer second", "v2", ts(20), sid=SID2)])
        t = texts(self.history(KEY))
        self.assertEqual([x.split()[1] for x in t], ["first", "second", "third", "fourth"])

    def test_f73_ties_keep_file_order(self):
        self.put(SID1, [entry("user", "invoice-mailer alpha", "u1", ts(5)), entry("user", "invoice-mailer beta", "u2", ts(5))])
        t = texts(self.history(KEY))
        self.assertEqual([x.split()[1] for x in t], ["alpha", "beta"])


def long_chain(lab, n=60, width=170):
    recs = []
    for i in range(n):
        recs.append(entry("user", "invoice-mailer step %03d %s" % (i, "x" * width), "u%03d" % i, ts(i % 60, hour=1 + i // 60)))
    lab.put(SID1, recs)
    return n


class Cap(Lab):
    def test_f73_over_the_cap_keeps_line_one_two_oldest_and_the_newest_that_fit(self):
        n = long_chain(self)
        out = self.history(KEY)
        self.assertLessEqual(len(out.rstrip("\n")), CAP, len(out))
        ls = self.lines(out)
        self.assertEqual(ls[0], HIST_LINE1 % (KEY, n))
        ent = [ENTRY_RE.match(l) for l in ls[1:]]
        omit = [OMIT_RE.match(l) for l in ls]
        self.assertEqual(len([m for m in omit if m]), 1, out)
        oi = [i for i, m in enumerate(omit) if m][0]
        self.assertEqual(oi, 3, "line 1, 2 oldest entries, then the omitted line")
        self.assertIn("step 000", ls[1])
        self.assertIn("step 001", ls[2])
        tail = ls[oi + 1:]
        self.assertTrue(tail, "newest entries follow the omitted line")
        self.assertIn("step %03d" % (n - 1), tail[-1], "the newest entry is kept")
        for l in tail:
            self.assertRegex(l, ENTRY_RE.pattern)
        k = int(omit[oi].group("k"))
        self.assertEqual(2 + len(tail) + k, n)
        self.assertEqual(omit[oi].group("ident"), KEY)
        self.assertEqual(omit[oi].group("hooks"), "~/.claude/hooks")
        steps = [int(re.search(r"step (\d{3})", l).group(1)) for l in tail]
        self.assertEqual(steps, list(range(n - len(tail), n)), "a contiguous run of the newest entries")

    def test_f73_the_omitted_line_path_follows_the_hooks_override(self):
        long_chain(self)
        out = self.history(KEY, extra={"HANDOFF_HOOKS_HOME": self.hooks})
        m = [OMIT_RE.match(l) for l in self.lines(out) if OMIT_RE.match(l)]
        self.assertEqual(len(m), 1, out)
        self.assertEqual(m[0].group("hooks"), self.hooks)

    def test_f73_all_has_no_cap_and_no_omitted_line(self):
        n = long_chain(self)
        out = self.history(KEY, "--all")
        self.assertGreater(len(out), CAP)
        self.assertEqual(len(self.entries(out)), n)
        self.assertFalse(any(OMIT_RE.match(l) for l in self.lines(out)))
        self.assertEqual(self.lines(out)[0], HIST_LINE1 % (KEY, n))

    def test_f73_under_the_cap_prints_everything(self):
        self.put(SID1, [entry("user", "invoice-mailer step %d" % i, "u%d" % i, ts(i)) for i in range(10)])
        out = self.history(KEY)
        self.assertEqual(len(self.entries(out)), 10)
        self.assertFalse(any(OMIT_RE.match(l) for l in self.lines(out)))


# ---------------------------------------------------------------- MCP tool
class McpBase(Lab):
    def setUp(self):
        super().setUp()
        self.clients = []

    def tearDown(self):
        for c in self.clients:
            c.close()

    def start(self, extra=None):
        env = {"CLAUDE_CODE_SESSION_ID": SID1}  # the MCP current session (F73 amendment)
        env.update(extra or {})
        env = self.env({k: v for k, v in env.items() if v is not None})
        c = Mcp([sys.executable, os.path.join(self.hooks, "recall-mcp.py")], env, self.proj)
        self.clients.append(c)
        self.init = c.init()
        return c

    @staticmethod
    def text(r):
        assert "result" in r, r
        return r["result"]["content"][0]["text"]


class McpTool(McpBase):
    def test_f73_tools_list_has_key_history_with_always_load_and_the_description(self):
        c = self.start()
        tools = {t["name"]: t for t in c.call("tools/list")["result"]["tools"]}
        self.assertIn("key_history", tools)
        t = tools["key_history"]
        self.assertEqual(t["_meta"], {"anthropic/alwaysLoad": True})
        self.assertEqual(t["description"], "Every mention of one identifier (a key, file, service, setting or name) in "
                         "this project's chats, oldest first. Use it before you state the current value of anything that "
                         "can change.")
        self.assertEqual(t["inputSchema"]["type"], "object")
        self.assertEqual(t["inputSchema"]["required"], ["identifier"])
        self.assertTrue({"identifier", "role"} <= set(t["inputSchema"]["properties"]))

    def test_f73_instructions_have_the_key_history_line(self):
        c = self.start()
        ins = self.init["result"]["instructions"]
        self.assertIn("For the current value of a setting, key or decision, call key_history and read every mention: the "
                      "newest mention can be a rejected proposal.", ins)
        self.assertLess(len(ins), 4096)

    def test_f73_tool_gives_the_same_output_as_the_cli(self):
        self.put(SID1, [entry("user", "invoice-mailer one", "u1", ts(1)), entry("assistant", "invoice-mailer two", "a1", ts(2)),
                        entry("user", "an unrelated closing prompt", "u2", ts(3))])
        cli = self.history(KEY)
        c = self.start()
        self.assertEqual(self.text(c.tool("key_history", {"identifier": KEY})).strip(), cli.strip())
        self.assertEqual(self.text(c.tool("key_history", {"identifier": "no-such-key"})).strip(),
                         NO_MENTIONS % "no-such-key")

    def test_f73_role_argument(self):
        self.put(SID1, [entry("user", "invoice-mailer from the user", "u1", ts(1)),
                        entry("assistant", "invoice-mailer from the assistant", "a1", ts(2)),
                        entry("user", "an unrelated closing prompt", "u2", ts(3))])
        c = self.start()
        out = self.text(c.tool("key_history", {"identifier": KEY, "role": "assistant"}))
        self.assertEqual([m.group("role") for m in self.entries(out)], ["assistant"])

    def test_f73_the_4000_cap_is_always_on(self):
        n = long_chain(self)
        self.put(SID1, [entry("user", "invoice-mailer step %03d %s" % (i, "x" * 170), "u%03d" % i, ts(i % 60, hour=1 + i // 60))
                        for i in range(n)] + [entry("user", "an unrelated closing prompt", "uz", ts(0, day=2))])
        c = self.start()
        out = self.text(c.tool("key_history", {"identifier": KEY}))
        self.assertLessEqual(len(out), CAP)
        ls = self.lines(out)
        self.assertEqual(ls[0], HIST_LINE1 % (KEY, n))
        self.assertEqual(len([l for l in ls if OMIT_RE.match(l)]), 1, out)

    def test_f73_current_prompt_record_is_excluded_and_the_records_after_it_are_not(self):
        self.put(SID1, [entry("user", "old: invoice-mailer is on", "u1", ts(1)),
                        entry("assistant", "ok invoice-mailer noted", "a1", ts(2)),
                        entry("user", "what is invoice-mailer set to CURRENTPROMPT", "u2", ts(9)),
                        entry("assistant", "thinking about invoice-mailer AFTERPROMPT", "a2", ts(10))])
        c = self.start()
        out = self.text(c.tool("key_history", {"identifier": KEY}))
        self.assertNotIn("CURRENTPROMPT", out)
        self.assertIn("AFTERPROMPT", out)
        self.assertEqual(len(self.entries(out)), 3, out)

    def test_f73_without_the_session_variable_the_prompt_is_not_excluded(self):
        self.put(SID1, [entry("user", "old: invoice-mailer is on", "u1", ts(1)),
                        entry("user", "what is invoice-mailer set to CURRENTPROMPT", "u2", ts(9))])
        c = self.start({"CLAUDE_CODE_SESSION_ID": None})
        self.assertIn("CURRENTPROMPT", self.text(c.tool("key_history", {"identifier": KEY})))

    def test_f73_a_session_id_with_no_transcript_does_not_exclude_and_does_not_guess_the_newest(self):
        self.put(SID1, [entry("user", "old: invoice-mailer is on", "u1", ts(1)),
                        entry("user", "what is invoice-mailer set to CURRENTPROMPT", "u2", ts(9))])
        c = self.start({"CLAUDE_CODE_SESSION_ID": "99999999-0000-4000-8000-000000000009"})
        self.assertIn("CURRENTPROMPT", self.text(c.tool("key_history", {"identifier": KEY})))

    def test_f73_a_transcript_last_written_over_600_seconds_ago_is_not_current(self):
        self.put(SID1, [entry("user", "old: invoice-mailer is on", "u1", ts(1)),
                        entry("user", "what is invoice-mailer set to CURRENTPROMPT", "u2", ts(9))])
        path = os.path.join(self.tdir, SID1 + ".jsonl")
        old = time.time() - 700
        os.utime(path, (old, old))
        c = self.start()
        self.assertIn("CURRENTPROMPT", self.text(c.tool("key_history", {"identifier": KEY})))

    def test_f73_a_transcript_written_within_600_seconds_is_current(self):
        self.put(SID1, [entry("user", "old: invoice-mailer is on", "u1", ts(1)),
                        entry("user", "what is invoice-mailer set to CURRENTPROMPT", "u2", ts(9))])
        path = os.path.join(self.tdir, SID1 + ".jsonl")
        t = time.time() - 500
        os.utime(path, (t, t))
        c = self.start()
        self.assertNotIn("CURRENTPROMPT", self.text(c.tool("key_history", {"identifier": KEY})))

    def test_f73_the_variable_picks_its_own_session_not_the_newest_file(self):
        self.put(SID1, [entry("user", "old: invoice-mailer is on", "u1", ts(1)),
                        entry("user", "what is invoice-mailer set to PROMPTONE", "u2", ts(9))])
        self.put(SID2, [entry("user", "other: invoice-mailer here", "v1", ts(2), sid=SID2),
                        entry("user", "what is invoice-mailer set to PROMPTTWO", "v2", ts(10), sid=SID2)])
        c = self.start({"CLAUDE_CODE_SESSION_ID": SID1})
        out = self.text(c.tool("key_history", {"identifier": KEY}))
        self.assertNotIn("PROMPTONE", out)
        self.assertIn("PROMPTTWO", out)

    def test_f73_a_subagent_transcript_is_not_the_current_session(self):
        self.put(SID1, [entry("user", "old: invoice-mailer is on", "u1", ts(1))])
        self.put(SID1, [entry("user", "sub: invoice-mailer SUBPROMPT", "s1", ts(2), sid=SID1)], sub="a1b2c3d4e5f6a7b8")
        c = self.start()
        self.assertIn("SUBPROMPT", self.text(c.tool("key_history", {"identifier": KEY})))

    def test_f73_the_prompt_is_the_last_user_text_record_even_with_tool_results_after_it(self):
        self.put(SID1, [entry("user", "old: invoice-mailer is on", "u1", ts(1)),
                        entry("user", "what is invoice-mailer set to CURRENTPROMPT", "u2", ts(9)),
                        bash_call("ls", "b1", ts(10), tid="t1"),
                        tool_result("done", "r1", ts(11), tid="t1")])
        c = self.start()
        self.assertNotIn("CURRENTPROMPT", self.text(c.tool("key_history", {"identifier": KEY})))

    def test_f73_recall_tool_use_is_excluded_in_the_tool_too(self):
        self.put(SID1, [entry("user", "invoice-mailer real", "u1", ts(1)),
                        mcp_call("mcp__lossless-recall__key_history", {"identifier": "invoice-mailer"}, "m1", ts(2)),
                        tool_result("history of invoice-mailer RESULTLEAK", "r1", ts(3), tid="toolu_2"),
                        entry("user", "closing prompt", "u2", ts(4))])
        c = self.start()
        out = self.text(c.tool("key_history", {"identifier": KEY}))
        self.assertNotIn("RESULTLEAK", out)

    def test_f73_missing_identifier_is_an_error_and_the_server_goes_on(self):
        c = self.start()
        for args in ({}, {"identifier": 5}, {"identifier": ""}, {"identifier": "k", "role": "bogus"}):
            with self.subTest(args=args):
                r = c.tool("key_history", args)
                self.assertIs(r["result"].get("isError"), True, r)
                self.assertNotIn("\n", r["result"]["content"][0]["text"].strip())
        self.assertEqual(c.call("ping").get("result"), {})

    def test_f73_health_row(self):
        self.put(SID1, [entry("user", "invoice-mailer one", "u1", ts(1)), entry("assistant", "invoice-mailer two", "a1", ts(2)),
                        entry("user", "closing prompt", "u2", ts(3))])
        c = self.start()
        c.tool("key_history", {"identifier": KEY})
        c.tool("key_history", {"identifier": "no-such-key"})
        rows = [json.loads(l) for l in open(os.path.join(self.hd, "recall-mcp.jsonl")) if l.strip()]
        self.assertEqual(len(rows), 2, rows)
        for r in rows:
            self.assertEqual(set(r), {"ts", "tool", "hits", "ms"}, r)
            self.assertEqual(r["tool"], "key_history")
        self.assertEqual(rows[0]["hits"], 2)
        self.assertEqual(rows[1]["hits"], 0)
        text = open(os.path.join(self.hd, "recall-mcp.jsonl")).read()
        self.assertNotIn("invoice-mailer", text)
        self.assertNotIn("no-such-key", text)

    def test_f73_tool_list_has_three_tools(self):
        c = self.start()
        names = sorted(t["name"] for t in c.call("tools/list")["result"]["tools"])
        self.assertEqual(names, ["key_history", "open_message", "search_earlier_chat"])
        for t in c.call("tools/list")["result"]["tools"]:
            self.assertEqual(t["_meta"], {"anthropic/alwaysLoad": True}, t["name"])


if __name__ == "__main__":
    unittest.main()
