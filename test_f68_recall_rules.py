"""F68 Strict recall rules (opt-in, `--recall-rules`). Code-blind: written from contract-0.16.md.
With the marker file `<hooks dir>/.recall-rules` and `HANDOFF_RECALL_RULES` not `0`, every place that injects the recall
line (SessionStart compact, startup and resume output, and the SubagentStart output) adds one exact line directly
after the recall line. No marker, or `HANDOFF_RECALL_RULES=0`: output is byte-identical to 0.15.0. The inject row in
`receipts.jsonl` gets `"recall_rules": true|false`.
Also F83.e: when the recall MCP server is registered for the user, the rule line ends with the tool sentence."""
import json, os, unittest

from levers_common import (Lab, RULE_SENTENCE, MCP_SUFFIX, register_mcp, TOOL, RULE_A, DEC_B, BOUNDARY, additional_context,
                           write_transcript)
from test_f44_recall import RECALL_LINE

SOURCES = ("compact", "startup", "resume")


class Base(Lab):
    def setUp(self):
        super().setUp()
        self.ledger([RULE_A, DEC_B])

    def part1(self, source="compact", extra=None, transcript=None, args=("--ledger", "--part", "1")):
        payload = {"cwd": self.proj, "session_id": "N", "hook_event_name": "SessionStart", "source": source}
        if transcript:
            payload["transcript_path"] = transcript
        r = self.script("postcompact-inject.py", args, payload, extra=extra)
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout)
        return r.stdout

    def sub(self, extra=None):
        payload = {"session_id": "58585858-0000-4000-8000-000000000058", "cwd": self.proj, "prompt_id": "p-1",
                   "agent_id": "a1b2c3d4e5f6a7b8", "agent_type": "general-purpose", "hook_event_name": "SubagentStart",
                   "transcript_path": os.path.join(self.home, ".claude", "projects", "x", "s.jsonl")}
        r = self.script("postcompact-inject.py", ("--subagent-start",), payload, extra=extra)
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout)
        return r.stdout

    @staticmethod
    def lines_of(stdout):
        return additional_context(stdout).split("\n")

    @staticmethod
    def recall_index(lines):
        idx = [i for i, l in enumerate(lines) if l.startswith("- recall:")]
        assert len(idx) == 1, (idx, lines[:6])
        return idx[0]


class Marker(Base):
    def test_f68_recall_line_is_present_in_every_output(self):
        for s in SOURCES:
            with self.subTest(s):
                self.assertEqual(sum(1 for l in self.lines_of(self.part1(s)) if l.startswith("- recall:")), 1)
        self.assertEqual(sum(1 for l in self.lines_of(self.sub()) if l.startswith("- recall:")), 1)

    def test_f68_line_goes_directly_after_the_recall_line_in_session_start_output(self):
        self.marker()
        for s in SOURCES:
            with self.subTest(s):
                lines = self.lines_of(self.part1(s))
                i = self.recall_index(lines)
                self.assertEqual(lines[i + 1], RULE_SENTENCE)
                self.assertEqual(lines.count(RULE_SENTENCE), 1)

    def test_f68_line_goes_directly_after_the_recall_line_in_subagent_start_output(self):
        self.marker()
        lines = self.lines_of(self.sub())
        i = self.recall_index(lines)
        self.assertEqual(lines[i + 1], RULE_SENTENCE)
        self.assertEqual(lines.count(RULE_SENTENCE), 1)

    def test_f68_output_with_marker_is_the_old_output_plus_that_one_line(self):
        for name, run in (("part1", lambda **k: self.part1("compact", **k)), ("sub", lambda **k: self.sub(**k))):
            with self.subTest(name):
                self.marker(False)
                base = self.lines_of(run())
                self.marker(True)
                new = self.lines_of(run())
                i = self.recall_index(base)
                self.assertEqual(new, base[:i + 1] + [RULE_SENTENCE] + base[i + 1:])

    def test_f68_the_exact_text(self):
        self.assertEqual(RULE_SENTENCE, "- recall rule: if your context does not clearly show an earlier number, path, "
                         "name, command or decision, run the recall command above before you answer. Copy it exactly: "
                         "full path, no cd. A failed or denied command is not \"not found\": run the exact command again. "
                         "If no search can run, say so.")
        self.marker()
        self.assertIn(RULE_SENTENCE, additional_context(self.part1()))

    def test_f68_no_marker_output_is_byte_identical_whatever_the_env(self):
        self.marker(False)
        a = self.part1()
        b = self.part1(extra={"HANDOFF_RECALL_RULES": "1"})
        self.assertEqual(a, b)
        self.assertNotIn("recall rule:", a)
        self.assertNotIn("recall rule:", self.sub())

    def test_f68_off_switch_gives_byte_identical_output(self):
        self.marker(False)
        base1, base2 = self.part1(), self.sub()
        self.marker(True)
        self.assertEqual(self.part1(extra={"HANDOFF_RECALL_RULES": "0"}), base1)
        self.assertEqual(self.sub(extra={"HANDOFF_RECALL_RULES": "0"}), base2)

    def test_f68_other_env_values_keep_the_rule_on(self):
        self.marker()
        self.assertIn(RULE_SENTENCE, additional_context(self.part1(extra={"HANDOFF_RECALL_RULES": "1"})))
        self.assertIn(RULE_SENTENCE, additional_context(self.sub(extra={"HANDOFF_RECALL_RULES": ""})))

    def test_f68_marker_without_a_recall_line_adds_nothing(self):
        # no recall.py next to the hook: there is no recall line, so there is nothing to follow
        os.remove(os.path.join(self.hooks, "recall.py"))
        self.marker()
        r = self.sub()
        if r.strip():
            self.assertNotIn("recall rule:", r)
        self.assertNotIn("recall rule:", self.part1())


class Receipts(Base):
    def transcript(self):
        p = os.path.join(self.home, ".claude", "projects", "x", "N.jsonl")
        write_transcript(p, [{"type": "user", "message": {"role": "user", "content": "First instruction for the fixture ok"}},
                             BOUNDARY, {"type": "user", "message": {"role": "user", "content": "A later message here ok ok"}}])
        return p

    def rows(self):
        return self.state_rows("receipts.jsonl")

    def test_f68_receipt_has_recall_rules_true_with_the_marker(self):
        self.marker()
        self.part1(transcript=self.transcript(), args=("--part", "1"))
        rows = self.rows()
        self.assertEqual(len(rows), 1, rows)
        self.assertIs(rows[0].get("recall_rules"), True, rows[0])

    def test_f68_receipt_has_recall_rules_false_without_the_marker(self):
        self.marker(False)
        self.part1(transcript=self.transcript(), args=("--part", "1"))
        rows = self.rows()
        self.assertEqual(len(rows), 1, rows)
        self.assertIs(rows[0].get("recall_rules"), False, rows[0])

    def test_f68_receipt_has_false_when_the_off_switch_is_set(self):
        self.marker()
        self.part1(transcript=self.transcript(), args=("--part", "1"), extra={"HANDOFF_RECALL_RULES": "0"})
        self.assertIs(self.rows()[0].get("recall_rules"), False)

    def test_f68_receipt_keeps_the_old_fields(self):
        self.marker()
        self.part1(transcript=self.transcript(), args=("--part", "1"))
        r = self.rows()[0]
        for k in ("ts", "sid", "agent_id", "key", "transcript", "boundary_ts", "kind", "handoff_sha256",
                  "part1_sha256", "part1_head"):
            self.assertIn(k, r)


class McpSuffix(Base):
    """F83.e: the tool is named only when the recall MCP server is registered for the user, not when the file exists."""
    keep = ("recall-mcp.py",)

    def test_f83_e_registered_server_adds_the_tool_sentence_to_the_rule_line(self):
        self.marker()
        register_mcp(self.home)
        for name, run in (("part1", lambda: self.part1()), ("sub", lambda: self.sub())):
            with self.subTest(name):
                lines = self.lines_of(run())
                i = self.recall_index(lines)
                self.assertEqual(lines[i + 1], RULE_SENTENCE + MCP_SUFFIX)
                self.assertTrue(lines[i + 1].endswith(" If Bash is not allowed, call search_earlier_chat."))
                self.assertIn(TOOL, lines[i])
                self.assertTrue(lines[i].startswith(RECALL_LINE[:60]))

    def test_f83_e_the_file_alone_does_not_name_the_tool(self):
        self.marker()
        self.assertTrue(os.path.exists(os.path.join(self.hooks, "recall-mcp.py")))
        for name, run in (("part1", lambda: self.part1()), ("sub", lambda: self.sub())):
            with self.subTest(name):
                lines = self.lines_of(run())
                i = self.recall_index(lines)
                self.assertEqual(lines[i + 1], RULE_SENTENCE)
                self.assertNotIn(TOOL, "\n".join(lines))

    def test_f83_e_another_registered_server_does_not_count(self):
        self.marker()
        register_mcp(self.home, name="some-other-server")
        self.assertNotIn(TOOL, additional_context(self.part1()))
        self.assertNotIn(TOOL, additional_context(self.sub()))

    def test_f83_e_a_broken_user_config_means_not_registered(self):
        self.marker()
        with open(os.path.join(self.home, ".claude.json"), "w") as f:
            f.write("{ not json")
        out = self.part1()
        self.assertNotIn(TOOL, additional_context(out))
        self.assertIn(RULE_SENTENCE, additional_context(out))

    def test_f83_e_registered_server_without_the_marker_names_the_tool_in_the_recall_line_only(self):
        self.marker(False)
        register_mcp(self.home)
        lines = self.lines_of(self.part1())
        i = self.recall_index(lines)
        self.assertIn(TOOL, lines[i])
        self.assertNotIn("recall rule:", "\n".join(lines))
        self.assertNotIn(MCP_SUFFIX, "\n".join(lines))

    def test_f83_e_registered_server_with_the_off_switch_adds_no_rule_line(self):
        self.marker()
        register_mcp(self.home)
        out = additional_context(self.part1(extra={"HANDOFF_RECALL_RULES": "0"}))
        self.assertNotIn("recall rule:", out)


if __name__ == "__main__":
    unittest.main()
