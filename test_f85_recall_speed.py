"""F85 Recall speed on a large project (0.20.1, hooks 1.22.1). Code-blind: written from the F85 text only.
F85.d: with RECALL_STATS=1 recall prints one last stderr line with counters. F85.a/b/f.1: on 50 transcripts of 2,000
lines each, the second keyword search with `rg` parses 7 lines or less and opens 2 transcripts or less. F85.c/f.2: stdout is the
same with and without `rg`. F85.f.3: a hit inside a recall tool call or its result stays out. F85.e/f.4/f.5: the lossless
check adds `--session <id8>` and a recall call that times out gives `skip` with the reason `timeout`."""
import json, os, re, shutil, stat, sys, unittest

from helpers import HOOKS_DIR
from test_f44_recall import RecallBase, RECALL
from test_f47a_lossless_labels import Base as ProveBase, PARENT
from test_f47_proof_receipts import BTS
from test_f45_no_silent_miss import BOUNDARY

NEEDLE = "NEEDLEXYZ"
STATS = re.compile(r"^recall stats: transcripts_opened=(\d+) lines_parsed=(\d+) rg_calls=(\d+) ms=(\d+)$")


def sid_of(n):
    return "85%06d-0000-4000-8000-%012d" % (n, n)


def stats_of(r):
    last = r.stderr.rstrip("\n").split("\n")[-1]
    m = STATS.match(last)
    assert m, "stderr:\n" + r.stderr
    return tuple(int(x) for x in m.groups())


class Big(RecallBase):
    N, LINES = 50, 2000

    def setUp(self):
        super().setUp()
        if not self.have_rg:
            self.skipTest("rg is not installed")

    def rec_line(self, sid, k, text, kind="assistant"):
        return json.dumps({"type": kind, "sessionId": sid, "cwd": self.proj, "uuid": "u%d-%s" % (k, sid[:8]),
                           "timestamp": "2026-03-05T12:%02d:%02d.000Z" % (k // 60 % 60, k % 60),
                           "message": {"role": kind, "content": text if kind == "user" else [{"type": "text", "text": text}]}})

    def tool_pair(self, sid, k, cmd, result):
        tid = "toolu_%s_%d" % (sid[:8], k)
        ts = "2026-03-05T12:%02d:%02d.000Z" % (k // 60 % 60, k % 60)
        use = {"type": "assistant", "sessionId": sid, "cwd": self.proj, "uuid": "tu%d-%s" % (k, sid[:8]), "timestamp": ts,
               "message": {"role": "assistant", "content": [{"type": "tool_use", "id": tid, "name": "Bash", "input": {"command": cmd}}]}}
        res = {"type": "user", "sessionId": sid, "cwd": self.proj, "uuid": "tr%d-%s" % (k, sid[:8]), "timestamp": ts,
               "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tid, "content": result}]}}
        return json.dumps(use), json.dumps(res)

    def build(self, recall_elsewhere=0):
        """50 transcripts. Needle: 3 plain lines in transcripts 7 and 31. Transcripts 7 and 31 also hold one recall.py
        tool call and its result each (4 lines in all). `recall_elsewhere`: other transcripts with such a pair."""
        d = self.tdir(self.proj)
        plan = {7: [100, 900], 31: [500]}
        pairs = {7, 31} | set(range(40, 40 + recall_elsewhere))
        for n in range(self.N):
            sid = sid_of(n)
            lines = [self.rec_line(sid, k, "filler line %d of session %d about the weather and tea" % (k, n)) for k in range(self.LINES)]
            for k in plan.get(n, []):
                lines[k] = self.rec_line(sid, k, "%s plain message in session %d line %d" % (NEEDLE, n, k))
            if n in pairs:
                a, b = self.tool_pair(sid, 1200, "python3 ~/.claude/hooks/recall.py search other words", "other words result text")
                lines[1200], lines[1201] = a, b
            with open(os.path.join(d, sid + ".jsonl"), "w") as f:
                f.write("\n".join(lines) + "\n")

    def search(self, *a, norg=False, stats=True, **kw):
        extra = dict(kw.pop("extra", {}) or {})
        if stats:
            extra["RECALL_STATS"] = "1"
        r = self.rc("search", NEEDLE, *a, norg=norg, extra=extra, **kw)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r

    def test_f85_f1_warm_second_search_parses_7_lines_or_less_and_opens_2_transcripts_or_less(self):
        self.build()
        self.search()  # warm the scope cache
        r = self.search()
        opened, parsed, rg_calls, ms = stats_of(r)
        self.assertLessEqual(parsed, 7, r.stderr)
        self.assertLessEqual(opened, 2, r.stderr)
        self.assertGreaterEqual(rg_calls, 1)
        hits = self.hits(r.stdout)
        self.assertEqual(len(hits), 3, r.stdout)
        self.assertEqual(sorted(h.group(0).split(" ")[0] for h in hits),
                         sorted([sid_of(7)[:8] + ":101", sid_of(7)[:8] + ":901", sid_of(31)[:8] + ":501"]))

    def test_f85_b_transcripts_without_a_candidate_line_are_not_scanned_for_own_tool_calls(self):
        self.build(recall_elsewhere=5)
        self.search()
        r = self.search()
        opened, parsed, _, _ = stats_of(r)
        self.assertLessEqual(opened, 2, r.stderr)
        self.assertLessEqual(parsed, 7, r.stderr)

    def test_f85_f2_the_same_stdout_without_rg(self):
        self.build()
        with_rg = self.search(stats=False).stdout
        self.search()
        warm = self.search(stats=False).stdout
        without = self.search(norg=True, stats=False).stdout
        self.assertEqual(with_rg, warm)
        self.assertEqual(with_rg, without)
        self.assertTrue(with_rg.strip())

    def test_f85_d_the_stats_line_is_last_on_stderr_and_only_with_the_variable(self):
        self.build()
        plain = self.search(stats=False)
        self.assertEqual(plain.stderr, "")
        r = self.search()
        lines = r.stderr.rstrip("\n").split("\n")
        self.assertTrue(STATS.match(lines[-1]), r.stderr)
        self.assertEqual(sum(1 for l in lines if l.startswith("recall stats:")), 1)

    def test_f85_d_without_rg_there_are_no_rg_calls(self):
        self.build()
        r = self.search(norg=True)
        opened, parsed, rg_calls, _ = stats_of(r)
        self.assertEqual(rg_calls, 0)
        self.assertGreater(opened, 0)

    def test_f85_f3_a_hit_inside_a_recall_tool_call_or_its_result_stays_out(self):
        self.build()
        d = self.tdir(self.proj)
        sid = sid_of(7)
        path = os.path.join(d, sid + ".jsonl")
        lines = open(path).read().split("\n")
        a, b = self.tool_pair(sid, 1200, "python3 ~/.claude/hooks/recall.py search %s" % NEEDLE, "%s found in an earlier chat" % NEEDLE)
        lines[1200], lines[1201] = a, b
        open(path, "w").write("\n".join(lines))
        for stats in (False, True):
            for norg in (False, True):
                with self.subTest(stats=stats, norg=norg):
                    r = self.search(norg=norg, stats=stats)
                    hits = [h.group(0).split(" ")[0] for h in self.hits(r.stdout)]
                    self.assertEqual(sorted(hits), sorted([sid[:8] + ":101", sid[:8] + ":901", sid_of(31)[:8] + ":501"]), r.stdout)
                    self.assertNotIn("earlier chat", r.stdout)

    def test_f85_c_a_search_with_no_hit_prints_the_same_with_and_without_rg(self):
        self.build()
        a = self.rc("search", "qqqnomatchqqq")
        b = self.rc("search", "qqqnomatchqqq", norg=True)
        self.assertEqual((a.returncode, a.stdout), (b.returncode, b.stdout))


class Lossless(ProveBase):
    """F85.e and F85.f.4, F85.f.5. A wrapper recall.py in a temp copy of the hooks records its arguments and runs the
    real recall (renamed). A second wrapper sleeps."""
    SESS2 = "f47a2222-0000-4000-8000-000000000002"

    def wrapper_hooks(self, sleeper=False):
        hooks = os.path.join(self.tmp, "hooks-wrap")
        shutil.copytree(HOOKS_DIR, hooks, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        self.log = os.path.join(self.tmp, "recall-args.log")
        real = os.path.join(hooks, "recall_real.py")
        shutil.copy(os.path.join(hooks, "recall.py"), real)
        src = '''#!/usr/bin/env python3
import json, os, subprocess, sys, time
if __name__ == "__main__":
    with open(%r, "a") as f:
        f.write(json.dumps(sys.argv[1:]) + "\\n")
    if %r:
        time.sleep(5)
        sys.exit(0)
    r = subprocess.run([sys.executable, %r] + sys.argv[1:])
    sys.exit(r.returncode)
''' % (self.log, sleeper, real)
        with open(os.path.join(hooks, "recall.py"), "w") as f:
            f.write(src)
        return os.path.join(hooks, "precompact-handoff.py")

    def two_sessions(self):
        t = self.main_transcript()
        recs = self.records(self.SESS2)
        self.write_jsonl(os.path.join(self.tdir(self.proj), self.SESS2 + ".jsonl"), recs)
        self.ok("index")
        return t

    def calls(self):
        if not os.path.exists(self.log):
            return []
        return [json.loads(l) for l in open(self.log) if l.strip()]

    def test_f85_f4_two_sessions_with_the_same_sentence_pass_and_the_search_has_session(self):
        t = self.two_sessions()
        pre = self.wrapper_hooks()
        rc = self.receipt(t, sid=PARENT)
        self.prove(env=self.penv(), pre=pre)
        v = self.verdict(rc)
        self.assertEqual(v["checks"]["lossless"], "pass", v)
        searches = [c for c in self.calls() if c and c[0] == "search"]
        self.assertTrue(searches)
        for c in searches:
            self.assertIn("--session", c, c)
            self.assertEqual(c[c.index("--session") + 1], PARENT[:8], c)

    def test_f85_f5_a_recall_call_that_runs_past_the_limit_gives_skip_and_timeout(self):
        t = self.main_transcript()
        pre = self.wrapper_hooks(sleeper=True)
        rc = self.receipt(t, sid=PARENT)
        env = dict(self.penv(), HANDOFF_PROVE_RECALL_TIMEOUT="2")
        self.prove(env=env, pre=pre)
        v = self.verdict(rc)
        self.assertEqual(v["checks"]["lossless"], "skip", v)
        self.assertIn("timeout", v["details"].get("lossless", ""), v)

    def test_f85_e_a_timeout_does_not_count_as_a_failure(self):
        t = self.main_transcript()
        pre = self.wrapper_hooks(sleeper=True)
        self.receipt(t, sid=PARENT)
        env = dict(self.penv(), HANDOFF_PROVE_RECALL_TIMEOUT="2")
        r = self.prove(env=env, pre=pre)
        self.assertIn("lossless 0/0", r.stdout)


if __name__ == "__main__":
    unittest.main()
