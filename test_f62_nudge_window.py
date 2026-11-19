"""F62 Nudge window source (code-blind: written from the contract and the README, docs/spec.md, docs/architecture.md).
Order: (1) CLAUDE_CODE_AUTO_COMPACT_WINDOW if a positive integer; (2) learned from the pre-compaction token counts of
the newest compact_boundary records (up to 20) of the current transcript, else of the other transcripts in the same
project folder; the window is the median plus 33,000, rounded to the nearest 1,000; (3) 200,000.
Thresholds: first reminder at 75% of the window, then every 25,000; final nudge at window minus 45,000. The meta file
holds `window` and `windowSource` ("env", "learned", "default").
F62.c: the nudge writes `window` and `windowSource` to <sid>-agent.meta.json; the next PreCompact health row copies
them as `window` and `window_source`.
Temp HOME. The hook is run from HANDOFF_HOOKS_DIR with a PostToolUse input."""
import json, os, subprocess, sys, time, unittest

from helpers import HookCase, HOOKS_DIR

NUDGE = os.path.join(HOOKS_DIR, "handoff-nudge.py")
ENV = "CLAUDE_CODE_AUTO_COMPACT_WINDOW"
FINAL = "Compaction is imminent"
SLUG = "-proj-f62"


def boundary(pre, k=0):
    return {"type": "system", "subtype": "compact_boundary", "content": "Conversation compacted",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 86400 - 1000 + k)),
            "compactMetadata": {"trigger": "auto", "preTokens": pre}}


def usage_entry(ctx):
    return {"type": "assistant", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "message": {"role": "assistant", "content": [{"type": "text", "text": "working"}],
                        "usage": {"input_tokens": ctx, "cache_creation_input_tokens": 0,
                                  "cache_read_input_tokens": 0, "output_tokens": 0}}}


class NudgeBase(HookCase):
    def setUp(self):
        super().setUp()
        self.proj = os.path.join(self.home, ".claude", "projects", SLUG)
        os.makedirs(self.proj)
        self.n = 0
        self.last_sid = None

    def write_t(self, name, recs, age_s=0):
        p = os.path.join(self.proj, name + ".jsonl")
        with open(p, "w") as f:
            f.write(json.dumps({"type": "user", "message": {"content": "Please keep going on the task"}}) + "\n")
            for r in recs:
                f.write(json.dumps(r) + "\n")
        if age_s:
            t = time.time() - age_s
            os.utime(p, (t, t))
        return p

    def boundaries(self, counts):
        return [boundary(c, i) for i, c in enumerate(counts)]

    def probe(self, ctx, window=None, history=(), sid=None, sibling=None, other_project=None):
        """Run the nudge for a fresh (or given) session whose last usage entry shows `ctx` tokens. Returns stdout."""
        if sid is None:
            self.n += 1
            sid = "f62%05d-0000-4000-8000-000000000001" % self.n
        self.last_sid = sid
        recs = self.boundaries(history) + [usage_entry(ctx)]
        tp = self.write_t(sid, recs)
        if sibling is not None:
            self.write_t("f62sibling-0000-4000-8000-000000000009", self.boundaries(sibling), age_s=3600)
        if other_project is not None:
            d = os.path.join(self.home, ".claude", "projects", "-proj-other")
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "other.jsonl"), "w") as f:
                for r in self.boundaries(other_project):
                    f.write(json.dumps(r) + "\n")
        extra = {}
        if window is not None:
            extra[ENV] = window
        payload = {"session_id": sid, "transcript_path": tp, "cwd": self.tmp, "hook_event_name": "PostToolUse",
                   "tool_name": "Bash", "tool_input": {"command": "ls"}, "tool_response": {"stdout": "x"}}
        r = subprocess.run([sys.executable, NUDGE], input=json.dumps(payload), capture_output=True, text=True,
                           env=self.env(None, extra), timeout=30)
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout)
        return r.stdout

    def assertNudge(self, out, msg=""):
        self.assertTrue(out.strip(), "expected a nudge, got no output. " + msg)

    def assertNoNudge(self, out, msg=""):
        self.assertEqual(out.strip(), "", "expected no nudge. " + msg)

    def meta(self, sid=None):
        """<sid>-agent.meta.json of the last probed session (F62.c: the nudge writes `window` and `windowSource`)."""
        p = os.path.join(self.hd, (sid or self.last_sid) + "-agent.meta.json")
        self.assertTrue(os.path.exists(p), "no meta file %s" % p)
        with open(p) as f:
            return json.load(f)

    def assertWindow(self, window, source, sid=None):
        m = self.meta(sid)
        self.assertEqual((m.get("window"), m.get("windowSource")), (window, source), m)


# ---------------------------------------------------------------- (1) env wins
class EnvWindow(NudgeBase):
    def test_f62_env_valid_sets_window_and_source(self):
        self.assertNoNudge(self.probe(250000, window="400000"), "250k is below 75% of 400k")
        self.assertNudge(self.probe(301000, window="400000"), "301k is above 75% of 400k")
        self.assertWindow(400000, "env")

    def test_f62_env_valid_beats_history(self):
        # history would give 167000 + 33000 = 200000; the env value must win
        out = self.probe(250000, window="400000", history=[167000, 167000, 167000])
        self.assertNoNudge(out)
        self.assertNudge(self.probe(301000, window="400000", history=[167000, 167000, 167000]))
        self.assertWindow(400000, "env")

    def test_f62_env_valid_small_window_keeps_old_thresholds(self):
        self.assertNoNudge(self.probe(224000, window="300000"))
        self.assertNudge(self.probe(226000, window="300000"))
        self.assertWindow(300000, "env")


# ---------------------------------------------------------------- (2) learned
class Learned(NudgeBase):
    HISTORY = [367000, 367000, 368000]

    def check_learned(self, window):
        self.assertNoNudge(self.probe(250000, window=window, history=self.HISTORY),
                           "250k: learned window is 400k, first reminder at 300k")
        self.assertNoNudge(self.probe(299000, window=window, history=self.HISTORY))
        self.assertNudge(self.probe(301000, window=window, history=self.HISTORY))
        self.assertWindow(400000, "learned")

    def test_f62_env_unset_learns_window(self):
        self.check_learned(None)

    def test_f62_env_empty_learns_window(self):
        self.check_learned("")

    def test_f62_env_abc_learns_window(self):
        self.check_learned("abc")

    def test_f62_env_zero_learns_window(self):
        self.check_learned("0")

    def test_f62_env_negative_learns_window(self):
        self.check_learned("-5")

    def test_f62_env_decimal_learns_window(self):
        self.check_learned("1.5")

    def test_f62_ac289_unsorted_counts_use_the_median(self):
        # preTokens 367000, 167000, 267000: median 267000 + 33000 = 300000 (first reminder 225000)
        h = [367000, 167000, 267000]
        self.assertNoNudge(self.probe(160000, history=h))
        self.assertWindow(300000, "learned")
        self.assertNoNudge(self.probe(224000, history=h))
        self.assertNudge(self.probe(226000, history=h))

    def test_f62_ac290_sibling_with_three_boundaries(self):
        self.assertNudge(self.probe(160000, history=[], sibling=[167000, 167000, 167000]))
        self.assertWindow(200000, "learned")

    def test_f62_ac292_precompact_health_row_copies_window(self):
        sid = "f62eeeee-0000-4000-8000-000000000001"
        self.assertNudge(self.probe(301000, history=self.HISTORY, sid=sid))
        self.write_transcript([{"type": "user", "message": {"content": "keep working on the task"}}])
        r = self.run_pre(self.payload(sid))
        self.assertEqual(r.returncode, 0, r.stderr)
        row = self.health()
        self.assertEqual((row.get("window"), row.get("window_source")), (400000, "learned"), row)

    def test_f62_learned_final_nudge_at_window_minus_45000(self):
        sid = "f62fffff-0000-4000-8000-000000000001"
        self.assertNudge(self.probe(301000, history=self.HISTORY, sid=sid))
        out = self.probe(356000, history=self.HISTORY, sid=sid)  # 400000 - 45000 = 355000
        self.assertIn(FINAL, out)

    def test_f62_learned_no_final_text_before_final_threshold(self):
        out = self.probe(351000, history=self.HISTORY)
        self.assertNudge(out)
        self.assertNotIn(FINAL, out)

    def test_f62_window_is_median_plus_33000_rounded_to_1000(self):
        cases = [([366600], 400000), ([366400], 399000), ([360000, 370000], 398000), ([100000, 200000, 900000], 233000)]
        for hist, want in cases:
            with self.subTest(history=hist):
                self.setUp()
                # a context just above the 75% point must nudge, just below must not (window `want`)
                above = int(want * 0.75) + 1000
                below = int(want * 0.75) - 1000
                self.assertNoNudge(self.probe(below, history=hist))
                self.assertNudge(self.probe(above, history=hist))
                self.assertWindow(want, "learned")

    def test_f62_only_newest_20_boundaries_are_used(self):
        # file order is time order: 25 old low counts first, then the newest 20 high counts
        hist = [167000] * 25 + [367000] * 20
        self.assertNoNudge(self.probe(250000, history=hist))
        self.assertNudge(self.probe(301000, history=hist))
        self.assertWindow(400000, "learned")

    def test_f62_learned_from_sibling_transcript_in_same_project(self):
        out = self.probe(250000, history=[], sibling=self.HISTORY)
        self.assertNoNudge(out, "current transcript has no boundary: learn 400k from the sibling")
        self.assertNudge(self.probe(301000, history=[], sibling=self.HISTORY))
        self.assertWindow(400000, "learned")

    def test_f62_current_transcript_beats_sibling(self):
        self.assertNoNudge(self.probe(250000, history=self.HISTORY, sibling=[167000, 167000]))
        self.assertNudge(self.probe(301000, history=self.HISTORY, sibling=[167000, 167000]))
        self.assertWindow(400000, "learned")

    def test_f62_other_project_folder_is_not_used(self):
        out = self.probe(151000, history=[], other_project=self.HISTORY)
        self.assertNudge(out, "history in another project folder must not be used: default 200k")
        self.assertWindow(200000, "default")


# ---------------------------------------------------------------- (3) default
class Default(NudgeBase):
    def check_default(self, window):
        self.assertNoNudge(self.probe(140000, window=window))
        self.assertNoNudge(self.probe(149000, window=window))
        self.assertNudge(self.probe(151000, window=window))
        self.assertWindow(200000, "default")

    def test_f62_unset_no_history_is_200k(self):
        self.check_default(None)

    def test_f62_empty_no_history_is_200k(self):
        self.check_default("")

    def test_f62_abc_no_history_is_200k(self):
        self.check_default("abc")

    def test_f62_zero_no_history_is_200k(self):
        self.check_default("0")

    def test_f62_negative_no_history_is_200k(self):
        self.check_default("-5")

    def test_f62_decimal_no_history_is_200k(self):
        self.check_default("1.5")

    def test_f62_default_final_nudge_at_155000(self):
        sid = "f62ddddd-0000-4000-8000-000000000001"
        self.assertNudge(self.probe(151000, sid=sid))
        self.assertIn(FINAL, self.probe(156000, sid=sid))


# ---------------------------------------------------------------- final at or below the first reminder
class FinalOnly(NudgeBase):
    def test_f62_final_at_or_below_first_sends_only_final(self):
        # window 100000: first reminder 75,000; final 55,000 (below it): only the final nudge
        self.assertNoNudge(self.probe(54000, window="100000"))
        out = self.probe(80000, window="100000")
        self.assertNudge(out)
        self.assertIn(FINAL, out)

    def test_f62_ac291_window_40000_one_final_nudge_then_none(self):
        sid = "f62ccccc-0000-4000-8000-000000000001"
        out = self.probe(40000, window="40000", sid=sid)
        self.assertIn(FINAL, out)
        self.assertNoNudge(self.probe(41000, window="40000", sid=sid), "the next call sends none")

    def test_f62_final_equal_to_first_sends_only_final(self):
        # window 180000: first reminder 135,000; final 135,000
        self.assertNoNudge(self.probe(134000, window="180000"))
        out = self.probe(136000, window="180000")
        self.assertNudge(out)
        self.assertIn(FINAL, out)


if __name__ == "__main__":
    unittest.main()
