"""F80 Action guard: `hooks/action-guard.py`, opt-in, shadow by default. Code-blind: written from contract-0.18.md.
It scans the tool_input of Edit, Write, MultiEdit, NotebookEdit (new text, not old_string) and the Bash command for
identifiers (F75 rule, first 60; not existing paths below cwd, not the file_path field). Subjects, evidence, cooldown,
threshold (100,000 tokens, env HANDOFF_ACTION_GUARD_TOKENS), the 4-subject limit and the caps are the same as F77, and F77
and F80 share one cooldown table. The event (PostToolBatch or the PostToolUse fallback) is the builder's choice: the
payload here carries both the single-call fields and a `tool_calls` list, and the output is accepted in either documented
form. Set ACTION_GUARD_EVENT=PostToolBatch to send that event name."""
import json, os, re, sys, unittest

from guard_common import (G, ACTION_LINE1, GUARD_LINE1, HEALTH_KEYS, KEY, chain, guard_text, SID1, ts, entry, bash_call,
                          mcp_call, tool_result, injection, usage_entry, HIST_LINE1, ENTRY_RE)

HK = HEALTH_KEYS | {"tool"}


class Scan(G):
    def setUp(self):
        super().setUp()
        self.tx(chain(KEY, 2, 1))

    def test_f80_write_content_with_a_changed_name_fires_with_line_one_and_the_f73_block(self):
        out = self.act("Write", {"file_path": os.path.join(self.proj, "out", "x.conf"), "content": "queue-depth=10\n"})
        ls = out.split("\n")
        self.assertEqual(ls[0], ACTION_LINE1)
        self.assertEqual(ls[1], HIST_LINE1 % (KEY, 3))
        self.assertEqual(len([l for l in ls if ENTRY_RE.match(l)]), 3)

    def test_f80_each_scanned_tool_and_field(self):
        cases = [("Edit", {"file_path": "/x/a.conf", "old_string": "a", "new_string": "queue-depth=10"}),
                 ("MultiEdit", {"file_path": "/x/a.conf", "edits": [{"old_string": "a", "new_string": "queue-depth=10"}]}),
                 ("NotebookEdit", {"notebook_path": "/x/a.ipynb", "new_source": "queue_depth = 10  # queue-depth"}),
                 ("Bash", {"command": "echo queue-depth=10 > out.conf"})]
        for tool, inp in cases:
            with self.subTest(tool):
                self.tx(chain(KEY, 2, 1), prompt="request for %s" % tool)
                out = self.act(tool, inp, extra={"HANDOFF_STATE_DIR": os.path.join(self.tmp, "s-" + tool)})
                self.assertEqual(self.blocks(out), [KEY], out)

    def test_f80_old_string_is_not_scanned(self):
        self.assertEqual(self.act("Edit", {"file_path": "/x/a.conf", "old_string": "queue-depth=1", "new_string": "limit=10"}), "")

    def test_f80_the_file_path_field_is_not_scanned(self):
        self.assertEqual(self.act("Write", {"file_path": os.path.join(self.proj, "out", "queue-depth.conf"),
                                            "content": "limit=10\n"}), "")

    def test_f80_other_tools_are_ignored(self):
        for tool, inp in (("Read", {"file_path": "/x/queue-depth.txt"}), ("Grep", {"pattern": "queue-depth"}),
                          ("Glob", {"pattern": "**/queue-depth*"}), ("WebFetch", {"url": "https://e.com/queue-depth"})):
            with self.subTest(tool):
                self.assertEqual(self.act(tool, inp), "")

    def test_f80_an_existing_path_below_cwd_is_not_an_anchor(self):
        os.makedirs(os.path.join(self.proj, "conf"))
        open(os.path.join(self.proj, "conf", "queue-depth.yaml"), "w").close()
        self.tx(chain("conf/queue-depth.yaml", 2, 1))
        self.assertEqual(self.act("Bash", {"command": "cat conf/queue-depth.yaml"}), "")

    def test_f80_control_a_missing_path_is_an_anchor(self):
        self.tx(chain("conf/queue-depth.yaml", 2, 1))
        self.assertNotEqual(self.act("Bash", {"command": "cat conf/queue-depth.yaml"}), "")

    def test_f80_a_sibling_key_is_not_a_subject(self):
        self.assertEqual(self.act("Bash", {"command": "echo queue-depth-eu=1 queue-depth.v2=2"}), "")

    def test_f80_a_name_stated_one_time_is_not_a_subject(self):
        self.tx(chain(KEY, 1, 0))
        self.assertEqual(self.act("Bash", {"command": "echo queue-depth=10"}), "")

    def test_f80_the_first_4_subjects_and_the_caps(self):
        recs = []
        for i, k in enumerate(("k-one", "k-two", "k-three", "k-four", "k-five")):
            recs += [entry("user" if j % 2 == 0 else "assistant", "%s step %02d %s" % (k, j, "x" * 100), "%s-%d" % (k, j),
                           ts((i * 8 + j) % 60, hour=1 + (i * 8 + j) // 60)) for j in range(30)]
        self.tx(recs)
        out = self.act("Bash", {"command": "set k-three=1 k-one=2 k-five=3 k-two=4 k-four=5"})
        self.assertEqual(out.split("\n")[0], ACTION_LINE1)
        ls = out.split("\n")[1:]
        starts = [i for i, l in enumerate(ls) if l.startswith("history of ")]
        self.assertLessEqual(len(starts), 4)
        self.assertEqual(self.blocks(out), ["k-three", "k-one", "k-five", "k-two"][:len(starts)])
        tot = 0
        for a, b in zip(starts, starts[1:] + [len(ls)]):
            blk = "\n".join(ls[a:b])
            self.assertLessEqual(len(blk), 1500)
            tot += len(blk)
        self.assertLessEqual(tot, 6000)


class Gates(G):
    def test_f80_threshold_100000_and_the_env_override(self):
        self.tx(chain(KEY, 2, 1), tokens=99999)
        self.assertEqual(self.act("Bash", {"command": "echo queue-depth=1"}), "")
        self.tx(chain(KEY, 2, 1), tokens=100000)
        self.assertNotEqual(self.act("Bash", {"command": "echo queue-depth=1"}), "")
        self.tx(chain(KEY, 2, 1), tokens=30000, prompt="again")
        self.assertEqual(self.act("Bash", {"command": "echo queue-depth=1"}), "")
        self.assertNotEqual(self.act("Bash", {"command": "echo queue-depth=1"}, extra={"HANDOFF_ACTION_GUARD_TOKENS": "20000"}), "")

    def test_f80_the_f77_env_does_not_set_the_f80_threshold(self):
        self.tx(chain(KEY, 2, 1), tokens=30000)
        self.assertEqual(self.act("Bash", {"command": "echo queue-depth=1"}, extra={"HANDOFF_HISTORY_GUARD_TOKENS": "20000"}), "")

    def test_f80_evidence_in_this_turn_suppresses(self):
        self.tx(chain(KEY, 2, 1), tail=[bash_call("python3 ~/.claude/hooks/recall.py history queue-depth", "b1",
                                                 ts(1, day=2), tid="t1")])
        self.assertEqual(self.act("Bash", {"command": "echo queue-depth=1"}), "")
        self.tx(chain(KEY, 2, 1), tail=[mcp_call("mcp__lossless-recall__key_history", {"identifier": "queue-depth"}, "m1",
                                                ts(1, day=2), tid="t1")], prompt="p2")
        self.assertEqual(self.act("Bash", {"command": "echo queue-depth=1"}), "")

    def test_f80_the_same_subject_is_not_shown_twice(self):
        self.tx(chain(KEY, 2, 1))
        self.assertNotEqual(self.act("Bash", {"command": "echo queue-depth=1"}), "")
        self.assertEqual(self.act("Bash", {"command": "echo queue-depth=2"}), "")

    def test_f80_a_new_mention_or_50000_more_tokens_ends_the_cooldown(self):
        self.tx(chain(KEY, 2, 1), tokens=150000)
        self.assertNotEqual(self.act("Bash", {"command": "echo queue-depth=1"}), "")
        self.tx(chain(KEY, 2, 1) + [entry("user", "queue-depth is now 77", "n1", ts(40))], tokens=150000, prompt="p2")
        self.assertNotEqual(self.act("Bash", {"command": "echo queue-depth=1"}), "")
        self.tx(chain(KEY, 2, 1) + [entry("user", "queue-depth is now 77", "n1", ts(40))], tokens=210000, prompt="p3")
        self.assertNotEqual(self.act("Bash", {"command": "echo queue-depth=1"}), "")

    def test_f80_the_cooldown_is_shared_with_f77_in_both_directions(self):
        self.tx(chain(KEY, 2, 1))
        self.assertNotEqual(self.stop("The queue-depth is 10."), "")
        self.assertEqual(self.act("Bash", {"command": "echo queue-depth=1"}), "", "F77 showed it first")
        self.tx(chain("other-key", 2, 1), prompt="next request")
        self.assertNotEqual(self.act("Bash", {"command": "echo other-key=1"}), "")
        self.assertEqual(self.stop("The other-key is 10."), "", "F80 showed it first")

    def test_f80_unlike_f77_a_second_call_in_a_turn_with_a_new_subject_still_fires(self):
        self.tx(chain("alpha-one", 2, 1) + chain("beta-two", 2, 1, start=5))
        self.assertNotEqual(self.act("Bash", {"command": "echo alpha-one=1"}), "")
        self.assertNotEqual(self.act("Bash", {"command": "echo beta-two=1"}), "")


class Modes(G):
    def setUp(self):
        super().setUp()
        self.tx(chain(KEY, 2, 1))
        self.cmd = {"command": "echo queue-depth=1"}

    def test_f80_unset_and_shadow_log_only(self):
        for mode in (None, "shadow"):
            with self.subTest(mode):
                d = os.path.join(self.tmp, "s-%s" % mode)
                self.assertEqual(self.act("Bash", self.cmd, mode=mode, extra={"HANDOFF_STATE_DIR": d}), "")
                rows = [json.loads(l) for l in open(os.path.join(d, "action-guard.jsonl"))]
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["mode"], "shadow")

    def test_f80_inject_logs_and_outputs(self):
        out = self.act("Bash", self.cmd)
        rows = self.rows("action-guard.jsonl")
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["mode"], rows[0]["chars"]), ("inject", len(out)))

    def test_f80_mode_0_gives_nothing(self):
        self.assertEqual(self.act("Bash", self.cmd, mode="0"), "")
        self.assertEqual(self.rows("action-guard.jsonl"), [])

    def test_f80_it_never_denies_or_blocks_a_tool_call(self):
        raw = self.run_action("Bash", self.cmd, extra={"HANDOFF_ACTION_GUARD": "inject"})
        self.assertNotIn("permissionDecision", raw)
        self.assertNotIn('"deny"', raw)
        o = json.loads(raw)
        self.assertIsInstance(o, dict)

    def test_f80_health_row_has_the_f77_fields_plus_tool_and_no_text(self):
        self.act("Bash", {"command": "echo queue-depth=1 SECRETCMDWORD"})
        r = self.rows("action-guard.jsonl")[0]
        self.assertEqual(set(r), HK, r)
        self.assertEqual((r["tool"], r["fired"], r["subjects"], r["session_id"]), ("Bash", True, 1, SID1))
        raw = open(os.path.join(self.state, "action-guard.jsonl")).read()
        for w in ("queue-depth", "SECRETCMDWORD", "echo"):
            self.assertNotIn(w, raw)

    def test_f80_files_have_mode_0600_and_follow_handoff_state_dir(self):
        self.act("Bash", self.cmd)
        p = os.path.join(self.state, "action-guard.jsonl")
        self.assertEqual(self.mode_of(p), 0o600)
        self.assertFalse(os.path.exists(os.path.join(self.hd, "action-guard.jsonl")))


class HooksHome(G):
    def test_f80_recall_py_comes_from_handoff_hooks_home_with_no_fallback(self):
        self.tx(chain(KEY, 2, 1))
        empty = os.path.join(self.tmp, "empty-hooks")
        os.makedirs(empty)
        self.assertEqual(self.act("Bash", {"command": "echo queue-depth=1"}, extra={"HANDOFF_HOOKS_HOME": empty}), "")
        self.assertNotEqual(self.act("Bash", {"command": "echo queue-depth=1"}, extra={"HANDOFF_HOOKS_HOME": self.hooks}), "")


class Errors(G):
    def test_f80_bad_input_gives_no_output_and_exit_0(self):
        self.tx(chain(KEY, 2, 1))
        for raw in ("{not json", "", "[]", "{}", json.dumps({"tool_name": 5, "tool_input": "x", "transcript_path": 3})):
            with self.subTest(raw[:12]):
                self.assertEqual(guard_text(self.run_action("Bash", {}, raw=raw, extra={"HANDOFF_ACTION_GUARD": "inject"})), "")

    def test_f80_missing_transcript_gives_no_output(self):
        self.assertEqual(self.act("Bash", {"command": "echo queue-depth=1"},
                                  payload={"transcript_path": os.path.join(self.tmp, "none.jsonl")}), "")

    def test_f80_a_huge_tool_input_runs_inside_the_budget(self):
        self.tx(chain(KEY, 2, 1))
        self.act("Write", {"file_path": "/x/a.txt", "content": " ".join("tok-%d.x" % i for i in range(60000))})
        self.assertLess(self.elapsed, 5.0)


if __name__ == "__main__":
    unittest.main()
