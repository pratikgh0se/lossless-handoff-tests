"""F62 window rules, ACs 298-300 (code-blind: written from docs/spec.md of the hardening-drift branch).
298: `compactMetadata.trigger` manual records are skipped, records without a trigger are kept.
299: a learned window below 100,000 or above 2,100,000 is not used: default 200,000.
300: the learned or default window stays in the meta file while the context grows, even if the history is deleted;
it is learned again at once after a compaction (the context is smaller than at the last call).
Gap: the 6 hour expiry is not tested. The spec names no meta field or other mechanism to move the clock.
Gap: the 1.5 s scan budget is not tested. The spec gives no outcome that a test can trigger without huge files."""
import json, os, unittest

from test_f62_nudge_window import NudgeBase, boundary


class RuleBase(NudgeBase):
    def boundaries(self, items):
        """Each item is a preTokens int (no trigger field) or a (preTokens, trigger) pair (trigger auto or manual)."""
        out = []
        for i, it in enumerate(items):
            if isinstance(it, tuple):
                pre, trig = it
                b = boundary(pre, i)
                b["compactMetadata"]["trigger"] = trig
            else:
                b = boundary(it, i)
                del b["compactMetadata"]["trigger"]
            out.append(b)
        return out


class Triggers(RuleBase):
    def test_ac298_only_manual_boundary_is_not_learned(self):
        self.probe(25000, history=[(30000, "manual")])
        self.assertWindow(200000, "default")

    def test_ac298_boundary_without_trigger_is_kept(self):
        self.probe(160000, history=[267000])
        self.assertWindow(300000, "learned")

    def test_ac298_manual_next_to_auto_uses_only_auto(self):
        self.probe(160000, history=[(30000, "manual"), (267000, "auto")])
        self.assertWindow(300000, "learned")

    def test_ac298_manual_in_current_transcript_falls_to_sibling_only_when_no_count(self):
        # the current transcript holds only a manual record, so it has no count: the sibling counts are used
        self.probe(160000, history=[(30000, "manual")], sibling=[167000, 167000, 167000])
        self.assertWindow(200000, "learned")


class Bounds(RuleBase):
    def test_ac299_huge_pretokens_is_default(self):
        self.probe(160000, history=[10 ** 15])
        self.assertWindow(200000, "default")

    def test_ac299_just_above_upper_bound_is_default(self):
        self.probe(160000, history=[2068000])  # 2,068,000 + 33,000 = 2,101,000
        self.assertWindow(200000, "default")

    def test_ac299_upper_bound_itself_is_learned(self):
        self.probe(160000, history=[2067000])  # 2,100,000
        self.assertWindow(2100000, "learned")

    def test_ac299_below_lower_bound_is_default(self):
        self.probe(160000, history=[66000])  # 99,000
        self.assertWindow(200000, "default")

    def test_ac299_lower_bound_itself_is_learned(self):
        self.probe(100000, history=[67000])  # 100,000
        self.assertWindow(100000, "learned")


class Cache(RuleBase):
    SID = "f62b0000-0000-4000-8000-000000000001"

    def test_ac300_learned_window_survives_deleted_history(self):
        self.probe(301000, history=[367000, 367000, 368000], sid=self.SID)
        self.assertWindow(400000, "learned")
        self.probe(310000, history=[], sid=self.SID)  # history gone, context grew
        self.assertWindow(400000, "learned")

    def test_ac300_default_window_is_kept_while_context_grows(self):
        self.probe(100000, history=[], sid=self.SID)
        self.assertWindow(200000, "default")
        self.probe(110000, history=[367000, 367000, 368000], sid=self.SID)  # history appears, context grew
        self.assertWindow(200000, "default")

    def test_ac300_compaction_learns_again_at_once(self):
        self.probe(301000, history=[367000, 367000, 368000], sid=self.SID)
        self.assertWindow(400000, "learned")
        self.probe(60000, history=[367000, 367000, 368000, 167000, 167000, 167000, 167000, 167000, 167000],
                   sid=self.SID)  # the context is smaller than at the last call
        self.assertWindow(self.expected_after_compaction(), "learned")

    @staticmethod
    def expected_after_compaction():
        # counts: 367000, 367000, 368000 and six times 167000 -> sorted median (9 values) = 167000 -> 200000
        return 200000

    def test_ac300_default_relearned_after_compaction(self):
        self.probe(100000, history=[], sid=self.SID)
        self.assertWindow(200000, "default")
        self.probe(50000, history=[367000, 367000, 368000], sid=self.SID)
        self.assertWindow(400000, "learned")


if __name__ == "__main__":
    unittest.main()
