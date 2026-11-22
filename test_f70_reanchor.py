"""F70 Re-anchor (opt-in, `--reanchor`): `hooks/reanchor.py`, a PostToolUse hook (matcher `*`, timeout 5). Code-blind:
written from contract-0.16.md. It reads the context token count of the session like `handoff-nudge.py` (the last usage
entry of the transcript). When the count is at least 50,000 tokens above the last anchor, it prints one JSON object
with the active rules and the recall line, and stores the new anchor. A count below the anchor means a compaction
happened: the anchor resets to the current count. Fixtures are transcripts with usage entries."""
import json, os, unittest

from levers_common import Lab, RULE_A, DEC_B, TASK_C, usage_entry, write_transcript, additional_context, RULE_SENTENCE
from test_f44_recall import RECALL_LINE

HEADER = "Lossless Handoff re-anchor: the project's active rules, repeated so they stay near the end of your context."
SCRIPT = "reanchor.py"


class Base(Lab):
    keep = ("reanchor.py",)

    def setUp(self):
        super().setUp()
        self.assertTrue(os.path.isfile(os.path.join(self.hooks, SCRIPT)), "hooks/reanchor.py is missing")
        self.ledger([RULE_A, DEC_B, TASK_C])
        self.sid = "70707070-0000-4000-8000-000000000070"

    def run_at(self, tokens, sid=None, extra=None, split=False, raw=None, transcript=True, agent=False):
        sid = sid or self.sid
        tp = os.path.join(self.home, ".claude", "projects", "x", sid + ".jsonl")
        write_transcript(tp, [{"type": "user", "message": {"role": "user", "content": "Please keep going on the task"}},
                              usage_entry(tokens, split=split)])
        payload = {"session_id": sid, "transcript_path": tp if transcript else os.path.join(self.tmp, "none.jsonl"),
                   "cwd": self.proj, "hook_event_name": "PostToolUse", "tool_name": "Bash",
                   "tool_input": {"command": "ls"}, "tool_response": {"stdout": "x"}}
        if agent:
            payload.update(agent_id="a1b2c3d4e5f6a7b8", agent_type="general-purpose")
        r = self.script(SCRIPT, (), payload, raw=raw, extra=extra)
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout)
        return r.stdout

    def fires(self, tokens, **kw):
        return bool(self.run_at(tokens, **kw).strip())

    def health(self):
        return [r for r in self.state_rows("health.jsonl") if r.get("event") == "reanchor"]


class Interval(Base):
    def test_f70_below_50000_prints_nothing(self):
        self.assertEqual(self.run_at(49999), "")

    def test_f70_at_50000_prints(self):
        self.assertTrue(self.fires(50000))

    def test_f70_next_print_needs_50000_more(self):
        self.assertTrue(self.fires(60000))
        self.assertFalse(self.fires(100000))
        self.assertFalse(self.fires(109999))
        self.assertTrue(self.fires(110000))
        self.assertFalse(self.fires(159999))
        self.assertTrue(self.fires(160000))

    def test_f70_a_run_that_prints_nothing_does_not_move_the_anchor(self):
        self.assertTrue(self.fires(60000))
        for t in (70000, 80000, 90000, 100000):
            self.assertFalse(self.fires(t), t)
        self.assertTrue(self.fires(110000))

    def test_f70_after_a_compaction_the_anchor_resets(self):
        self.assertTrue(self.fires(150000))
        self.assertEqual(self.run_at(30000), "", "a lower count is a compaction: the anchor resets, nothing prints")
        self.assertFalse(self.fires(79999))
        self.assertTrue(self.fires(80000))

    def test_f70_sessions_have_their_own_anchor(self):
        self.assertTrue(self.fires(60000))
        self.assertTrue(self.fires(60000, sid="70707070-0000-4000-8000-0000000000bb"))
        self.assertFalse(self.fires(70000))

    def test_f70_token_count_adds_cache_tokens(self):
        self.assertEqual(self.run_at(49999, split=True), "")
        self.assertTrue(self.fires(61000, sid="70707070-0000-4000-8000-0000000000cc", split=True))

    def test_f70_state_file_per_session(self):
        self.run_at(60000)
        p = os.path.join(self.hd, "reanchor-%s.json" % self.sid)
        self.assertTrue(os.path.exists(p), os.listdir(self.hd))
        self.assertEqual(json.load(open(p)), {"v": 1, "anchor": 60000})

    def test_f70_subagent_events_are_ignored(self):
        self.assertEqual(self.run_at(90000, agent=True), "")
        self.assertFalse(os.path.exists(os.path.join(self.hd, "reanchor-%s.json" % self.sid)))
        self.assertTrue(self.fires(90000))

    def test_f70_the_anchor_moves_even_when_there_is_no_rule(self):
        self.ledger([DEC_B])
        self.assertEqual(self.run_at(60000), "")
        self.ledger([RULE_A])
        self.assertFalse(self.fires(100000), "the anchor is 60000 now")
        self.assertTrue(self.fires(110000))


class Override(Base):
    def test_f70_env_interval_is_used(self):
        self.assertTrue(self.fires(12000, extra={"HANDOFF_REANCHOR_TOKENS": "10000"}))

    def test_f70_bounds_are_inclusive(self):
        self.assertFalse(self.fires(499999, extra={"HANDOFF_REANCHOR_TOKENS": "500000"}))
        self.assertTrue(self.fires(500000, sid="70707070-0000-4000-8000-0000000000d1",
                                   extra={"HANDOFF_REANCHOR_TOKENS": "500000"}))
        self.assertFalse(self.fires(9999, sid="70707070-0000-4000-8000-0000000000d2",
                                    extra={"HANDOFF_REANCHOR_TOKENS": "10000"}))
        self.assertTrue(self.fires(10000, sid="70707070-0000-4000-8000-0000000000d3",
                                   extra={"HANDOFF_REANCHOR_TOKENS": "10000"}))

    def test_f70_out_of_range_or_bad_values_use_50000(self):
        for i, v in enumerate(("9999", "5000", "0", "-1", "500001", "abc", "", "1e5", "20000.5")):
            with self.subTest(v):
                sid = "70707070-0000-4000-8000-0000000001%02d" % i
                self.assertFalse(self.fires(30000, sid=sid, extra={"HANDOFF_REANCHOR_TOKENS": v}), "30000 < 50000")
                sid2 = "70707070-0000-4000-8000-0000000002%02d" % i
                self.assertTrue(self.fires(50000, sid=sid2, extra={"HANDOFF_REANCHOR_TOKENS": v}))

    def test_f70_off_switch(self):
        self.assertEqual(self.run_at(200000, extra={"HANDOFF_REANCHOR": "0"}), "")
        self.assertEqual(self.health(), [])
        self.assertFalse(os.path.exists(os.path.join(self.hd, "reanchor-%s.json" % self.sid)))

    def test_f70_other_values_of_the_off_variable_keep_it_on(self):
        self.assertTrue(self.fires(60000, extra={"HANDOFF_REANCHOR": "1"}))


class Output(Base):
    def obj(self, tokens=60000):
        out = self.run_at(tokens)
        self.assertTrue(out.strip(), "no output")
        return json.loads(out), out

    def test_f70_exact_json_shape(self):
        o, out = self.obj()
        self.assertEqual(set(o), {"hookSpecificOutput"})
        h = o["hookSpecificOutput"]
        self.assertEqual(set(h), {"hookEventName", "additionalContext"})
        self.assertEqual(h["hookEventName"], "PostToolUse")
        self.assertIsInstance(h["additionalContext"], str)
        self.assertEqual(out.count("\n"), 1 if out.endswith("\n") else 0, "one JSON object on one line")

    def test_f70_text_has_header_rules_and_recall_line(self):
        o, _ = self.obj()
        text = o["hookSpecificOutput"]["additionalContext"]
        lines = text.split("\n")
        self.assertEqual(lines[0], HEADER)
        self.assertIn("RULEAAA", text)
        self.assertNotIn("DECBBB", text.split("- recall:")[0], "active rules only")
        self.assertNotIn("TASKDDD", text)
        self.assertTrue(lines[-1].startswith("- recall:"), lines[-1][:80])
        self.assertTrue(lines[-1].startswith(RECALL_LINE[:80]))

    def test_f70_rules_block_is_at_most_4000_characters(self):
        self.ledger(["- D%d [2026-10-20] [rule] RULE%d %s | why: r" % (n, n, "x" * 280) for n in range(1, 60)])
        text = json.loads(self.run_at(60000))["hookSpecificOutput"]["additionalContext"]
        recall = text.split("\n")[-1]
        block = text[len(HEADER):len(text) - len(recall)]
        self.assertLessEqual(len(block.strip("\n")), 4000, len(block))
        self.assertIn("RULE59", text, "newest rules first")

    def test_f70_with_the_recall_rules_marker_the_recall_line_is_followed_by_the_rule_line(self):
        self.marker()
        text = json.loads(self.run_at(60000))["hookSpecificOutput"]["additionalContext"]
        lines = text.split("\n")
        i = [k for k, l in enumerate(lines) if l.startswith("- recall:")][0]
        self.assertEqual(lines[i + 1], RULE_SENTENCE)

    def test_f70_no_rules_means_no_output_and_no_health_row(self):
        for lines in ([DEC_B, TASK_C], []):
            with self.subTest(len(lines)):
                self.ledger(lines)
                self.assertEqual(self.run_at(90000, sid="70707070-0000-4000-8000-0000000003%02d" % len(lines)), "")
        self.assertEqual(self.health(), [])

    def test_f70_no_ledger_file_means_no_output(self):
        os.remove(os.path.join(self.pdir, "decisions.md"))
        self.assertEqual(self.run_at(90000), "")


class Health(Base):
    def test_f70_one_row_per_injection(self):
        text = json.loads(self.run_at(60000))["hookSpecificOutput"]["additionalContext"]
        self.run_at(70000)
        rows = self.health()
        self.assertEqual(len(rows), 1, rows)
        r = rows[0]
        self.assertEqual(set(r), {"ts", "session_id", "event", "tokens", "chars"})
        self.assertEqual(r["session_id"], self.sid)
        self.assertEqual(r["tokens"], 60000)
        self.assertEqual(r["chars"], len(text))
        self.assertIs(type(r["tokens"]), int)
        self.assertIs(type(r["chars"]), int)
        self.assertIsInstance(r["ts"], str)

    def test_f70_second_injection_adds_a_second_row(self):
        self.run_at(60000)
        self.run_at(115000)
        self.assertEqual([r["tokens"] for r in self.health()], [60000, 115000])


class NeverFails(Base):
    def test_f70_bad_input_prints_nothing_and_exits_0(self):
        for raw in ("{not json", "", "[]", "null", "{}", json.dumps({"session_id": 5}), json.dumps({"transcript_path": None})):
            with self.subTest(raw[:20]):
                self.assertEqual(self.run_at(90000, raw=raw), "")

    def test_f70_missing_transcript_prints_nothing(self):
        self.assertEqual(self.run_at(90000, transcript=False), "")

    def test_f70_unreadable_state_file_prints_nothing_or_json_and_exits_0(self):
        os.makedirs(self.hd, exist_ok=True)
        open(os.path.join(self.hd, "reanchor-%s.json" % self.sid), "w").write("{not json")
        out = self.run_at(90000)
        if out.strip():
            json.loads(out)


if __name__ == "__main__":
    unittest.main()
