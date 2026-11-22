"""F39.1 and F39.3 session cursors: `decisions.state.json` keeps `cursors` = {<session id>: <ISO ts of the newest entry of
that session already merged>} (at most 200, the oldest by timestamp dropped). The merge reads entries newer than the
cursor of the CURRENT session. An old state file (no cursors) applies `lastEntryTs` only when `lastSid` equals the current
session; otherwise the whole transcript is read. `lastSid` and `lastEntryTs` repeat the newest write. Code-blind: written
from docs/spec.md F39.1 and F39.3 and the PR description only. The merge model is stubbed with the `claude` shim, as in
test_f39_ledger.py. The bug: chat Y starts at 10:00, chat X compacts at 14:00 and Y compacts at 15:00; with one project
cursor, Y's decisions from 10:00 to 14:00 never reach the merge input."""
import json, os, re, unittest

from helpers import *
from test_f39_ledger import F39, ts, parse_ts, SEED3, key_for


class Cursors(F39):
    def tx(self, sid, entries):
        path = os.path.join(self.tmp, "t-%s.jsonl" % sid)
        with open(path, "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")
        return path

    def compact(self, sid, entries, extra=None):
        p = self.payload(sid, cwd=self.cwd)
        p["transcript_path"] = self.tx(sid, entries)
        self.go(payload=p, extra=extra)

    def seed_state(self, cursors=None, last_sid=None, last_ts=None, ledger=SEED3):
        d, _ = self.seed(ledger, state=False)
        st = {"v": 1, "root": self.repo_root, "updatedAt": 1700000000000}
        if last_sid is not None:
            st["lastSid"] = last_sid
        if last_ts is not None:
            st["lastEntryTs"] = last_ts
        if cursors is not None:
            st["cursors"] = cursors
        with open(os.path.join(d, "decisions.state.json"), "w") as f:
            json.dump(st, f)

    def new_part(self, n=None):
        return self.conv_part(self.merge_stdin(n))

    def cur(self, sid):
        return parse_ts(self.state()["cursors"][sid])

    # fixtures: chat Y starts at minute 0, chat X compacts at minute 240, Y compacts at minute 300
    def y_entries(self, upto):
        e = [user("Y-EARLY: rule one from chat Y", timestamp=ts(0)), user("Y-MID: rule two from chat Y", timestamp=ts(120))]
        if upto >= 300:
            e.append(user("Y-LATE: rule three from chat Y", timestamp=ts(300)))
        return e

    def x_entries(self):
        return [user("X-ONE: decision from chat X", timestamp=ts(30)), user("X-TWO: decision from chat X", timestamp=ts(240))]

    # ------------------------------------------------------------------ the bug
    def test_cursor_two_sessions_early_items_of_the_second_chat_still_reach_the_merge_input(self):
        self.compact("X", self.x_entries())
        self.compact("Y", self.y_entries(300))
        self.assertEqual(self.merge_calls(), 2)
        new = self.new_part(2)
        for want in ("Y-EARLY", "Y-MID", "Y-LATE"):
            self.assertIn(want, new)
        for other in ("X-ONE", "X-TWO"):
            self.assertNotIn(other, new, "the merge input holds only the current session transcript")

    def test_cursor_the_first_session_merge_input_has_all_its_entries(self):
        self.compact("X", self.x_entries())
        new = self.new_part(1)
        self.assertIn("X-ONE", new)
        self.assertIn("X-TWO", new)

    def test_cursor_the_other_session_does_not_hide_items_older_than_its_cursor_in_either_order(self):
        self.compact("Y", self.y_entries(300))
        self.compact("X", self.x_entries())
        self.assertEqual(self.merge_calls(), 2)
        new = self.new_part(2)
        self.assertIn("X-ONE", new)
        self.assertIn("X-TWO", new)

    def test_cursor_a_session_second_compaction_reads_only_its_own_newer_entries(self):
        self.compact("Y", self.y_entries(0))
        self.compact("X", self.x_entries())
        self.compact("Y", self.y_entries(300))
        self.assertEqual(self.merge_calls(), 3)
        new = self.new_part(3)
        self.assertIn("Y-LATE", new)
        for old in ("Y-EARLY", "Y-MID", "X-ONE", "X-TWO"):
            self.assertNotIn(old, new)

    def test_cursor_a_second_run_with_nothing_new_makes_no_call_for_that_session_only(self):
        self.compact("Y", self.y_entries(300))
        self.compact("X", self.x_entries())
        calls = self.merge_calls()
        self.compact("Y", self.y_entries(300))
        self.assertEqual(self.merge_calls(), calls)
        self.assertEqual(self.health()["ledger"], "unchanged")

    # ------------------------------------------------------------------ state
    def test_cursor_first_merge_writes_the_cursor_and_the_legacy_fields(self):
        self.compact("X", self.x_entries())
        st = self.state()
        self.assertEqual(list(st["cursors"]), ["X"])
        self.assertEqual(parse_ts(st["cursors"]["X"]), parse_ts(ts(240)))
        self.assertEqual(st["lastSid"], "X")
        self.assertEqual(parse_ts(st["lastEntryTs"]), parse_ts(ts(240)))
        self.assertEqual(st["v"], 1)

    def test_cursor_other_sessions_cursors_are_kept(self):
        self.compact("X", self.x_entries())
        self.compact("Y", self.y_entries(300))
        st = self.state()
        self.assertEqual(sorted(st["cursors"]), ["X", "Y"])
        self.assertEqual(parse_ts(st["cursors"]["X"]), parse_ts(ts(240)))
        self.assertEqual(parse_ts(st["cursors"]["Y"]), parse_ts(ts(300)))
        self.assertEqual(st["lastSid"], "Y")
        self.assertEqual(parse_ts(st["lastEntryTs"]), parse_ts(ts(300)))

    def test_cursor_a_later_merge_moves_only_its_own_entry(self):
        self.compact("X", self.x_entries())
        self.compact("Y", self.y_entries(300))
        before_y = self.state()["cursors"]["Y"]
        self.compact("X", self.x_entries() + [user("X-THREE: later decision", timestamp=ts(400))])
        st = self.state()
        self.assertEqual(parse_ts(st["cursors"]["X"]), parse_ts(ts(400)))
        self.assertEqual(st["cursors"]["Y"], before_y)
        self.assertEqual(st["lastSid"], "X")

    def test_cursor_unchanged_run_keeps_every_cursor(self):
        self.compact("X", self.x_entries())
        self.compact("Y", self.y_entries(300))
        before = self.state()["cursors"]
        self.compact("X", self.x_entries())
        self.assertEqual(self.state()["cursors"], before)

    def test_cursor_a_failed_merge_moves_no_cursor(self):
        self.compact("X", self.x_entries())
        before = self.state()["cursors"]
        self.set_shim("merge", rc=1)
        self.compact("Y", self.y_entries(300))
        self.assertEqual(self.health()["ledger"], "failed")
        self.assertEqual(self.state()["cursors"], before)

    # ------------------------------------------------------------------ migration of an old state file
    def test_cursor_old_state_with_last_sid_equal_to_the_current_session_uses_last_entry_ts(self):
        self.seed_state(last_sid="S", last_ts=ts(10))
        self.compact("S", [user("S-OLD: before the cursor", timestamp=ts(5)), user("S-NEW: after the cursor", timestamp=ts(30))])
        self.assertEqual(self.merge_calls(), 1)
        new = self.new_part()
        self.assertIn("S-NEW", new)
        self.assertNotIn("S-OLD", new)
        self.assertEqual(parse_ts(self.state()["cursors"]["S"]), parse_ts(ts(30)))

    def test_cursor_old_state_with_last_sid_equal_and_nothing_newer_makes_no_call(self):
        self.seed_state(last_sid="S", last_ts=ts(30))
        self.compact("S", [user("S-OLD: before the cursor", timestamp=ts(5)), user("S-NEW: at the cursor", timestamp=ts(30))])
        self.assertEqual(self.merge_calls(), 0)
        self.assertEqual(self.health()["ledger"], "unchanged")

    def test_cursor_old_state_with_another_last_sid_reads_the_whole_transcript(self):
        self.seed_state(last_sid="OTHER", last_ts=ts(100))
        self.compact("S", [user("S-OLD: before the old cursor", timestamp=ts(5)), user("S-NEW: after it", timestamp=ts(200))])
        self.assertEqual(self.merge_calls(), 1)
        new = self.new_part()
        self.assertIn("S-OLD", new)
        self.assertIn("S-NEW", new)
        self.assertEqual(parse_ts(self.state()["cursors"]["S"]), parse_ts(ts(200)))

    def test_cursor_old_state_with_another_last_sid_and_all_entries_older_still_reads_them(self):
        self.seed_state(last_sid="OTHER", last_ts=ts(500))
        self.compact("S", [user("S-ONLY: older than the old project cursor", timestamp=ts(5))])
        self.assertEqual(self.merge_calls(), 1)
        self.assertIn("S-ONLY", self.new_part())

    def test_cursor_a_cursor_for_the_session_wins_over_last_entry_ts(self):
        self.seed_state(cursors={"S": ts(10)}, last_sid="S", last_ts=ts(500))
        self.compact("S", [user("S-OLD: before the cursor", timestamp=ts(5)), user("S-NEW: after the cursor", timestamp=ts(30))])
        new = self.new_part()
        self.assertIn("S-NEW", new)
        self.assertNotIn("S-OLD", new)

    def test_cursor_a_new_session_with_other_cursors_present_reads_everything(self):
        self.seed_state(cursors={"OTHER": ts(500)}, last_sid="OTHER", last_ts=ts(500))
        self.compact("S", [user("S-ONLY: nothing merged for this session yet", timestamp=ts(5))])
        self.assertIn("S-ONLY", self.new_part())
        self.assertEqual(sorted(self.state()["cursors"]), ["OTHER", "S"])

    # ------------------------------------------------------------------ prune
    def cursors_of(self, n, base=-2000):
        return {"s%03d" % i: ts(base + i) for i in range(n)}

    def test_cursor_at_most_200_cursors_are_kept_and_the_oldest_by_timestamp_are_dropped(self):
        self.seed_state(cursors=self.cursors_of(200), last_sid="s199", last_ts=ts(-1801))
        self.compact("S", [user("S-NEW: a rule", timestamp=ts(5))])
        cur = self.state()["cursors"]
        self.assertEqual(len(cur), 200)
        self.assertIn("S", cur)
        self.assertNotIn("s000", cur, "the oldest by timestamp is dropped")
        self.assertIn("s001", cur)
        self.assertIn("s199", cur)

    def test_cursor_prune_drops_the_oldest_by_timestamp_not_by_name_or_order(self):
        cur = {"zz-old": ts(-5000)}
        cur.update({"a%03d" % i: ts(-2000 + i) for i in range(199)})
        self.seed_state(cursors=cur, last_sid="a198", last_ts=ts(-1802))
        self.compact("S", [user("S-NEW: a rule", timestamp=ts(5))])
        after = self.state()["cursors"]
        self.assertEqual(len(after), 200)
        self.assertNotIn("zz-old", after)
        self.assertIn("a000", after)

    def test_cursor_prune_to_200_from_a_larger_file(self):
        self.seed_state(cursors=self.cursors_of(250), last_sid="s249", last_ts=ts(-1751))
        self.compact("S", [user("S-NEW: a rule", timestamp=ts(5))])
        after = self.state()["cursors"]
        self.assertEqual(len(after), 200)
        self.assertIn("S", after)
        self.assertNotIn("s000", after)
        self.assertNotIn("s050", after)
        self.assertIn("s249", after)

    def test_cursor_under_the_limit_nothing_is_dropped(self):
        self.seed_state(cursors=self.cursors_of(50), last_sid="s049", last_ts=ts(-1951))
        self.compact("S", [user("S-NEW: a rule", timestamp=ts(5))])
        self.assertEqual(len(self.state()["cursors"]), 51)

    # ------------------------------------------------------------------ the rest of F39 still holds
    def test_cursor_state_file_keeps_its_other_fields(self):
        self.compact("X", self.x_entries())
        st = self.state()
        self.assertEqual(st["root"], self.repo_root)
        self.assertIsInstance(st["updatedAt"], int)

    def test_cursor_a_two_session_run_writes_one_ledger_and_backups_as_before(self):
        self.compact("X", self.x_entries())
        self.compact("Y", self.y_entries(300))
        self.assertTrue(os.path.exists(os.path.join(self.pdir(), "decisions.md")))
        self.assertLessEqual(len(self.backups()), 20)


if __name__ == "__main__":
    unittest.main()
