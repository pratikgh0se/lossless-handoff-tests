"""F63 Format drift alarm (code-blind: written from the contract and the README, docs/spec.md, docs/architecture.md).
Reconcile compares, per session in its window: (1) post-compaction inject events that the hooks recorded in
health.jsonl, (2) compact_boundary records in that session's transcript. Inject events >= 1 and boundaries == 0 sets
`format_drift: true` in reconcile.json with `format_drift_sessions` (session id, inject count, boundary count) and a
one-line reason. --prove and the claims evaluation mark the affected claims `fail` with reason `format_drift`. The
SessionStart install check prints exactly one line with "format drift" when the newest reconcile.json has it.
The inject event is one main-session row (`agent_id` null) in receipts.jsonl (F63.a). Most tests write those rows by hand;
one test makes the row with the real postcompact-inject.py. Result keys: format_drift, format_drift_sessions
([{"sid","injects","boundaries"}]), format_drift_reason. Reconcile prints a line starting `format drift:`."""
import json, os, re, subprocess, sys, unittest

from helpers import installed_settings, user
from test_f45_no_silent_miss import BOUNDARY, iso
from test_f48_claims import ClaimsBase, claim

SID = "f63aaaaa-0000-4000-8000-000000000001"
OKSID = "f63bbbbb-0000-4000-8000-000000000002"
DAY = 86400


class DriftBase(ClaimsBase):
    def setUp(self):
        super().setUp()
        self.proj = os.path.join(self.home, ".claude", "projects", "-proj-f63")
        os.makedirs(self.proj)

    def transcript(self, sid, boundaries):
        p = os.path.join(self.proj, sid + ".jsonl")
        recs = [dict(user("A user message long enough to be real text here"), entrypoint="cli",
                     timestamp=iso(-DAY * 2), sessionId=sid)]
        for off in boundaries:
            recs.append(dict(BOUNDARY, timestamp=iso(off), sessionId=sid))
        recs.append(dict(user("A later user message after any compaction"), timestamp=iso(-5), sessionId=sid))
        with open(p, "w") as f:
            for r in recs:
                f.write(json.dumps(r) + "\n")
        return p

    def inject(self, sid, tpath):
        """A real post-compaction inject: fresh handoff and sidecar on disk, then SessionStart compact part 1."""
        self.put_latest("BODY\n", sid=sid)
        self.put_sidecar(sid=sid, status="ok", age_s=60)
        self.add_health_row(sid, ts=iso(-60))  # the PreCompact row that goes with the handoff (a handoff, not an inject)
        pl = {"session_id": sid, "cwd": self.tmp, "hook_event_name": "SessionStart", "source": "compact",
              "transcript_path": tpath}
        r = subprocess.run([sys.executable, self.post, "--part", "1"], input=json.dumps(pl), capture_output=True,
                           text=True, env=self.env(None), timeout=30)
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout)

    def receipts(self, sid, n, tpath, boundary_ts=None):
        """n main-session inject rows in receipts.jsonl (F63.a field list)."""
        os.makedirs(self.hd, exist_ok=True)
        with open(os.path.join(self.hd, "receipts.jsonl"), "a") as f:
            for i in range(n):
                f.write(json.dumps({"ts": iso(-60 - i), "sid": sid[:8], "agent_id": None, "key": sid,
                                    "transcript": tpath, "boundary_ts": boundary_ts, "kind": "normal",
                                    "handoff_sha256": "0" * 64, "part1_sha256": "1" * 64, "part1_head": "x"}) + "\n")

    def reconcile(self):
        r = self.run_pre("--reconcile", "--days", "7")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return self.read_json(os.path.join(self.hd, "reconcile.json"))

    def read_json(self, p):
        with open(p) as f:
            return json.load(f)

    # fixtures
    def drift_fixture(self, n=2):
        """Session SID: n inject rows, 0 boundaries (the format drift case, AC 294)."""
        t = self.transcript(SID, [])
        self.receipts(SID, n, t)

    def clean_fixture(self):
        """Session OKSID: one inject row and one boundary (AC 293)."""
        t = self.transcript(OKSID, [-3600])
        self.receipts(OKSID, 1, t, boundary_ts=iso(-3600))


def flat(x):
    if isinstance(x, dict):
        return [v for k in x for v in flat(x[k])]
    if isinstance(x, (list, tuple)):
        return [v for e in x for v in flat(e)]
    return [x]


def assert_lists_session(tc, entry, sid, inject, boundary):
    vals = flat(entry)
    tc.assertTrue(any(isinstance(v, str) and (v == sid or v == sid[:8] or sid[:8] in v) for v in vals),
                  "session id missing in %r" % (entry,))
    ints = [v for v in vals if isinstance(v, int) and not isinstance(v, bool)]
    tc.assertIn(inject, ints, "inject count %d missing in %r" % (inject, entry))
    tc.assertIn(boundary, ints, "boundary count %d missing in %r" % (boundary, entry))


# ---------------------------------------------------------------- reconcile.json
class Reconcile(DriftBase):
    def test_f63_a_boundaries_and_injects_match_no_drift(self):
        self.clean_fixture()
        j = self.reconcile()
        self.assertIs(j.get("format_drift"), False, j)
        self.assertEqual(j.get("format_drift_sessions", []), [], j)

    def test_f63_a_more_boundaries_than_injects_no_drift(self):
        t = self.transcript(OKSID, [-7200, -3600])
        self.receipts(OKSID, 1, t)
        j = self.reconcile()
        self.assertIs(j.get("format_drift"), False, j)

    def test_f63_b_injects_without_boundaries_is_drift(self):
        self.drift_fixture()
        j = self.reconcile()
        self.assertIs(j.get("format_drift"), True, j)
        sessions = j.get("format_drift_sessions")
        self.assertIsInstance(sessions, list, j)
        self.assertEqual(len(sessions), 1, sessions)
        self.assertEqual(sessions, [{"sid": SID[:8], "injects": 2, "boundaries": 0}])  # AC 294

    def test_f63_b_real_inject_row_counts_as_inject_event(self):
        t = self.transcript(SID, [])
        self.inject(SID, t)  # postcompact-inject.py writes the receipt row itself
        j = self.reconcile()
        self.assertIs(j.get("format_drift"), True, j)
        self.assertEqual(j["format_drift_sessions"], [{"sid": SID[:8], "injects": 1, "boundaries": 0}])

    def test_f63_b_reconcile_prints_a_format_drift_line(self):
        self.drift_fixture()
        r = self.run_pre("--reconcile", "--days", "7")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len([l for l in r.stdout.split("\n") if l.startswith("format drift:")]), 1, r.stdout)

    def test_f63_a_no_drift_prints_no_format_drift_line(self):
        self.clean_fixture()
        r = self.run_pre("--reconcile", "--days", "7")
        self.assertFalse([l for l in r.stdout.split("\n") if l.startswith("format drift:")], r.stdout)

    def test_f63_b_reason_is_one_line(self):
        self.drift_fixture()
        j = self.reconcile()
        reason = j.get("format_drift_reason")
        self.assertTrue(isinstance(reason, str) and reason.strip() and "\n" not in reason.strip(), j)

    def test_f63_b_only_the_drifting_session_is_listed(self):
        self.clean_fixture()
        self.drift_fixture()
        j = self.reconcile()
        self.assertIs(j.get("format_drift"), True, j)
        sessions = j["format_drift_sessions"]
        self.assertEqual(len(sessions), 1, sessions)
        self.assertEqual(sessions, [{"sid": SID[:8], "injects": 2, "boundaries": 0}])
        self.assertNotIn(OKSID[:8], json.dumps(sessions))

    def test_f63_c_no_injects_no_drift(self):
        self.transcript(SID, [])  # no boundaries, but also no inject event
        j = self.reconcile()
        self.assertIs(j.get("format_drift"), False, j)
        self.assertEqual(j.get("format_drift_sessions", []), [], j)


# ---------------------------------------------------------------- --prove and claims
class Claims(DriftBase):
    def setUp(self):
        super().setUp()
        self.set_register([claim("C1", "coverage", "reconcile:coverage", min_rate=0.5)])

    def write_reconcile(self, drift):
        d = {"ts": iso(-10), "days": 30, "compactions": 10, "handoffs": 10, "recovered": 0, "missed": 0,
             "missed_interactive": 0, "missed_headless": 0, "killed": 0, "sessions": [], "format_drift": drift}
        if drift:
            d["format_drift_sessions"] = [{"sid": SID[:8], "injects": 2, "boundaries": 0}]
            d["format_drift_reason"] = "post-compaction injects recorded but no compact_boundary in the transcript"
        else:
            d["format_drift_sessions"] = []
        json.dump(d, open(os.path.join(self.hd, "reconcile.json"), "w"))

    def test_f63_d_drift_fails_the_claim_with_reason(self):
        self.write_reconcile(True)
        self.prove()
        c = self.status()["C1"]
        self.assertEqual(c["status"], "fail", c)
        rep = [l for l in self.report().split("\n") if re.search(r"\bC1\b", l)]
        self.assertTrue(rep and "fail (format_drift)" in rep[0], self.report())

    def test_f63_d_claims_flag_shows_the_failure(self):
        self.write_reconcile(True)
        self.prove()
        r = self.run_pre("--claims")
        self.assertEqual(r.returncode, 0, r.stderr)
        row = [l for l in r.stdout.split("\n") if re.search(r"\bC1\b", l)]
        self.assertTrue(row and "fail (format_drift)" in row[0], r.stdout)  # AC 297

    def test_f63_d_control_no_drift_passes(self):
        self.write_reconcile(False)
        self.prove()
        c = self.status()["C1"]
        self.assertEqual(c["status"], "pass", c)
        self.assertNotIn("format_drift", json.dumps(c))

    def test_f63_d_real_reconcile_then_prove(self):
        # one healthy session gives a coverage that would pass, one drifting session must turn it into a fail
        self.clean_fixture()
        self.drift_fixture()
        r = self.run_pre("--reconcile", "--prove", "--days", "7")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        c = self.status()["C1"]
        self.assertEqual(c["status"], "fail", c)
        self.assertTrue(any(re.search(r"\bC1\b", l) and "fail (format_drift)" in l
                            for l in self.report().split("\n")), self.report())

    def test_f63_d_proof_claim_of_a_drift_session_fails(self):
        # F63.c: a proof:* claim that counts a check of a receipt of a drift session fails with format_drift
        self.set_register([claim("C3", "lossless", "proof:lossless")])
        self.add_proof("lossless", "pass", sid=SID)
        self.write_reconcile(True)
        self.prove()
        c = self.status()["C3"]
        self.assertEqual(c["status"], "fail", c)
        self.assertTrue(any(re.search(r"\bC3\b", l) and "fail (format_drift)" in l
                            for l in self.report().split("\n")), self.report())


# ---------------------------------------------------------------- SessionStart install check
class Check(DriftBase):
    def setUp(self):
        super().setUp()
        json.dump(dict(installed_settings(self.home), cleanupPeriodDays=365),
                  open(os.path.join(self.home, ".claude", "settings.json"), "w"))

    def check(self):
        r = subprocess.run([sys.executable, self.post, "--check"], input="", capture_output=True, text=True,
                           env=self.env(None), timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def drift_lines(self, out):
        return [l for l in out.split("\n") if "format drift" in l.lower()]

    def test_f63_e_drift_prints_exactly_one_line(self):
        self.drift_fixture()
        self.assertIs(self.reconcile().get("format_drift"), True)
        out = self.check()
        self.assertEqual(len(self.drift_lines(out)), 1, out)
        self.assertTrue(self.drift_lines(out)[0].startswith("HANDOFF CHECK: format drift:"), out)
        self.assertEqual(len(self.drift_lines(self.check())), 1, "F63.d: printed on each run, not once only")

    def test_f63_e_no_inject_rows_prints_no_such_line(self):
        self.transcript(SID, [])
        self.assertIs(self.reconcile().get("format_drift"), False)
        self.assertEqual(self.drift_lines(self.check()), [])

    def test_f63_e_no_drift_prints_no_such_line(self):
        self.clean_fixture()
        self.assertIs(self.reconcile().get("format_drift"), False)
        self.assertEqual(self.drift_lines(self.check()), [])

    def test_f63_e_handwritten_reconcile_with_drift_prints_one_line(self):
        os.makedirs(self.hd, exist_ok=True)
        json.dump({"ts": iso(-10), "days": 7, "compactions": 1, "handoffs": 1, "recovered": 0, "missed": 0,
                   "missed_interactive": 0, "missed_headless": 0, "killed": 0, "sessions": [],
                   "format_drift": True,
                   "format_drift_sessions": [{"sid": SID[:8], "injects": 1, "boundaries": 0}]},
                  open(os.path.join(self.hd, "reconcile.json"), "w"))
        out = self.check()
        self.assertEqual(len(self.drift_lines(out)), 1, out)


if __name__ == "__main__":
    unittest.main()
