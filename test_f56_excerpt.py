"""F56 Log the excerpt cut: ACs 252-254 of docs/spec.md. Code-blind: written from the spec only.
The handoff model sees at most 120,000 characters of the transcript. Each PreCompact health row logs
`excerpt_chars` and `excerpt_dropped`; `--prove` prints one information line about them.
Temp HOME, `claude` shim on PATH (the summary call is enabled: HANDOFF_HAIKU_FALLBACK unset)."""
import json, os, re, subprocess, sys, unittest

from helpers import HookCase, PRE, user, asst

CAP = 120000
LINE_RE = re.compile(r"^excerpt cut: (\d+) of (\d+) compactions, median dropped (\d+) chars$", re.M)


class Excerpt(HookCase):
    LEDGER_ENV = None

    def setUp(self):
        super().setUp()
        self.install_shim(out="SUMMARY-F56 the model summary text")

    def small(self):
        return [user("Please fix the parser bug in the exporter"), asst("Looking at the parser now"),
                user("Also add a unit test for the empty input case"), asst("Added the test")]

    def big(self):
        # 40 messages of 6,000 chars each: 240,000 chars in the current segment, more than the 120,000 cap
        out = []
        for i in range(40):
            text = ("segment-%02d " % i) + ("lorem ipsum dolor sit amet %d " % i) * 250
            out.append(user(text[:6000]) if i % 2 == 0 else asst(text[:6000]))
        return out

    def run_one(self, sid, entries):
        self.write_transcript(entries)
        r = self.run_pre(self.payload(sid), fallback=None)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return [json.loads(l) for l in self.health_lines() if json.loads(l).get("sid") == sid[:8]][-1]

    def prove(self):
        r = subprocess.run([sys.executable, PRE, "--prove", "--days", "1"], stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, env=self.env(None), timeout=120)
        return r

    def test_ac252_small_transcript_not_cut(self):
        row = self.run_one("S", self.small())
        self.assertGreater(row["excerpt_chars"], 0, row)
        self.assertEqual(row["excerpt_dropped"], 0, row)

    def test_ac252_excerpt_chars_is_an_int_not_more_than_transcript(self):
        row = self.run_one("S", self.small())
        self.assertIsInstance(row["excerpt_chars"], int)
        self.assertLess(row["excerpt_chars"], 5000)

    def test_ac252_no_model_call_gives_zero_chars(self):
        # HANDOFF_HAIKU_FALLBACK=0 turns the model call off: the shim must stay uncalled
        self.write_transcript(self.small())
        r = self.run_pre(self.payload("S"), fallback="0")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(self.shim_invoked())
        row = self.health()
        self.assertEqual(row["excerpt_chars"], 0, row)

    def test_ac253_large_segment_is_cut(self):
        row = self.run_one("S", self.big())
        self.assertGreater(row["excerpt_dropped"], 0, row)
        self.assertLessEqual(row["excerpt_chars"], CAP, row)
        self.assertGreater(row["excerpt_chars"], 0, row)

    def test_ac253_segment_after_boundary_only(self):
        # a big segment before the previous boundary does not count as dropped; the current segment is small
        entries = self.big() + [{"type": "system", "subtype": "compact_boundary", "content": "Conversation compacted"}] \
            + self.small()
        row = self.run_one("S", entries)
        self.assertEqual(row["excerpt_dropped"], 0, row)
        self.assertGreater(row["excerpt_chars"], 0, row)

    def test_ac254_prove_prints_excerpt_line(self):
        r1 = self.run_one("S", self.small())
        r2 = self.run_one("S2", self.big())
        r = self.prove()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        m = LINE_RE.search(r.stdout)
        self.assertIsNotNone(m, r.stdout)
        self.assertEqual((int(m.group(1)), int(m.group(2))), (1, 2), r.stdout)
        self.assertEqual(int(m.group(3)), r2["excerpt_dropped"], (r1, r2, r.stdout))

    def test_ac254_median_over_cut_rows(self):
        self.run_one("S", self.big())
        self.run_one("S2", self.big())
        self.run_one("S3", self.small())
        rows = [json.loads(l) for l in self.health_lines()]
        drops = sorted(x["excerpt_dropped"] for x in rows if x.get("excerpt_dropped", 0) > 0)
        self.assertEqual(len(drops), 2, rows)
        r = self.prove()
        m = LINE_RE.search(r.stdout)
        self.assertIsNotNone(m, r.stdout)
        self.assertEqual((int(m.group(1)), int(m.group(2))), (2, 3), r.stdout)
        lo, hi = drops
        self.assertTrue(lo <= int(m.group(3)) <= hi, (drops, r.stdout))

    def test_ac254_no_cut_prints_zero_median(self):
        self.run_one("S", self.small())
        r = self.prove()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("excerpt cut: 0 of 1 compactions, median dropped 0 chars", r.stdout.split("\n"))

    def test_ac254_line_never_fails_the_run(self):
        self.run_one("S", self.big())
        r = self.prove()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIsNotNone(LINE_RE.search(r.stdout), r.stdout)

    def test_ac254_rows_without_fields_are_ignored(self):
        os.makedirs(self.hd, exist_ok=True)
        with open(self.health_path(), "w") as f:
            f.write(json.dumps({"ts": __import__("time").strftime("%Y-%m-%dT%H:%M:%SZ", __import__("time").gmtime()),
                                "sid": "old00000", "trigger": "auto", "status": "ok", "hook_version": "1.11.0"}) + "\n")
        self.run_one("S", self.big())
        r = self.prove()
        m = LINE_RE.search(r.stdout)
        self.assertIsNotNone(m, r.stdout)
        self.assertEqual((int(m.group(1)), int(m.group(2))), (1, 1), r.stdout)


if __name__ == "__main__":
    unittest.main()
