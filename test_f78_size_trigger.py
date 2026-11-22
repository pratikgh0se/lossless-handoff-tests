"""F78 Size trigger (amends F67.b), gated by the marker file `<hooks dir>/.recall-size-trigger`. Code-blind: written from
contract-0.18.md and litm-trigger-design.md section 3. With the marker and no F67.b cue, auto-recall fires when the prompt
does not start with `/`, the context count is at least 100,000 tokens (env HANDOFF_AUTO_RECALL_TOKENS, 10,000 to
1,000,000) and the prompt holds 1 or more identifiers (F75 rule) that are F77 subjects in the current session and are not
existing paths below cwd. Output: the F75 history output for the first 3 such identifiers. Off switch
HANDOFF_AUTO_RECALL_SIZE=0. Health row `"cue": "size"`. Without the marker, auto-recall is byte-identical to 0.17.0."""
import json, os, re, shutil, unittest

from history_common import SID1, HIST_LINE1, ts, entry
from levers_common import usage_entry
from test_f75_auto_recall_history import Base, HIST_HEADER, FULL_RE
from test_f67_auto_recall import HEADER as WORD_HEADER
from helpers import run_install, run_uninstall, installed_home
from test_f64_minimal_install import Base as InstBase, DEFAULTS_REL

MARKER = ".recall-size-trigger"
PROMPT = "please change queue-depth to 40 now"
NEEDS = "recall-size-trigger: needs --auto-recall; skipped"


class Size(Base):
    def setUp(self):
        super().setUp()
        self.marker = os.path.join(self.hooks, MARKER)
        open(self.marker, "w").close()

    def build(self, tokens=150000, key="queue-depth", n=3, prompt=PROMPT):
        recs = self.chain(key, n) + ([usage_entry(tokens, ts="2026-03-01T13:00:00Z")] if tokens is not None else [])
        recs.append(entry("user", prompt, "cur", ts(0, day=2)))
        self.put(SID1, recs)

    def test_f78_fires_with_the_f75_history_output_and_the_size_cue(self):
        self.build()
        out = self.ctx(PROMPT)
        ls = out.split("\n")
        self.assertEqual(ls[0], HIST_HEADER)
        self.assertEqual(ls[1], HIST_LINE1 % ("queue-depth", 3))
        m = FULL_RE.match(ls[-1])
        self.assertTrue(m, ls[-1])
        row = self.rows()[-1]
        self.assertEqual(row["cue"], "size")
        self.assertEqual((row["mode"], row["identifiers"]), ("history", 1))
        self.assertTrue(row["fired"])

    def test_f78_the_current_prompt_is_not_in_the_blocks(self):
        self.build(prompt=PROMPT + " CURRENTMARK")
        self.assertNotIn("CURRENTMARK", self.ctx(PROMPT + " CURRENTMARK"))

    def test_f78_without_the_marker_nothing_fires(self):
        os.remove(self.marker)
        self.build()
        self.assertEqual(self.run_hook(PROMPT).strip(), "")
        self.assertTrue(all(r.get("cue") != "size" for r in self.rows()))

    def test_f78_a_cued_prompt_gives_the_same_bytes_with_and_without_the_marker(self):
        self.build(tokens=150000)
        prompt = "what did we decide about queue-depth"
        with_marker = self.run_hook(prompt)
        os.remove(self.marker)
        without = self.run_hook(prompt)
        self.assertEqual(with_marker, without)
        self.assertNotEqual(without.strip(), "")
        self.assertNotEqual(self.rows()[-1].get("cue"), "size")

    def test_f78_a_slash_prompt_does_not_fire(self):
        self.build(prompt="/" + PROMPT)
        self.assertEqual(self.run_hook("/" + PROMPT).strip(), "")

    def test_f78_below_100000_tokens_no_output_and_at_100000_it_fires(self):
        self.build(tokens=99999)
        self.assertEqual(self.run_hook(PROMPT).strip(), "")
        self.build(tokens=100000)
        self.assertNotEqual(self.run_hook(PROMPT).strip(), "")

    def test_f78_no_usage_entry_means_no_output(self):
        self.build(tokens=None)
        self.assertEqual(self.run_hook(PROMPT).strip(), "")

    def test_f78_env_override_of_the_threshold(self):
        self.build(tokens=30000)
        self.assertEqual(self.run_hook(PROMPT).strip(), "")
        self.assertNotEqual(self.run_hook(PROMPT, extra={"HANDOFF_AUTO_RECALL_TOKENS": "20000"}).strip(), "")
        self.build(tokens=150000)
        self.assertEqual(self.run_hook(PROMPT, extra={"HANDOFF_AUTO_RECALL_TOKENS": "200000"}).strip(), "")
        self.build(tokens=50000)
        for v in ("5000", "2000000", "abc"):
            with self.subTest(v):
                self.assertEqual(self.run_hook(PROMPT, extra={"HANDOFF_AUTO_RECALL_TOKENS": v}).strip(), "")

    def test_f78_off_switch(self):
        self.build()
        self.assertEqual(self.run_hook(PROMPT, extra={"HANDOFF_AUTO_RECALL_SIZE": "0"}).strip(), "")
        self.assertNotEqual(self.run_hook(PROMPT, extra={"HANDOFF_AUTO_RECALL_SIZE": "1"}).strip(), "")

    def test_f78_the_off_switch_of_auto_recall_still_wins(self):
        self.build()
        self.assertEqual(self.run_hook(PROMPT, extra={"HANDOFF_AUTO_RECALL": "0"}).strip(), "")

    def test_f78_an_identifier_that_is_not_a_subject_does_not_fire(self):
        self.build(n=1)  # one mention
        self.assertEqual(self.run_hook(PROMPT).strip(), "")
        self.build(n=40 + 2)  # 42 text messages
        self.assertEqual(self.run_hook(PROMPT).strip(), "")

    def test_f78_a_prompt_without_an_identifier_does_not_fire(self):
        self.build()
        self.assertEqual(self.run_hook("please change the depth to 40 now").strip(), "")

    def test_f78_an_existing_path_below_cwd_is_not_an_identifier_here(self):
        os.makedirs(os.path.join(self.proj, "conf"))
        open(os.path.join(self.proj, "conf", "queue-depth.yaml"), "w").close()
        self.build(key="conf/queue-depth.yaml", prompt="please open conf/queue-depth.yaml now")
        self.assertEqual(self.run_hook("please open conf/queue-depth.yaml now").strip(), "")

    def test_f78_only_the_subject_identifiers_get_a_block_and_at_most_3(self):
        recs = []
        for i, k in enumerate(("k-one", "k-two", "k-three", "k-four")):
            recs += self.chain(k, 3, start=i * 4)
        recs += [entry("user", "single-mention here", "s1", ts(50)), usage_entry(150000, ts="2026-03-01T13:00:00Z"),
                 entry("user", "x", "cur", ts(0, day=2))]
        self.put(SID1, recs)
        out = self.ctx("please set single-mention and k-two and k-one and k-three and k-four")
        self.assertEqual(self.blocks(out), ["k-two", "k-one", "k-three"], out)

    def test_f78_the_current_session_only(self):
        other = "73000002-0000-4000-8000-000000000002"
        self.put(other, [usage_entry(150000, ts="2026-03-01T13:00:00Z")] +
                 [dict(r, sessionId=other) for r in self.chain("queue-depth", 3)])
        self.put(SID1, [usage_entry(150000, ts="2026-03-01T13:00:00Z"), entry("user", PROMPT, "cur", ts(0, day=2))])
        self.assertEqual(self.run_hook(PROMPT).strip(), "", "the subject must be a subject in the current session")

    def test_f78_an_injected_history_block_from_this_turn_is_not_repeated_by_the_guard(self):
        # F77 condition 5: an injected `history of <subject>:` block is evidence, so the guard stays quiet for it
        self.build()
        out = self.ctx(PROMPT)
        self.assertIn("history of queue-depth:", out)

    def test_f78_runs_inside_the_budget_and_never_errors(self):
        self.build()
        self.run_hook(PROMPT)
        self.assertLess(self.elapsed, 5.0)
        self.assertEqual(self.run_hook(PROMPT, raw="{not json").strip(), "")
        self.assertEqual(self.run_hook(PROMPT, transcript=False).strip(), "")


class Install(InstBase):
    FLAG = "--recall-size-trigger"

    def run_i(self, *args):
        r = run_install(self.home, *args)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.wait_first_index()
        return r

    def marker(self):
        return self.p(".claude/hooks/" + MARKER)

    def test_f78_the_flag_with_auto_recall_writes_the_marker(self):
        self.run_i("--auto-recall", self.FLAG)
        self.assertTrue(os.path.isfile(self.marker()))
        self.assertTrue(os.path.isfile(self.p(".claude/hooks/auto-recall.py")))

    def test_f78_the_flag_without_auto_recall_prints_the_needs_line_and_exits_0(self):
        r = self.run_i(self.FLAG)
        self.assertIn(NEEDS, r.stdout + r.stderr)
        self.assertFalse(os.path.exists(self.marker()))
        self.assertFalse(os.path.exists(self.p(".claude/hooks/auto-recall.py")))

    def test_f78_the_default_install_has_no_marker(self):
        home, _ = installed_home()
        self.assertFalse(os.path.exists(os.path.join(home, ".claude", "hooks", MARKER)))

    def test_f78_uninstall_removes_the_marker(self):
        self.run_i("--auto-recall", self.FLAG)
        r = run_uninstall(self.home)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(os.path.exists(self.marker()))

    def test_f78_dry_run_lists_it_only_when_given(self):
        r = run_install(self.home, "--dry-run", "--auto-recall", self.FLAG)
        self.assertIn(MARKER, r.stdout + r.stderr)
        r = run_install(self.home, "--dry-run", "--auto-recall")
        plan = "\n".join(l for l in (r.stdout + r.stderr).split("\n") if "not selected" not in l)
        self.assertNotIn(MARKER, plan)

    def test_f78_help_lists_both_flags(self):
        r = run_install(self.home, "--help")
        self.assertIn(self.FLAG, r.stdout)
        self.assertIn("--no-recall-size-trigger", r.stdout)

    def test_f78_save_defaults_writes_the_key_and_a_plain_run_applies_it(self):
        self.run_i("--auto-recall", self.FLAG, "--save-defaults")
        with open(os.path.join(self.home, DEFAULTS_REL)) as f:
            lines = f.read().split("\n")
        self.assertIn("recall_size_trigger=1", lines)
        self.assertIn("auto_recall=1", lines)
        home2 = os.path.join(self.tmp, "home2")
        os.makedirs(os.path.join(home2, ".config", "lossless-handoff"))
        shutil.copy(os.path.join(self.home, DEFAULTS_REL), os.path.join(home2, DEFAULTS_REL))
        r = run_install(home2)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(os.path.isfile(os.path.join(home2, ".claude", "hooks", MARKER)))

    def test_f78_a_saved_default_without_auto_recall_prints_the_needs_line(self):
        os.makedirs(os.path.join(self.home, ".config", "lossless-handoff"), exist_ok=True)
        with open(os.path.join(self.home, DEFAULTS_REL), "w") as f:
            f.write("recall_size_trigger=1\n")
        r = self.run_i()
        self.assertIn(NEEDS, r.stdout + r.stderr)
        self.assertFalse(os.path.exists(self.marker()))

    def test_f78_no_flag_turns_it_off_for_one_run(self):
        self.run_i("--auto-recall", self.FLAG, "--save-defaults")
        home2 = os.path.join(self.tmp, "home2")
        os.makedirs(os.path.join(home2, ".config", "lossless-handoff"))
        shutil.copy(os.path.join(self.home, DEFAULTS_REL), os.path.join(home2, DEFAULTS_REL))
        r = run_install(home2, "--no-recall-size-trigger")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(os.path.exists(os.path.join(home2, ".claude", "hooks", MARKER)))
        self.assertTrue(os.path.isfile(os.path.join(home2, ".claude", "hooks", "auto-recall.py")))

    def test_f78_a_rerun_keeps_the_marker(self):
        self.run_i("--auto-recall", self.FLAG)
        self.run_i()
        self.assertTrue(os.path.isfile(self.marker()))


if __name__ == "__main__":
    unittest.main()
