"""F74 Search fixes (`recall.py search` and the MCP tool `search_earlier_chat`). Code-blind: written from
contract-0.17.md only. The F73 exclusions (a) recall's own tool use, (b) auto-recall injections and (d) fork duplicates
apply to search; (c) the current prompt applies to the MCP tool only. Hits whose query terms match as whole tokens rank
above substring-only hits, and inside each group the order stays newest first. The hit line format does not change."""
import json, os, re, sys, unittest

from history_common import Lab, SID1, SID2, ts, entry, bash_call, mcp_call, tool_result, injection
from test_f73_history import McpBase

HIT = re.compile(r"^(?P<id>\S+:\d+) (?P<ts>\d{4}-\d\d-\d\d \d\d:\d\d) (?P<role>user|assistant|tool)( \[(?P<src>\w+)\])?: (?P<text>.*)$")
DESC_ADD = ("Hits are newest first. A newer hit can be a rejected proposal or a dry run. For the history of one identifier, "
            "use key_history.")


def hits(out):
    return [HIT.match(l) for l in out.split("\n") if HIT.match(l)]


class Base(Lab):
    def search(self, *args, extra=None):
        r = self.run_recall("search", *args, extra=extra)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout


class Exclusions(Base):
    def test_f74_a_recall_tool_use_and_results_are_not_hits(self):
        self.put(SID1, [
            entry("user", "keep: the zebrawidget is on", "u1", ts(1)),
            bash_call("python3 ~/.claude/hooks/recall.py search zebrawidget", "b1", ts(2), tid="t1"),
            tool_result("zebrawidget RESULTLEAK", "r1", ts(3), tid="t1"),
            mcp_call("mcp__lossless-recall__search_earlier_chat", {"query": "zebrawidget MCPCALLLEAK"}, "m1", ts(4), tid="t2"),
            tool_result("zebrawidget MCPRESULTLEAK", "r2", ts(5), tid="t2")])
        out = self.search("zebrawidget")
        self.assertIn("keep: the zebrawidget", out)
        for leak in ("RESULTLEAK", "MCPCALLLEAK", "MCPRESULTLEAK", "recall.py search zebrawidget"):
            self.assertNotIn(leak, out)
        tool = self.search("zebrawidget", "--role", "tool")
        for leak in ("RESULTLEAK", "MCPCALLLEAK", "MCPRESULTLEAK", "recall.py search zebrawidget"):
            self.assertNotIn(leak, tool, "--role tool must not show recall's own calls either")

    def test_f74_a_control_other_tool_use_is_still_found(self):
        self.put(SID1, [bash_call("systemctl restart zebrawidget", "b1", ts(1), tid="t1"),
                        tool_result("zebrawidget restarted CONTROLMARK", "r1", ts(2), tid="t1")])
        out = self.search("zebrawidget", "--role", "tool")
        self.assertTrue(hits(out), "a Bash call without recall.py must stay searchable with --role tool:\n" + out)

    def test_f74_b_auto_recall_injections_are_not_hits(self):
        self.put(SID1, [entry("user", "real: the zebrawidget is on", "u1", ts(1)),
                        injection("Lossless Handoff auto-recall: earlier messages that match your words.\n"
                                  "- 73000001:1 2026-03-01 12:01 user: zebrawidget INJLEAK", "i1", ts(2))])
        out = self.search("zebrawidget")
        self.assertNotIn("INJLEAK", out)
        self.assertIn("real: the zebrawidget", out)

    def test_f74_d_fork_copy_shows_each_message_once(self):
        base = [entry("user", "zebrawidget set to a", "u1", ts(1)), entry("assistant", "zebrawidget ok a", "a1", ts(2))]
        self.put(SID1, base)
        self.put(SID2, [dict(r, sessionId=SID2) for r in base] + [entry("user", "zebrawidget set to c", "u3", ts(9), sid=SID2)])
        out = self.search("zebrawidget")
        for w in ("set to a", "ok a", "set to c"):
            self.assertEqual(out.count(w), 1, (w, out))

    def test_f74_d_same_text_and_timestamp_counts_once(self):
        self.put(SID1, [entry("user", "zebrawidget set to z", "u1", ts(5))])
        self.put(SID2, [entry("user", "zebrawidget  set to z", "other", ts(5), sid=SID2)])
        self.assertEqual(self.search("zebrawidget").count("set to z"), 1)

    def test_f74_c_the_cli_keeps_the_last_prompt(self):
        self.put(SID1, [entry("user", "old: zebrawidget is on", "u1", ts(1)),
                        entry("user", "what about zebrawidget LASTPROMPT", "u2", ts(9))])
        self.assertIn("LASTPROMPT", self.search("zebrawidget"))


class Ranking(Base):
    def chain(self):
        self.put(SID1, [entry("user", "WHOLEOLD the invoice-mailer is on", "u1", ts(1)),
                        entry("user", "SUBOLD xinvoice-mailer is a look-alike", "u2", ts(2)),
                        entry("user", "WHOLENEW the invoice-mailer moved", "u3", ts(3)),
                        entry("user", "SUBNEW invoice-mailer-eu is a sibling", "u4", ts(4))])

    def order(self, out):
        marks = re.findall(r"(WHOLEOLD|SUBOLD|WHOLENEW|SUBNEW)", "\n".join(h.group("text") for h in hits(out)))
        return marks

    def test_f74_whole_token_hits_rank_above_substring_hits_each_group_newest_first(self):
        self.chain()
        out = self.search("invoice-mailer")
        self.assertEqual(self.order(out), ["WHOLENEW", "WHOLEOLD", "SUBNEW", "SUBOLD"], out)

    def test_f74_ranking_with_a_plain_word(self):
        self.put(SID1, [entry("user", "WHOLEOLD the mailer is on", "u1", ts(1)),
                        entry("user", "SUBNEW the mailerd daemon", "u2", ts(2))])
        out = self.search("mailer")
        self.assertEqual(self.order(out), ["WHOLEOLD", "SUBNEW"], out)

    def test_f74_hit_line_format_is_unchanged(self):
        self.chain()
        out = self.search("invoice-mailer")
        self.assertTrue(hits(out))
        for l in out.split("\n"):
            if l.startswith("mode:") or l.endswith("searched)") or not l:
                continue
            self.assertRegex(l, HIT.pattern, l)

class Mcp(McpBase):
    def test_f74_description_has_the_added_sentence(self):
        c = self.start()
        tools = {t["name"]: t for t in c.call("tools/list")["result"]["tools"]}
        d = tools["search_earlier_chat"]["description"]
        self.assertIn(DESC_ADD, d)
        self.assertGreater(len(d), len(DESC_ADD))

    def test_f74_mcp_search_excludes_the_current_prompt_record_only(self):
        self.put(SID1, [entry("user", "old: zebrawidget is on", "u1", ts(1)),
                        entry("user", "what is zebrawidget CURRENTPROMPT", "u2", ts(9)),
                        entry("assistant", "about zebrawidget AFTERPROMPT", "a2", ts(10))])
        c = self.start()
        out = self.text(c.tool("search_earlier_chat", {"query": "zebrawidget"}))
        self.assertIn("old: zebrawidget", out)
        self.assertNotIn("CURRENTPROMPT", out)
        self.assertIn("AFTERPROMPT", out, "only the prompt record is hidden, not the records after it")

    def test_f74_mcp_search_applies_exclusions_a_b_and_d(self):
        base = [entry("user", "zebrawidget set to a", "u1", ts(1))]
        self.put(SID1, base + [bash_call("python3 recall.py search zebrawidget", "b1", ts(2), tid="t1"),
                               tool_result("zebrawidget RESULTLEAK", "r1", ts(3), tid="t1"),
                               injection("Lossless Handoff auto-recall: x zebrawidget INJLEAK", "i1", ts(4)),
                               entry("user", "closing prompt", "u9", ts(8))])
        self.put(SID2, [dict(r, sessionId=SID2) for r in base])
        c = self.start()
        out = self.text(c.tool("search_earlier_chat", {"query": "zebrawidget"}))
        self.assertEqual(out.count("set to a"), 1, out)
        self.assertNotIn("RESULTLEAK", out)
        self.assertNotIn("INJLEAK", out)

    def test_f74_mcp_ranking(self):
        self.put(SID1, [entry("user", "WHOLEOLD the invoice-mailer is on", "u1", ts(1)),
                        entry("user", "SUBOLD xinvoice-mailer is a look-alike", "u2", ts(2)),
                        entry("user", "WHOLENEW the invoice-mailer moved", "u3", ts(3)),
                        entry("user", "SUBNEW invoice-mailer-eu is a sibling", "u4", ts(4)),
                        entry("user", "a closing prompt", "u5", ts(5))])
        c = self.start()
        out = self.text(c.tool("search_earlier_chat", {"query": "invoice-mailer"}))
        marks = re.findall(r"(WHOLEOLD|SUBOLD|WHOLENEW|SUBNEW)", out)
        self.assertEqual(marks, ["WHOLENEW", "WHOLEOLD", "SUBNEW", "SUBOLD"], out)


if __name__ == "__main__":
    unittest.main()
