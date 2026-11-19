"""F63 prove and window rules, AC 301 and F63.b/F63.c details (code-blind: written from docs/spec.md of the
hardening-drift branch).
301: in the drift state `--prove` counts the checks of the drift session as `fail` (summary `0/N`), proof-report.md
holds `format_drift`, and a proof:* claim has status `fail` with `(format_drift)`.
F63.b: boundaries count from the reconcile window start; a boundary with no readable timestamp always counts.
F63.c: a proof row outside the claim window never fails a proof:* claim."""
import json, os, re, unittest

from test_f45_no_silent_miss import BOUNDARY, iso
from test_f48_claims import claim
from test_f63_format_drift import DriftBase, SID, OKSID, DAY
from helpers import user


def report_row(text, cid):
    return [l for l in text.split("\n") if re.search(r"\b%s\b" % cid, l)]


class Prove(DriftBase):
    def setUp(self):
        super().setUp()
        self.set_register([claim("C3", "delivered", "proof:delivered")])

    def drift_receipt(self):
        t = self.transcript(SID, [])
        self.receipts(SID, 1, t, boundary_ts=iso(-3600))  # the hook recorded a boundary time; the transcript has none

    def combined(self):
        r = self.run_pre("--reconcile", "--prove", "--days", "7")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r

    def test_ac301_prove_counts_drift_checks_as_fail(self):
        self.drift_receipt()
        r = self.combined()
        summary = next(l for l in r.stdout.split("\n") if l.startswith("proof "))
        self.assertEqual(len(re.findall(r"\b0/1\b", summary)) >= 1, True, summary)
        self.assertNotRegex(summary, r"\b1/1\b")
        rows = [json.loads(l) for l in open(os.path.join(self.hd, "proofs.jsonl")) if l.strip()]
        self.assertEqual(len(rows), 1, rows)
        results = set(rows[0]["checks"].values())
        self.assertNotIn("pass", results, rows)

    def test_f63c_proofs_jsonl_marks_every_check_fail_with_reason(self):
        # F63.c: `--prove` marks every check of a receipt of a drift session `fail` with the reason `format_drift`
        self.drift_receipt()
        self.combined()
        rows = [json.loads(l) for l in open(os.path.join(self.hd, "proofs.jsonl")) if l.strip()]
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(set(rows[0]["checks"].values()), {"fail"}, rows)
        self.assertIn("format_drift", json.dumps(rows[0].get("details")), rows)

    def test_ac301_proof_report_holds_format_drift(self):
        self.drift_receipt()
        self.combined()
        self.assertIn("format_drift", open(os.path.join(self.hd, "proof-report.md")).read())

    def test_ac301_proof_claim_fails_with_format_drift(self):
        self.drift_receipt()
        self.combined()
        self.assertEqual(self.status()["C3"]["status"], "fail", self.status())
        row = report_row(self.report(), "C3")
        self.assertTrue(row and "fail (format_drift)" in row[0], self.report())
        r = self.run_pre("--claims")
        self.assertTrue(any("fail (format_drift)" in l for l in report_row(r.stdout, "C3")), r.stdout)

    def test_ac301_healthy_session_is_not_marked_drift(self):
        # control: a session with a boundary and an inject row never gets format_drift in the proof report
        t = self.transcript(OKSID, [-3600])
        self.receipts(OKSID, 1, t, boundary_ts=iso(-3600))
        self.combined()
        self.assertNotIn("format_drift", open(os.path.join(self.hd, "proof-report.md")).read())
        row = report_row(self.report(), "C3")
        self.assertFalse(row and "format_drift" in row[0], self.report())


class ClaimWindow(DriftBase):
    def setUp(self):
        super().setUp()
        self.set_register([claim("C3", "delivered", "proof:delivered", window_days=30)])
        os.makedirs(self.hd, exist_ok=True)
        json.dump({"ts": iso(-10), "days": 30, "compactions": 1, "handoffs": 1, "recovered": 0, "missed": 0,
                   "missed_interactive": 0, "missed_headless": 0, "killed": 0, "sessions": [],
                   "format_drift": True,
                   "format_drift_sessions": [{"sid": SID[:8], "injects": 1, "boundaries": 0}],
                   "format_drift_reason": "injects without compact_boundary records"},
                  open(os.path.join(self.hd, "reconcile.json"), "w"))

    def test_f63c_proof_row_inside_the_claim_window_fails_the_claim(self):
        self.add_proof("delivered", "pass", sid=SID[:8], ts=iso(-3600))
        self.prove()
        self.assertEqual(self.status()["C3"]["status"], "fail", self.status())
        self.assertTrue(any("fail (format_drift)" in l for l in report_row(self.report(), "C3")), self.report())

    def test_f63c_proof_row_outside_the_claim_window_never_fails_the_claim(self):
        old = iso(-40 * DAY)
        row = {"ts": old, "receipt_ts": old, "sid": SID[:8], "agent_id": None, "checks": {"delivered": "pass"},
               "details": {}}
        with open(os.path.join(self.hd, "proofs.jsonl"), "a") as f:
            f.write(json.dumps(row) + "\n")
        self.prove()
        c = self.status()["C3"]
        self.assertNotEqual(c["status"], "fail", c)
        self.assertFalse(any("format_drift" in l for l in report_row(self.report(), "C3")), self.report())


class BoundaryWindow(DriftBase):
    def write(self, sid, records):
        p = os.path.join(self.proj, sid + ".jsonl")
        with open(p, "w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
        return p

    def msg(self):
        return dict(user("A user message long enough to be real text here"), entrypoint="cli",
                    timestamp=iso(-30 * DAY), sessionId=SID)

    def test_f63b_boundary_older_than_the_window_does_not_count(self):
        t = self.write(SID, [self.msg(), dict(BOUNDARY, timestamp=iso(-20 * DAY), sessionId=SID)])
        self.receipts(SID, 1, t)
        j = self.reconcile()  # --days 7
        self.assertIs(j.get("format_drift"), True, j)
        self.assertEqual(j["format_drift_sessions"], [{"sid": SID[:8], "injects": 1, "boundaries": 0}])

    def test_f63b_boundary_inside_the_window_counts(self):
        t = self.write(SID, [self.msg(), dict(BOUNDARY, timestamp=iso(-2 * DAY), sessionId=SID)])
        self.receipts(SID, 1, t)
        j = self.reconcile()
        self.assertIs(j.get("format_drift"), False, j)

    def test_f63b_boundary_without_timestamp_always_counts(self):
        rec = dict(BOUNDARY, sessionId=SID)
        rec.pop("timestamp", None)
        t = self.write(SID, [self.msg(), rec])
        self.receipts(SID, 1, t)
        j = self.reconcile()
        self.assertIs(j.get("format_drift"), False, j)


if __name__ == "__main__":
    unittest.main()
