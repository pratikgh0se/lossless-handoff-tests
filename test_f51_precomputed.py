"""F51 (precomputed compactions) ACs 212-217 of docs/spec.md. Code-blind: fixtures are built from the spec only.
SessionStart `compact`: a handoff written at T0 still belongs to a compaction applied later (T1), when the handoff
is newer than the previous boundary or no earlier boundary exists. Temp HOME, real clock."""
import json, os, time, unittest

from helpers import PLAIN, user, asst
from test_f45_no_silent_miss import F45Base, BOUNDARY, iso
from test_f46_subagent_isolation import F46Base

SID = "S"
AID = "a1"
BODY = "HANDOFF-BODY-F51 the agent note for this compaction\n"
NOTE_PFX = "Note: this compaction was prepared at "
NOT_REFRESHED = "not refreshed"


def stamp(age_s):
    return iso(-age_s)


def fmt_h(age_s):
    return time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime(time.time() - age_s))


def boundary(age_s, precomputed=False):
    r = dict(BOUNDARY, timestamp=stamp(age_s))
    if precomputed:
        r["compactMetadata"] = {"precomputed": True, "preservedSegment": {"headUuid": "u1", "tailUuid": "u2"}}
    return r


class Mixin:
    def fixture(self, key, h_age, boundaries):
        """Handoff files for `key` with last-health ts `h_age` seconds ago; transcript with boundaries (ages in s)."""
        self.put_latest(BODY, sid=key)
        ts = stamp(h_age)
        self.put_sidecar(sid=key, ts=ts)
        entries = [user("An early message long enough to count as a user message")]
        for age, pre in boundaries:
            entries.append(boundary(age, pre))
            entries.append(user("A message after that compaction, still long enough"))
        return ts

    def part1(self, payload, k=1):
        r = self.run_post(payload, args=("--part", str(k)))
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout)
        if r.stdout.strip() == "":
            return None
        return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]

    def receipts(self):
        p = os.path.join(self.hd, "receipts.jsonl")
        return [json.loads(l) for l in open(p).read().split("\n") if l.strip()] if os.path.exists(p) else []

    def assert_precomputed_ok(self, payload, h_age, key=SID):
        out = self.part1(payload)
        self.assertIsNotNone(out)
        lines = out.split("\n")
        self.assertEqual(lines[0] + "\n", PLAIN, out[:200])
        self.assertTrue(lines[1].startswith(NOTE_PFX), lines[:3])
        self.assertIn(BODY.strip(), out)
        for bad in ("HANDOFF RECOVERED", "HANDOFF DEGRADED", NOT_REFRESHED):
            self.assertNotIn(bad, out)
        rs = [r for r in self.receipts() if r.get("key") == key]
        self.assertEqual(len(rs), 1, self.receipts())
        self.assertEqual(rs[0]["kind"], "normal")
        # the stated time is H (to the second; the clock moves a little while the test runs)
        stated = lines[1][len(NOTE_PFX):].split(";")[0]
        t = time.mktime(time.strptime(stated, "%Y-%m-%d %H:%M:%SZ")) - time.timezone
        self.assertLess(abs(t - (time.time() - h_age)), 30, stated)
        # parts 2 and 3 print their normal parts: the same as for a fresh handoff of the same file
        p2, p3 = self.part1(payload, 2), self.part1(payload, 3)
        self.put_sidecar(sid=key, ts=stamp(5))
        self.assertEqual((p2, p3), (self.part1(payload, 2), self.part1(payload, 3)))
        return out


class Main(Mixin, F45Base):
    LEDGER_ENV = "0"

    def run_case(self, h_age, boundaries, transcript=True):
        self.fixture(SID, h_age, boundaries)
        entries = [user("An early message long enough to count as a user message")]
        for age, pre in boundaries:
            entries += [boundary(age, pre), user("A message after that compaction, still long enough")]
        if transcript:
            self.write_transcript(entries)
        return self.compact_payload(sid=SID)

    def test_ac212_prepared_earlier_than_now_is_normal(self):
        p = self.run_case(6000, [(3 * 3600, False)])
        self.assert_precomputed_ok(p, 6000)

    def test_ac213_h_older_than_newest_boundary_recovers(self):
        p = self.run_case(6000, [(3 * 3600, False), (1800, False)])
        out = self.part1(p)
        self.assertIsNotNone(out)
        self.assertTrue(out.startswith("HANDOFF RECOVERED") or out.startswith("HANDOFF DEGRADED"), out[:200])
        self.assertNotIn(NOTE_PFX, out)

    def test_ac214_no_boundary_in_transcript(self):
        p = self.run_case(6000, [])
        self.assert_precomputed_ok(p, 6000)

    def test_ac215_boundary_20s_old_is_ignored(self):
        p = self.run_case(6000, [(3 * 3600, False), (20, True)])
        self.assert_precomputed_ok(p, 6000)

    def test_ac216_fresh_handoff_has_no_note(self):
        p = self.run_case(300, [(3 * 3600, False)])
        out = self.part1(p)
        self.assertIsNotNone(out)
        self.assertNotIn(NOTE_PFX, out)
        self.assertTrue(out.startswith(PLAIN), out[:200])
        self.assertIn(BODY.strip(), out)
        for bad in ("HANDOFF RECOVERED", "HANDOFF DEGRADED"):
            self.assertNotIn(bad, out)

    def test_unreadable_transcript_means_f51_does_not_apply(self):
        # F51: a missing or unreadable transcript -> F51 does not apply; the 1.10.0 rule stays (recovery, then DEGRADED)
        p = self.run_case(6000, [], transcript=False)
        p["transcript_path"] = os.path.join(self.tmp, "does-not-exist.jsonl")
        out = self.part1(p)
        self.assertIsNotNone(out)
        self.assertNotIn(NOTE_PFX, out)
        self.assertTrue(out.startswith("HANDOFF RECOVERED") or out.startswith("HANDOFF DEGRADED"), out[:200])


class Subagent(Mixin, F46Base):
    LEDGER_ENV = "0"
    KEY = "S-a-a1"

    def case(self, h_age, sub_boundaries, parent_boundaries):
        self.put_latest(BODY, sid=self.KEY)
        self.put_sidecar(sid=self.KEY, ts=stamp(h_age))
        base = [user("An early message long enough to count as a user message")]

        def with_b(bs):
            e = list(base)
            for age, pre in bs:
                e += [boundary(age, pre), user("A message after that compaction, still long enough")]
            return e
        self.write_transcript(with_b(parent_boundaries))
        self.write_sub_transcript(with_b(sub_boundaries))
        return self.sub_compact_payload()

    def test_ac217_subagent_uses_its_own_transcript(self):
        # the parent has a newer boundary than H (it would force recovery); the subagent's own transcript does not
        p = self.case(6000, [(3 * 3600, False)], [(3 * 3600, False), (1800, False)])
        self.assert_precomputed_ok(p, 6000, key=self.KEY)

    def test_ac217_subagent_h_older_than_own_boundary_recovers(self):
        p = self.case(6000, [(3 * 3600, False), (1800, False)], [(3 * 3600, False)])
        out = self.part1(p)
        self.assertIsNotNone(out)
        self.assertNotIn(NOTE_PFX, out)
        self.assertTrue(out.startswith("HANDOFF RECOVERED") or out.startswith("HANDOFF DEGRADED"), out[:200])


if __name__ == "__main__":
    unittest.main()
