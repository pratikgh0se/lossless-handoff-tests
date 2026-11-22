"""F77 History guard: `hooks/history-guard.py`, a Stop command hook (opt-in, shadow by default). Code-blind: written from
contract-0.18.md and litm-trigger-design.md section 2.
Trigger (all true): 1 `stop_hook_active` is not true and the hook did not block in this user turn; 2 the context count is
at least 100,000 tokens (env HANDOFF_HISTORY_GUARD_TOKENS, 10,000 to 1,000,000); 3 the reply has an anchor (an identifier,
the first 60, not in a tool input or result of this turn and not an existing path below cwd); 4 the anchor gives a subject
(an identifier in 2 to 40 text messages before the current user prompt, at least 2 from the user; otherwise the identifiers
in the same sentence as an earlier mention of the anchor); 5 no evidence in this turn; 6 cooldown.
The Stop-output form is the builder's choice from the docs: these tests accept either documented form."""
import json, os, re, shutil, stat, sys, unittest

from guard_common import (G, GUARD_LINE1, HEALTH_KEYS, KEY, chain, guard_text, SID1, ts, entry, bash_call, mcp_call,
                          tool_result, injection, usage_entry, HIST_LINE1, ENTRY_RE)

REPLY = "The queue-depth is 10, as you asked."


class Trigger(G):
    def test_f77_fires_on_a_changed_subject_with_line_one_then_the_f73_block(self):
        self.tx(chain(KEY, 2, 1))
        out = self.stop(REPLY)
        ls = out.split("\n")
        self.assertEqual(ls[0], GUARD_LINE1)
        self.assertEqual(ls[1], HIST_LINE1 % (KEY, 3))
        self.assertEqual(len([l for l in ls if ENTRY_RE.match(l)]), 3)
        steps = [int(re.search(r"step (\d)", l).group(1)) for l in ls if ENTRY_RE.match(l)]
        self.assertEqual(steps, [0, 1, 2], "oldest first")

    def test_f77_stop_hook_active_true_gives_no_output(self):
        self.tx(chain(KEY, 2, 1))
        self.assertEqual(self.stop(REPLY, stop_hook_active=True), "")

    def test_f77_a_second_stop_after_a_block_in_the_same_turn_gives_no_output(self):
        recs = chain("alpha-one", 2, 1) + chain("beta-two", 2, 1, start=5)
        self.tx(recs)
        self.assertNotEqual(self.stop("alpha-one is 10"), "")
        self.assertEqual(self.stop("beta-two is 10"), "", "the guard blocked once in this user turn")

    def test_f77_a_new_user_turn_allows_a_new_block(self):
        recs = chain("alpha-one", 2, 1) + chain("beta-two", 2, 1, start=5)
        self.tx(recs)
        self.assertNotEqual(self.stop("alpha-one is 10"), "")
        self.tx(recs, prompt="a second, different request")
        self.assertNotEqual(self.stop("beta-two is 10"), "")


class Threshold(G):
    def test_f77_below_100000_tokens_gives_no_output_and_at_100000_fires(self):
        self.tx(chain(KEY, 2, 1), tokens=99999)
        self.assertEqual(self.stop(REPLY), "")
        self.tx(chain(KEY, 2, 1), tokens=100000)
        self.assertNotEqual(self.stop(REPLY), "")

    def test_f77_the_context_count_adds_the_cache_fields(self):
        self.tx(chain(KEY, 2, 1), tokens=None)
        recs = chain(KEY, 2, 1) + [usage_entry(150000, split=True, ts="2026-03-01T13:00:00Z")]
        self.tx(recs, tokens=None)
        self.assertNotEqual(self.stop(REPLY), "")

    def test_f77_a_usage_entry_with_a_total_of_zero_is_skipped(self):
        recs = chain(KEY, 2, 1) + [usage_entry(150000, ts="2026-03-01T13:00:00Z"), usage_entry(0, ts="2026-03-01T13:01:00Z")]
        self.tx(recs, tokens=None)
        self.assertNotEqual(self.stop(REPLY), "")

    def test_f77_no_usage_entry_means_no_output(self):
        self.tx(chain(KEY, 2, 1), tokens=None)
        self.assertEqual(self.stop(REPLY), "")

    def test_f77_env_override_lowers_and_raises_the_threshold(self):
        self.tx(chain(KEY, 2, 1), tokens=30000)
        self.assertEqual(self.stop(REPLY), "")
        self.assertNotEqual(self.stop(REPLY, extra={"HANDOFF_HISTORY_GUARD_TOKENS": "20000"}), "")
        self.tx(chain(KEY, 2, 1), tokens=150000)
        self.assertEqual(self.stop(REPLY, extra={"HANDOFF_HISTORY_GUARD_TOKENS": "200000"}), "")

    def test_f77_an_override_outside_10000_to_1000000_is_ignored(self):
        self.tx(chain(KEY, 2, 1), tokens=50000)
        for v in ("5000", "2000000", "abc", ""):
            with self.subTest(v):
                self.assertEqual(self.stop(REPLY, extra={"HANDOFF_HISTORY_GUARD_TOKENS": v}), "", "the default 100,000 applies")


class Subjects(G):
    def test_f77_a_fact_stated_one_time_does_not_fire(self):
        self.tx(chain(KEY, 1, 0))
        self.assertEqual(self.stop(REPLY), "")

    def test_f77_two_user_messages_are_enough_and_two_messages_with_one_user_are_not(self):
        self.tx(chain(KEY, 2, 0))
        self.assertNotEqual(self.stop(REPLY), "")
        self.tx(chain(KEY, 1, 1))
        self.assertEqual(self.stop(REPLY), "", "at least 2 of the messages must be from the user")
        self.tx(chain(KEY, 0, 3))
        self.assertEqual(self.stop(REPLY), "")

    def test_f77_40_text_messages_are_a_subject_and_41_are_not(self):
        self.tx(chain(KEY, 20, 20))
        self.assertNotEqual(self.stop(REPLY), "")
        self.tx(chain(KEY, 21, 20))
        self.assertEqual(self.stop(REPLY), "")

    def test_f77_tool_inputs_and_results_are_not_text_messages(self):
        recs = chain(KEY, 1, 0) + [bash_call("echo queue-depth", "b1", ts(5), tid="t1"),
                                   tool_result("queue-depth is 10", "r1", ts(6), tid="t1"),
                                   bash_call("echo queue-depth again", "b2", ts(7), tid="t2"),
                                   tool_result("queue-depth is 20", "r2", ts(8), tid="t2")]
        self.tx(recs)
        self.assertEqual(self.stop(REPLY), "")

    def test_f77_recall_output_is_not_a_text_message(self):
        recs = chain(KEY, 1, 0) + [injection("Lossless Handoff auto-recall: history of queue-depth: 2 mention(s) queue-depth",
                                             "i1", ts(5))]
        self.tx(recs)
        self.assertEqual(self.stop(REPLY), "")

    def test_f77_mentions_after_the_current_prompt_do_not_count(self):
        self.tx(chain(KEY, 1, 0), tail=[entry("assistant", "queue-depth is now 10 after the prompt", "t1", ts(1, day=2))])
        self.assertEqual(self.stop(REPLY), "")

    def test_f77_sibling_keys_are_not_the_subject(self):
        self.tx(chain(KEY, 2, 1))
        self.assertEqual(self.stop("The queue-depth-eu is 10 and queue-depth.v2 is 20."), "")

    def test_f77_the_first_4_subjects_in_reply_order(self):
        recs = []
        for i, k in enumerate(("k-one", "k-two", "k-three", "k-four", "k-five")):
            recs += chain(k, 2, 1, start=i * 4)
        self.tx(recs)
        out = self.stop("Values: k-two is 1, k-one is 2, k-five is 3, k-three is 4, k-four is 5.")
        self.assertEqual(self.blocks(out), ["k-two", "k-one", "k-five", "k-three"])
        self.assertNotIn("k-four", out)

    def test_f77_a_reply_with_no_identifier_gives_no_output(self):
        self.tx(chain(KEY, 2, 1))
        self.assertEqual(self.stop("All done, nothing else to add."), "")

    def test_f77_backticked_tokens_are_identifiers(self):
        self.tx(chain("Zeta", 2, 1))
        self.assertNotEqual(self.stop("The `Zeta` is 10."), "")


class Anchor(G):
    def test_f77_an_anchor_in_a_tool_input_of_this_turn_does_not_count(self):
        self.tx(chain(KEY, 2, 1), tail=[bash_call("grep -n queue-depth config.txt", "b1", ts(1, day=2), tid="t1")])
        self.assertEqual(self.stop(REPLY), "")

    def test_f77_an_anchor_in_a_tool_result_of_this_turn_does_not_count(self):
        self.tx(chain(KEY, 2, 1), tail=[bash_call("cat notes.txt", "b1", ts(1, day=2), tid="t1"),
                                        tool_result("queue-depth = 10", "r1", ts(2, day=2), tid="t1")])
        self.assertEqual(self.stop(REPLY), "")

    def test_f77_control_a_tool_input_before_the_current_prompt_does_not_suppress(self):
        recs = chain(KEY, 2, 1) + [bash_call("grep -n queue-depth config.txt", "b1", ts(30), tid="t1")]
        self.tx(recs)
        self.assertNotEqual(self.stop(REPLY), "")

    def test_f77_an_existing_path_below_cwd_is_not_an_anchor(self):
        os.makedirs(os.path.join(self.proj, "conf"))
        open(os.path.join(self.proj, "conf", "queue-depth.yaml"), "w").close()
        recs = chain("conf/queue-depth.yaml", 2, 1)
        self.tx(recs)
        self.assertEqual(self.stop("I edited conf/queue-depth.yaml for you."), "")

    def test_f77_control_a_path_that_does_not_exist_is_an_anchor(self):
        self.tx(chain("conf/queue-depth.yaml", 2, 1))
        self.assertNotEqual(self.stop("I edited conf/queue-depth.yaml for you."), "")

    def test_f77_a_value_with_no_key_anchors_through_the_sentence(self):
        recs = chain("filler-a", 1, 0)  # keeps the chat longer
        recs += [entry("user", "Set queue-depth to AB12-9Z for now", "u1", ts(10)),
                 entry("assistant", "Done: queue-depth is fine.", "a1", ts(11)),
                 entry("user", "Use queue-depth with care in staging", "u2", ts(12))]
        self.tx(recs)
        out = self.stop("The value is AB12-9Z.")
        self.assertEqual(self.blocks(out), ["queue-depth"], out)

    def test_f77_a_value_with_no_earlier_mention_gives_no_output(self):
        self.tx(chain(KEY, 2, 1))
        self.assertEqual(self.stop("The value is ZZ99-9Q."), "")


class Evidence(G):
    def test_f77_a_recall_history_call_in_this_turn_suppresses(self):
        self.tx(chain(KEY, 2, 1), tail=[bash_call("python3 ~/.claude/hooks/recall.py history queue-depth", "b1",
                                                 ts(1, day=2), tid="t1"),
                                        tool_result("history of queue-depth: 3 mention(s)", "r1", ts(2, day=2), tid="t1")])
        self.assertEqual(self.stop(REPLY), "")

    def test_f77_a_key_history_tool_call_in_this_turn_suppresses(self):
        self.tx(chain(KEY, 2, 1), tail=[mcp_call("mcp__lossless-recall__key_history", {"identifier": "queue-depth"}, "m1",
                                                ts(1, day=2), tid="t1"),
                                        tool_result("history of queue-depth: 3 mention(s)", "r1", ts(2, day=2), tid="t1")])
        self.assertEqual(self.stop(REPLY), "")

    def test_f77_an_injected_history_block_in_this_turn_suppresses(self):
        self.tx(chain(KEY, 2, 1), tail=[injection("Lossless Handoff auto-recall: the history of the identifiers in your "
                                                  "prompt, oldest first.\nhistory of queue-depth: 3 mention(s), oldest first.",
                                                  "i1", ts(1, day=2))])
        self.assertEqual(self.stop(REPLY), "")

    def test_f77_evidence_for_another_subject_does_not_suppress(self):
        self.tx(chain(KEY, 2, 1), tail=[bash_call("python3 ~/.claude/hooks/recall.py history other-key", "b1",
                                                 ts(1, day=2), tid="t1")])
        self.assertNotEqual(self.stop(REPLY), "")

    def test_f77_evidence_before_the_current_prompt_does_not_suppress(self):
        recs = chain(KEY, 2, 1) + [bash_call("python3 ~/.claude/hooks/recall.py history queue-depth", "b1", ts(30), tid="t1")]
        self.tx(recs)
        self.assertNotEqual(self.stop(REPLY), "")


class Cooldown(G):
    def test_f77_the_same_subject_is_not_shown_twice(self):
        self.tx(chain(KEY, 2, 1))
        self.assertNotEqual(self.stop(REPLY), "")
        self.tx(chain(KEY, 2, 1), prompt="another request")
        self.assertEqual(self.stop(REPLY), "", "no new mention and no context growth")

    def test_f77_a_new_mention_ends_the_cooldown(self):
        self.tx(chain(KEY, 2, 1))
        self.assertNotEqual(self.stop(REPLY), "")
        self.tx(chain(KEY, 2, 1) + [entry("user", "queue-depth is now 99", "new1", ts(40))], prompt="another request")
        out = self.stop(REPLY)
        self.assertEqual(out.split("\n")[1], HIST_LINE1 % (KEY, 4))

    def test_f77_context_growth_of_50000_ends_the_cooldown(self):
        self.tx(chain(KEY, 2, 1), tokens=150000)
        self.assertNotEqual(self.stop(REPLY), "")
        self.tx(chain(KEY, 2, 1), tokens=190000, prompt="another request")
        self.assertEqual(self.stop(REPLY), "")
        self.tx(chain(KEY, 2, 1), tokens=200000, prompt="a third request")
        self.assertNotEqual(self.stop(REPLY), "")


class Modes(G):
    def test_f77_unset_and_shadow_give_no_output_but_log_a_row(self):
        for mode in (None, "shadow"):
            with self.subTest(mode):
                self.tx(chain(KEY, 2, 1), prompt="request %s" % mode)
                self.assertEqual(self.stop(REPLY, mode=mode, extra={"HANDOFF_STATE_DIR": os.path.join(self.tmp, "s-%s" % mode)}), "")
                rows = [json.loads(l) for l in open(os.path.join(self.tmp, "s-%s" % mode, "history-guard.jsonl"))]
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["mode"], "shadow")
                self.assertIs(rows[0]["fired"], True)

    def test_f77_block_gives_output_and_a_block_row(self):
        self.tx(chain(KEY, 2, 1))
        out = self.stop(REPLY)
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["mode"], "block")
        self.assertEqual(rows[0]["chars"], len(out))

    def test_f77_mode_0_gives_no_output_and_no_row_and_no_state(self):
        self.tx(chain(KEY, 2, 1))
        self.assertEqual(self.stop(REPLY, mode="0"), "")
        self.assertEqual(self.rows(), [])
        self.assertFalse(os.path.isdir(self.state) and any(f.startswith("history-guard") for f in os.listdir(self.state)))

    def test_f77_unknown_mode_values_do_not_block(self):
        self.tx(chain(KEY, 2, 1))
        self.assertEqual(self.stop(REPLY, mode="yes"), "")


class Output(G):
    def test_f77_stdout_is_the_documented_stop_form(self):
        self.tx(chain(KEY, 2, 1))
        raw = self.run_stop(REPLY, extra={"HANDOFF_HISTORY_GUARD": "block"})
        o = json.loads(raw)
        self.assertEqual(set(o), {"hookSpecificOutput"}, raw[:300])
        self.assertEqual(o["hookSpecificOutput"]["hookEventName"], "Stop")
        self.assertEqual(set(o["hookSpecificOutput"]), {"hookEventName", "additionalContext"})
        self.assertEqual(len(raw.strip().split("\n")), 1, "one JSON line")

    def test_f77_caps_1500_per_subject_and_6000_in_total(self):
        recs = []
        for i, k in enumerate(("k-one", "k-two", "k-three", "k-four", "k-five")):
            recs += [entry("user" if j % 2 == 0 else "assistant", "%s step %02d %s" % (k, j, "x" * 100), "%s-%d" % (k, j),
                           ts((i * 8 + j) % 60, hour=1 + (i * 8 + j) // 60)) for j in range(30)]
        self.tx(recs)
        out = self.stop("k-one is 1, k-two is 2, k-three is 3, k-four is 4, k-five is 5.")
        ls = out.split("\n")
        self.assertEqual(ls[0], GUARD_LINE1)
        body = ls[1:]
        starts = [i for i, l in enumerate(body) if l.startswith("history of ")]
        self.assertLessEqual(len(starts), 4)
        self.assertGreaterEqual(len(starts), 1)
        total = 0
        for a, b in zip(starts, starts[1:] + [len(body)]):
            block = "\n".join(body[a:b])
            self.assertLessEqual(len(block), 1500, len(block))
            total += len(block)
        self.assertLessEqual(total, 6000)
        self.assertTrue(any(l.startswith("[") and "omitted in the middle" in l for l in body), "30 long mentions are cut")


class Health(G):
    def test_f77_row_fields_and_no_text(self):
        self.tx(chain(KEY, 2, 1), tokens=123456)
        out = self.stop("The queue-depth is 10 and SECRETREPLYWORD stays.")
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(set(r), HEALTH_KEYS, r)
        self.assertEqual((r["session_id"], r["fired"], r["subjects"], r["tokens"]), (SID1, True, 1, 123456))
        self.assertGreaterEqual(r["anchors"], 1)
        self.assertTrue(isinstance(r["ms"], int) and isinstance(r["chars"], int) and isinstance(r["ts"], str))
        raw = open(os.path.join(self.state, "history-guard.jsonl")).read()
        for w in ("queue-depth", "queue", "SECRETREPLYWORD", "step"):
            self.assertNotIn(w, raw)

    def test_f77_files_have_mode_0600(self):
        self.tx(chain(KEY, 2, 1))
        self.stop(REPLY)
        for n in ("history-guard.jsonl", "history-guard-%s.json" % SID1):
            p = os.path.join(self.state, n)
            self.assertTrue(os.path.exists(p), n)
            self.assertEqual(self.mode_of(p), 0o600, n)

    def test_f77_handoff_state_dir_decides_where_the_files_go(self):
        self.tx(chain(KEY, 2, 1))
        self.stop(REPLY)
        self.assertTrue(os.path.exists(os.path.join(self.state, "history-guard.jsonl")))
        self.assertFalse(os.path.exists(os.path.join(self.hd, "history-guard.jsonl")))

    def test_f77_default_state_dir_is_the_claude_handoffs_folder(self):
        self.tx(chain(KEY, 2, 1))
        import subprocess, time
        p = {"session_id": SID1, "transcript_path": self.session, "cwd": self.proj, "hook_event_name": "Stop",
             "stop_hook_active": False, "last_assistant_message": REPLY}
        r = subprocess.run([sys.executable, os.path.join(self.hooks, "history-guard.py")], input=json.dumps(p),
                           capture_output=True, text=True, env=self.env({"HANDOFF_HISTORY_GUARD": "block"}), cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.hd, "history-guard.jsonl")))


class HooksHome(G):
    def test_f77_a_decoy_recall_py_beside_the_entry_file_is_not_used_when_the_override_names_a_folder(self):
        self.tx(chain(KEY, 2, 1))
        real = os.path.join(self.tmp, "real-hooks")
        shutil.copytree(self.hooks, real)
        trace = os.path.join(self.tmp, "decoy.trace")
        with open(os.path.join(self.hooks, "recall.py"), "w") as f:
            f.write("import os\nopen(os.environ['DECOY_TRACE'], 'w').write('used')\nraise SystemExit(0)\n")
        out = self.stop(REPLY, extra={"HANDOFF_HOOKS_HOME": real, "DECOY_TRACE": trace})
        self.assertFalse(os.path.exists(trace), "the guard used the decoy beside the entry file")
        self.assertNotEqual(out, "", "the real folder named by HANDOFF_HOOKS_HOME works")


class Errors(G):
    def test_f77_bad_input_gives_no_output_and_exit_0(self):
        self.tx(chain(KEY, 2, 1))
        for raw in ("{not json", "", "[]", "{}", json.dumps({"last_assistant_message": 5, "transcript_path": 7})):
            with self.subTest(raw[:12]):
                self.assertEqual(guard_text(self.run_stop("x", raw=raw, extra={"HANDOFF_HISTORY_GUARD": "block"})), "")

    def test_f77_missing_or_broken_transcript_gives_no_output(self):
        self.assertEqual(self.stop(REPLY, payload={"transcript_path": os.path.join(self.tmp, "none.jsonl")}), "")
        with open(self.session, "w") as f:
            f.write("{broken\n\x00\x01 not json\n")
        self.assertEqual(self.stop(REPLY), "")

    def test_f77_runs_within_the_budget_on_a_long_chat(self):
        recs = chain(KEY, 2, 1)
        recs += [entry("user" if i % 2 else "assistant", "filler message %d about other things" % i, "f%d" % i,
                       ts(i % 60, hour=2 + i // 60)) for i in range(3000)]
        self.tx(recs)
        self.stop(REPLY)
        self.assertLess(self.elapsed, 5.0)


if __name__ == "__main__":
    unittest.main()
