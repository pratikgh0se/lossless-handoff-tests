"""F71 Claim guard (opt-in, `--claim-guard`, shadow by default): `hooks/claim-guard.py`, a Stop hook (timeout 5).
Code-blind: written from contract-0.16.md. A claim cue in `last_assistant_message` plus no search evidence since the last
user message means: shadow mode logs `would_block` to `claim-guard.jsonl`; live mode (`HANDOFF_CLAIM_GUARD=block`) also
asks Claude Code to continue with a fixed reason. `stop_hook_active` true: nothing. At most one block per user turn.
Evidence: (a) a Bash tool call whose command has `recall.py`, (b) a tool call named `mcp__lossless-recall__*`,
(c) an auto-recall injection (text that starts with `Lossless Handoff auto-recall:`) after the last user message.
The branch spec (F71.f) fixes the live form: exit 0 and the JSON object {"decision": "block", "reason": <text>}."""
import json, os, unittest

from levers_common import Lab, write_transcript

CUES = ["as we decided", "we decided", "as you said", "you said", "we agreed", "as agreed", "as discussed", "you told me",
        "you mentioned", "as mentioned earlier", "earlier you", "last time"]
REASON = "You stated an earlier fact without searching. Search for it with recall, then correct or confirm it."
SCRIPT = "claim-guard.py"
PROMPT_TEXT = "ZQPROMPT please tell me about the billing storage"
REPLY_TEXT = "ZQREPLY the billing storage uses postgres"


def user(text, uuid):
    return {"type": "user", "uuid": uuid, "timestamp": "2026-03-01T12:00:00.000Z",
            "message": {"role": "user", "content": text}}


def tool_use(name, inp, uid="tu1"):
    return {"type": "assistant", "uuid": "a-" + uid, "message": {"role": "assistant",
            "content": [{"type": "tool_use", "id": uid, "name": name, "input": inp}]}}


def tool_result(uid="tu1"):
    return {"type": "user", "uuid": "r-" + uid, "message": {"role": "user",
            "content": [{"type": "tool_result", "tool_use_id": uid, "content": "ok"}]}}


def text_reply(text):
    return {"type": "assistant", "uuid": "t-" + text[:5], "message": {"role": "assistant",
            "content": [{"type": "text", "text": text}]}}


def injection(text):
    return {"type": "attachment", "uuid": "inj", "timestamp": "2026-03-01T12:00:01.000Z", "attachment": {
        "type": "hook_additional_context", "hookName": "UserPromptSubmit", "hookEvent": "UserPromptSubmit",
        "toolUseID": "UserPromptSubmit", "content": [text]}}


class Base(Lab):
    keep = ("claim-guard.py",)

    def setUp(self):
        super().setUp()
        self.assertTrue(os.path.isfile(os.path.join(self.hooks, SCRIPT)), "hooks/claim-guard.py is missing")
        self.sid = "71717171-0000-4000-8000-000000000071"
        self.tp = os.path.join(self.home, ".claude", "projects", "x", self.sid + ".jsonl")
        self.turn = 0

    def new_turn(self, *after, prompt=PROMPT_TEXT):
        """Write a transcript: an old turn, then a new user message and the records `after` it."""
        self.turn += 1
        recs = [user("An older question here", "u-old"), text_reply("An older answer"),
                user(prompt, "u-%d" % self.turn), *after]
        write_transcript(self.tp, recs)

    def run_guard(self, reply, extra=None, active=False, raw=None, sid=None):
        payload = {"session_id": sid or self.sid, "transcript_path": self.tp, "cwd": self.proj, "hook_event_name": "Stop",
                   "stop_hook_active": active, "last_assistant_message": reply}
        return self.script(SCRIPT, (), payload, raw=raw, extra=extra)

    def rows(self):
        return self.state_rows("claim-guard.jsonl")

    @staticmethod
    def blocked(r):
        """F71.f: exit 0 and exactly {"decision": "block", "reason": <fixed text>} on stdout."""
        if r.returncode == 0 and r.stdout.strip():
            return json.loads(r.stdout) == {"decision": "block", "reason": REASON}
        return False

    def assert_quiet(self, r):
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""), (r.stdout, r.stderr))


class Shadow(Base):
    def test_f71_each_cue_without_evidence_is_logged_and_prints_nothing(self):
        for i, cue in enumerate(CUES):
            with self.subTest(cue):
                self.new_turn(text_reply("x"))
                r = self.run_guard("Right: %s the storage is postgres." % cue)
                self.assert_quiet(r)
                rows = self.rows()
                self.assertEqual(len(rows), i + 1, rows)
                self.assertEqual(rows[-1]["cue"], cue)
                self.assertEqual(rows[-1]["session_id"], self.sid)
                self.assertIs(rows[-1]["would_block"], True)
                self.assertEqual(set(rows[-1]), {"ts", "session_id", "would_block", "cue"})

    def test_f71_cues_are_case_insensitive_and_whole_words(self):
        self.new_turn()
        self.assert_quiet(self.run_guard("AS WE DECIDED the storage is postgres"))
        self.assertEqual(self.rows()[-1]["cue"], "as we decided")
        n = len(self.rows())
        for text in ("we decidedly use postgres", "unyou said it", "wheel last timer", "reyou mentioned x"):
            self.new_turn()
            self.assert_quiet(self.run_guard(text))
        self.assertEqual(len(self.rows()), n)

    def test_f71_no_cue_means_no_log(self):
        self.new_turn()
        self.assert_quiet(self.run_guard("The storage is postgres. Done."))
        self.assertEqual(self.rows(), [])

    def test_f71_explicit_shadow_value_is_shadow(self):
        self.new_turn()
        r = self.run_guard("as we decided the storage is postgres", extra={"HANDOFF_CLAIM_GUARD": "shadow"})
        self.assert_quiet(r)
        self.assertEqual(len(self.rows()), 1)

    def test_f71_log_holds_no_reply_text_and_no_prompt_text(self):
        self.new_turn(prompt=PROMPT_TEXT)
        self.run_guard("%s as we decided" % REPLY_TEXT)
        text = open(os.path.join(self.hd, "claim-guard.jsonl")).read()
        for w in ("ZQREPLY", "ZQPROMPT", "billing", "postgres"):
            self.assertNotIn(w, text)


class Evidence(Base):
    REPLY = "As we decided, the storage is postgres."

    def quiet_with(self, *after):
        self.new_turn(*after)
        self.assert_quiet(self.run_guard(self.REPLY))
        self.assertEqual(self.rows(), [])

    def test_f71_a_bash_recall_call_is_evidence(self):
        self.quiet_with(tool_use("Bash", {"command": "python3 ~/.claude/hooks/recall.py search \"storage\""}),
                        tool_result())

    def test_f71_a_bash_command_without_recall_is_not_evidence(self):
        self.new_turn(tool_use("Bash", {"command": "ls -la"}), tool_result())
        self.assert_quiet(self.run_guard(self.REPLY))
        self.assertEqual(len(self.rows()), 1)

    def test_f71_an_mcp_recall_tool_call_is_evidence(self):
        self.quiet_with(tool_use("mcp__lossless-recall__search_earlier_chat", {"query": "storage"}), tool_result())
        self.setUp()
        self.quiet_with(tool_use("mcp__lossless-recall__open_message", {"id": "x:1"}), tool_result())

    def test_f71_another_mcp_server_is_not_evidence(self):
        self.new_turn(tool_use("mcp__other-server__search", {"query": "storage"}), tool_result())
        self.assert_quiet(self.run_guard(self.REPLY))
        self.assertEqual(len(self.rows()), 1)

    def test_f71_an_auto_recall_injection_is_evidence(self):
        self.quiet_with(injection("Lossless Handoff auto-recall: earlier messages that match your words. Verify them "
                                  "before you rely on them.\n- x:1 2026-03-01 12:00 user: we use postgres"))

    def test_f71_other_hook_context_is_not_evidence(self):
        self.new_turn(injection("some other hook context"))
        self.assert_quiet(self.run_guard(self.REPLY))
        self.assertEqual(len(self.rows()), 1)

    def test_f71_evidence_before_the_last_user_message_does_not_count(self):
        write_transcript(self.tp, [user("older question", "u-old"),
                                   tool_use("Bash", {"command": "python3 recall.py search x"}), tool_result(),
                                   text_reply("old answer"), user("a new question about storage", "u-new")])
        self.assert_quiet(self.run_guard(self.REPLY))
        self.assertEqual(len(self.rows()), 1)

    def test_f71_evidence_in_a_live_run_stops_the_block_too(self):
        self.new_turn(tool_use("Bash", {"command": "python3 ~/.claude/hooks/recall.py open x:1"}), tool_result())
        self.assert_quiet(self.run_guard(self.REPLY, extra={"HANDOFF_CLAIM_GUARD": "block"}))


class Live(Base):
    LIVE = {"HANDOFF_CLAIM_GUARD": "block"}
    REPLY = "As we decided, the storage is postgres."

    def test_f71_live_mode_blocks_with_the_fixed_reason(self):
        self.new_turn()
        r = self.run_guard(self.REPLY, extra=self.LIVE)
        self.assertTrue(self.blocked(r), (r.returncode, r.stdout, r.stderr))
        self.assertEqual(self.rows()[-1]["cue"], "as we decided")
        self.assertIs(self.rows()[-1]["would_block"], True)

    def test_f71_live_mode_blocks_for_each_cue(self):
        for cue in CUES:
            with self.subTest(cue):
                self.new_turn()
                self.assertTrue(self.blocked(self.run_guard("Yes, %s the storage is postgres" % cue, extra=self.LIVE)))

    def test_f71_stop_hook_active_means_nothing(self):
        self.new_turn()
        r = self.run_guard(self.REPLY, extra=self.LIVE, active=True)
        self.assert_quiet(r)
        self.assertEqual(self.rows(), [])
        r = self.run_guard(self.REPLY, active=True)
        self.assert_quiet(r)
        self.assertEqual(self.rows(), [])

    def test_f71_one_block_per_user_turn(self):
        self.new_turn()
        self.assertTrue(self.blocked(self.run_guard(self.REPLY, extra=self.LIVE)))
        r = self.run_guard(self.REPLY, extra=self.LIVE)
        self.assert_quiet(r)
        self.new_turn()  # a new user message
        self.assertTrue(self.blocked(self.run_guard(self.REPLY, extra=self.LIVE)))

    def test_f71_the_one_block_marker_is_per_session(self):
        self.new_turn()
        self.assertTrue(self.blocked(self.run_guard(self.REPLY, extra=self.LIVE)))
        self.assertTrue(self.blocked(self.run_guard(self.REPLY, extra=self.LIVE, sid="71717171-0000-4000-8000-0000000000bb")))

    def test_f71_live_mode_without_a_cue_prints_nothing(self):
        self.new_turn()
        self.assert_quiet(self.run_guard("The storage is postgres.", extra=self.LIVE))


class OffSwitch(Base):
    def test_f71_off_switch_means_nothing_at_all(self):
        self.new_turn()
        r = self.run_guard("As we decided, the storage is postgres.", extra={"HANDOFF_CLAIM_GUARD": "0"})
        self.assert_quiet(r)
        self.assertEqual(self.rows(), [])
        self.assertEqual([n for n in os.listdir(self.hd)] if os.path.isdir(self.hd) else [], [])


class NeverFails(Base):
    def test_f71_bad_input_prints_nothing_and_exits_0(self):
        self.new_turn()
        for raw in ("{not json", "", "[]", "null", "{}", json.dumps({"last_assistant_message": 5}),
                    json.dumps({"session_id": "s", "last_assistant_message": None})):
            for extra in (None, {"HANDOFF_CLAIM_GUARD": "block"}):
                with self.subTest(raw[:20], extra=extra):
                    self.assert_quiet(self.run_guard("x", raw=raw, extra=extra))

    def test_f71_missing_transcript_prints_nothing(self):
        payload = {"session_id": self.sid, "transcript_path": os.path.join(self.tmp, "none.jsonl"), "cwd": self.proj,
                   "stop_hook_active": False, "last_assistant_message": "As we decided, postgres."}
        for extra in (None, {"HANDOFF_CLAIM_GUARD": "block"}):
            self.assert_quiet(self.script(SCRIPT, (), payload, extra=extra))


if __name__ == "__main__":
    unittest.main()
