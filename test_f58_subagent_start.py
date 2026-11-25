"""F58 Rules at subagent start: ACs 261-267 of docs/spec.md. Code-blind: written from the spec only.
`postcompact-inject.py --subagent-start` reads the SubagentStart hook JSON on stdin and prints
{"hookSpecificOutput": {"hookEventName": "SubagentStart", "additionalContext": ...}} with the active `rule` entries
of the project ledger (newest first) and the recall line. Installer tests use a temp HOME (helpers refuse the real
HOME) with launchctl and the network off."""
import json, os, re, shutil, subprocess, sys, tempfile, time, unittest

import helpers
from helpers import HookCase, no_recall, run_install, run_uninstall
from test_f44_recall import RECALL_LINE, key_for, canon, canon_lines
from test_f55_recall_agent import MARKER, SENTENCE
from test_content import git

HEADER = ("Project rules for this repo (standing; from the Lossless Handoff decisions list; "
          "the user's latest words win):")
# F66.b (0.14.0): when rules are injected, the text starts with this line, then the header below it.
PREAMBLE = ("These are the user's standing rules for the main session of this project. Apply only the rules that fit "
            "your task. Your task brief comes first.")
RESTART_LINE = "New hook event (SubagentStart): restart open Claude Code sessions to load it."
SID = "58585858-0000-4000-8000-000000000058"
AGENT = "a1b2c3d4e5f6a7b8"
ATYPE = "general-purpose"
RULE_A = "- D1 [2026-10-01] [rule] RULEAAA never put tool names in commit messages | why: user said so"
DEC = "- D2 [2026-10-02] [decision] DECBBB use sqlite for storage | why: simple"
RULE_B = "- D3 [2026-10-03] [rule] RULECCC run at most 3 builders at once | why: load"
TASK = "- D4 [2026-10-04] [task] TASKDDD approve the release draft | why: one off"


def rule_line(n, width=300):
    head = "- D%d [2026-10-20] [rule] " % n
    tail = " | why: r"
    return head + ("RULE%d " % n).ljust(width - len(head) - len(tail), "x") + tail


class Base(HookCase):
    LEDGER_ENV = None  # the ledger switch stays at its default

    def setUp(self):
        super().setUp()
        self.rt = os.path.realpath(self.tmp)
        self.home = os.path.join(self.rt, "home")
        os.makedirs(self.home, exist_ok=True)
        self.hd = os.path.join(self.home, ".local", "state", "claude-handoffs")
        self.proj = os.path.join(self.rt, "r", "proj")
        os.makedirs(self.proj)
        git(self.proj, "init", "-q")
        self.pdir = os.path.join(self.hd, "projects", key_for(self.proj))
        self.elapsed = None

    def write_ledger(self, lines):
        os.makedirs(self.pdir, exist_ok=True)
        with open(os.path.join(self.pdir, "decisions.md"), "w") as f:
            f.write("# Project decisions: %s\n%s\n" % (self.proj, "\n".join(lines)))
        return os.path.join(self.pdir, "decisions.md")

    def start_input(self, cwd=None, agent=AGENT, atype=ATYPE):
        return {"session_id": SID, "transcript_path": os.path.join(self.home, ".claude", "projects", "x", SID + ".jsonl"),
                "cwd": cwd or self.proj, "prompt_id": "p-0001", "agent_id": agent, "agent_type": atype,
                "hook_event_name": "SubagentStart"}

    def sub(self, payload=None, raw=None, extra=None, devnull=False):
        """Run the hook with --subagent-start. Returns CompletedProcess; self.elapsed holds the run time."""
        if raw is None and payload is None:
            payload = self.start_input()
        if raw is None:
            raw = json.dumps(payload)
        t0 = time.time()
        r = subprocess.run([sys.executable, helpers.POST, "--subagent-start"], input=None if devnull else raw,
                           stdin=subprocess.DEVNULL if devnull else None, capture_output=True, text=True,
                           env=self.env(None, extra), timeout=30)
        self.elapsed = time.time() - t0
        return r

    def sub_ctx(self, **kw):
        r = self.sub(**kw)
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout)
        self.assertTrue(r.stdout.strip(), "no output")
        o = json.loads(r.stdout)
        self.assertEqual(set(o), {"hookSpecificOutput"}, o)
        h = o["hookSpecificOutput"]
        self.assertEqual(h["hookEventName"], "SubagentStart")
        self.assertEqual(set(h), {"hookEventName", "additionalContext"}, h)
        return h["additionalContext"]

    def put_agent_file(self, text):
        p = os.path.join(self.home, ".claude", "agents", "recall.md")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(text)

    def assert_silent(self, r):
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""), (r.stdout, r.stderr))


# ---------------------------------------------------------------- AC 261
class Content(Base):
    def setUp(self):
        super().setUp()
        self.write_ledger([RULE_A, DEC, RULE_B, TASK])

    def test_ac261_header_rules_newest_first_recall_line(self):
        ctx = self.sub_ctx()
        self.assertTrue(ctx.startswith(PREAMBLE + "\n" + HEADER), ctx[:300])
        lines = ctx.split("\n")
        self.assertEqual(lines.count(RULE_A), 1)
        self.assertEqual(lines.count(RULE_B), 1)
        self.assertLess(lines.index(RULE_B), lines.index(RULE_A), "newest rule (D3) must come first")
        recall = [l for l in lines if l.startswith("- recall: ")]
        self.assertEqual(canon_lines(recall), [RECALL_LINE])
        lines = canon_lines(lines)
        self.assertLess(lines.index(RULE_A), lines.index(RECALL_LINE), "rules come before the recall line")
        self.assertEqual(lines.index(PREAMBLE), 0)
        self.assertEqual(lines.index(HEADER), 1)

    def test_ac261_no_decision_and_no_task(self):
        r = self.sub()
        self.assertEqual(r.returncode, 0)
        for token in ("DECBBB", "TASKDDD", "D2 ", "D4 "):
            self.assertNotIn(token, r.stdout)
        ctx = self.sub_ctx()
        self.assertNotIn("DECBBB", ctx)
        self.assertNotIn("TASKDDD", ctx)

    def test_ac261_finishes_within_two_seconds(self):
        self.sub_ctx()
        self.assertLess(self.elapsed, 2.0)

    def test_ac261_only_active_rules_are_listed(self):
        self.write_ledger([
            "- D1 [2026-10-01] SUPERSEDED by D2 [2026-10-02]: [rule] OLDRULE use 5 builders | because: replaced",
            "- D2 [2026-10-02] [rule] NEWRULE use 3 builders | why: load",
            "- D3 [2026-10-03] [rule] DONERULE keep the draft private | why: x",
            "- D4 [2026-10-04] RESOLVED [2026-10-05]: finished | was: [task] TASKGONE approve it | why: y"])
        ctx = self.sub_ctx()
        self.assertIn("NEWRULE", ctx)
        self.assertIn("DONERULE", ctx)
        self.assertNotIn("OLDRULE", ctx)
        self.assertNotIn("TASKGONE", ctx)

    def test_ac261_rules_of_another_project_are_not_listed(self):
        other = os.path.join(self.rt, "r", "other")
        os.makedirs(other)
        git(other, "init", "-q")
        d = os.path.join(self.hd, "projects", key_for(other))
        os.makedirs(d)
        with open(os.path.join(d, "decisions.md"), "w") as f:
            f.write("# Project decisions: %s\n- D1 [2026-10-01] [rule] OTHERRULE only for the other repo | why: x\n" % other)
        ctx = self.sub_ctx()
        self.assertNotIn("OTHERRULE", ctx)
        ctx2 = self.sub_ctx(payload=self.start_input(cwd=other))
        self.assertIn("OTHERRULE", ctx2)
        self.assertNotIn("RULEAAA", ctx2)

    def test_ac261_subdirectory_cwd_uses_the_project_root(self):
        sub = os.path.join(self.proj, "pkg", "deep")
        os.makedirs(sub)
        ctx = self.sub_ctx(payload=self.start_input(cwd=sub))
        self.assertIn("RULEAAA", ctx)

    def test_f58a_recall_line_has_f55c_sentence_when_agent_file_has_marker(self):
        self.put_agent_file(MARKER + "\nolder content\n")
        ctx = self.sub_ctx()
        recall = [l for l in ctx.split("\n") if l.startswith("- recall: ")]
        self.assertEqual(len(recall), 1)
        self.assertEqual(canon(recall[0], SENTENCE), RECALL_LINE + " " + SENTENCE, recall[0][-300:])

    def test_f58a_recall_line_has_no_sentence_for_a_foreign_agent_file(self):
        self.put_agent_file("---\nname: recall\n---\nmine\n")
        self.assertNotIn(SENTENCE, self.sub_ctx())

    def test_ac261_works_for_any_agent_type_and_empty_type(self):
        for atype in ("Explore", "recall", ""):
            with self.subTest(atype=atype):
                ctx = self.sub_ctx(payload=self.start_input(atype=atype))
                self.assertIn("RULEAAA", ctx)


# ---------------------------------------------------------------- AC 262
class Isolation(Base):
    def test_ac262_main_handoff_and_agent_note_never_appear(self):
        self.write_ledger([RULE_A, RULE_B])
        os.makedirs(self.hd, exist_ok=True)
        files = {SID + "-latest.md": "HANDOFFTOKEN-LATEST-91 the main handoff\n",
                 SID + "-agent.md": "AGENTNOTETOKEN-92 the main agent note\n",
                 SID + "-a-%s-latest.md" % AGENT: "TWINLATEST-93 handoff of this subagent\n",
                 SID + "-a-%s-agent.md" % AGENT: "TWINNOTE-94 note of this subagent\n"}
        for name, text in files.items():
            with open(os.path.join(self.hd, name), "w") as f:
                f.write(text)
        r = self.sub()
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertIn("RULEAAA", r.stdout)  # not empty: the rules are there
        for token in ("HANDOFFTOKEN-LATEST-91", "AGENTNOTETOKEN-92", "TWINLATEST-93", "TWINNOTE-94"):
            self.assertNotIn(token, r.stdout)

    def test_ac262_works_when_the_handoff_files_exist_without_a_ledger(self):
        self.put_latest("HANDOFFTOKEN-LATEST-95 body\n", SID)
        self.agent_file("AGENTNOTETOKEN-96 note\n", SID)
        r = self.sub()
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertNotIn("HANDOFFTOKEN-LATEST-95", r.stdout)
        self.assertNotIn("AGENTNOTETOKEN-96", r.stdout)


# ---------------------------------------------------------------- AC 263
class Cut(Base):
    def test_ac263_context_cut_at_4000_at_an_entry_boundary(self):
        lines = [rule_line(n) for n in range(1, 61)]
        ledger_path = self.write_ledger(lines)
        ctx = self.sub_ctx()
        # AMENDED by F88.c: the full text is cut at 4,000 characters as before; the rules left follow as index lines
        # after an INDEX line (total 9,900 at most), then the pointer line.
        self.assertLessEqual(len(ctx), 9900, len(ctx))
        self.assertTrue(ctx.startswith(PREAMBLE + "\n" + HEADER))
        out_lines = [l for l in ctx.split("\n") if l.strip()]
        shown = [l for l in out_lines if l in set(lines)]
        self.assertEqual(len(shown), len([l for l in out_lines if l.startswith("- D") and l in set(lines)]))
        ids = [int(re.match(r"- D(\d+) ", l).group(1)) for l in shown]
        self.assertGreaterEqual(len(ids), 4)
        self.assertLess(len(ids), 60)
        self.assertEqual(ids, list(range(60, 60 - len(ids), -1)), "newest first, no gaps")
        self.assertLessEqual(sum(len(l) + 1 for l in shown), 4000, "full text stays within 4,000")
        self.assertEqual(out_lines.count("INDEX (rules not shown in full above):"), 1)
        more = [l for l in out_lines if l.startswith("[more rules:")]
        self.assertEqual(len(more), 1, ctx[-600:])
        self.assertTrue(more[0].endswith("]"), more[0])
        self.assertIn("recall.py decisions --kind rule", more[0])
        self.assertIn(ledger_path, more[0])
        self.assertNotIn('recall.py search "rule"', more[0])

    def test_ac263_no_more_rules_line_when_everything_fits(self):
        self.write_ledger([RULE_A, RULE_B])
        self.assertNotIn("[more rules:", self.sub_ctx())

    def test_ac263_cut_with_the_agent_file_sentence_still_within_9900(self):
        self.put_agent_file(MARKER + "\n")
        self.write_ledger([rule_line(n) for n in range(1, 61)])
        self.assertLessEqual(len(self.sub_ctx()), 9900)


# ---------------------------------------------------------------- AC 264
class Empty(Base):
    def test_ac264_no_ledger_only_the_recall_line(self):
        ctx = self.sub_ctx()
        self.assertEqual(canon(ctx.strip()), RECALL_LINE)
        self.assertNotIn(HEADER, ctx)

    def test_ac264_ledger_without_active_rule_only_the_recall_line(self):
        self.write_ledger([DEC, TASK])
        ctx = self.sub_ctx()
        self.assertEqual(canon(ctx.strip()), RECALL_LINE)

    def test_ac264_empty_ledger_file_only_the_recall_line(self):
        self.write_ledger([])
        self.assertEqual(canon(self.sub_ctx().strip()), RECALL_LINE)

    @no_recall
    def test_ac264_no_ledger_and_no_recall_script_prints_nothing(self):
        self.assert_silent(self.sub())

    @no_recall
    def test_ac264_decisions_only_and_no_recall_script_prints_nothing(self):
        self.write_ledger([DEC, TASK])
        self.assert_silent(self.sub())

    @no_recall
    def test_f58b_rules_without_recall_script_have_no_recall_line(self):
        self.write_ledger([RULE_A])
        ctx = self.sub_ctx()
        self.assertTrue(ctx.startswith(PREAMBLE + "\n" + HEADER))
        self.assertIn("RULEAAA", ctx)
        self.assertNotIn("- recall:", ctx)


# ---------------------------------------------------------------- AC 265
class Off(Base):
    def test_ac265_rules_off_prints_nothing(self):
        self.write_ledger([RULE_A, RULE_B])
        self.assert_silent(self.sub(extra={"HANDOFF_SUBAGENT_RULES": "0"}))

    def test_ac265_rules_on_value_still_works(self):
        self.write_ledger([RULE_A])
        r = self.sub(extra={"HANDOFF_SUBAGENT_RULES": "1"})
        self.assertIn("RULEAAA", r.stdout)

    def test_ac265_garbage_and_empty_stdin_print_nothing(self):
        self.write_ledger([RULE_A, RULE_B])
        for raw in ("not json", "", "{", "[1, 2]", "null", "\x00\xff garbage"):
            with self.subTest(raw=raw):
                self.assert_silent(self.sub(raw=raw))

    def test_ac265_no_stdin_prints_nothing(self):
        self.write_ledger([RULE_A])
        self.assert_silent(self.sub(devnull=True))

    def test_ac265_missing_cwd_prints_nothing(self):
        self.write_ledger([RULE_A])
        p = self.start_input()
        del p["cwd"]
        self.assert_silent(self.sub(payload=p))
        self.assert_silent(self.sub(raw="{}"))

    def test_ac265_never_exits_non_zero(self):
        for raw in ("not json", "", "{}", json.dumps(self.start_input(cwd=os.path.join(self.rt, "nope")))):
            with self.subTest(raw=raw[:30]):
                self.assertEqual(self.sub(raw=raw).returncode, 0)


# ---------------------------------------------------------------- AC 266
class Install(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="f58-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self.sp = os.path.join(self.home, ".claude", "settings.json")
        self.cmd = "python3 %s/.claude/hooks/postcompact-inject.py --subagent-start" % self.home

    def wait_first_index(self):
        log = os.path.join(self.home, ".local", "state", "claude-handoffs", "recall", "index-all.log")
        end = time.time() + 20
        while time.time() < end and not (os.path.exists(log) and os.path.getsize(log) > 0):
            time.sleep(0.2)
        time.sleep(0.3)

    def install(self, *args):
        r = run_install(self.home, *args)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.wait_first_index()
        return r

    def uninstall(self):
        r = run_uninstall(self.home)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r

    def settings(self):
        with open(self.sp) as f:
            return json.load(f)

    def sub_entries(self, s=None):
        """All (group index, hook dict) under SubagentStart."""
        s = s or self.settings()
        return [(i, h) for i, g in enumerate(s.get("hooks", {}).get("SubagentStart", [])) for h in g.get("hooks", [])]

    def ours(self, s=None):
        return [h for _, h in self.sub_entries(s) if "--subagent-start" in h.get("command", "")]

    @staticmethod
    def lines(r):
        return [l.strip() for l in (r.stdout + r.stderr).split("\n")]

    def test_ac266_one_subagent_start_entry_with_the_command(self):
        self.install("--no-nightly")
        ours = self.ours()
        self.assertEqual(len(ours), 1, self.sub_entries())
        self.assertEqual(ours[0]["command"], self.cmd)
        self.assertEqual(ours[0].get("type"), "command")
        self.assertEqual(ours[0].get("timeout"), 10)
        self.assertEqual(len(self.settings()["hooks"]["SubagentStart"]), 1)

    def test_ac266_second_install_adds_none_and_no_restart_line(self):
        r1 = self.install("--no-nightly")
        self.assertEqual(self.lines(r1).count(RESTART_LINE), 1, r1.stdout)
        before = self.settings()
        r2 = self.install("--no-nightly")
        self.assertEqual(len(self.ours()), 1)
        self.assertEqual(self.settings()["hooks"]["SubagentStart"], before["hooks"]["SubagentStart"])
        self.assertNotIn(RESTART_LINE, self.lines(r2))

    def test_ac266_restart_line_prints_again_only_when_the_entry_is_added_again(self):
        self.install("--no-nightly")
        s = self.settings()
        del s["hooks"]["SubagentStart"]
        with open(self.sp, "w") as f:
            json.dump(s, f)
        r = self.install("--no-nightly")
        self.assertEqual(self.lines(r).count(RESTART_LINE), 1, r.stdout)
        self.assertEqual(len(self.ours()), 1)

    def test_ac266_dry_run_writes_nothing(self):
        r = run_install(self.home, "--no-nightly", "--dry-run")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(os.path.exists(self.sp))
        self.assertFalse(os.path.exists(os.path.join(self.home, ".claude", "hooks", "postcompact-inject.py")))

    def test_ac266_dry_run_keeps_existing_settings_without_the_entry(self):
        os.makedirs(os.path.dirname(self.sp))
        text = json.dumps({"hooks": {"PreCompact": [{"hooks": [{"type": "command", "command": "echo other"}]}]}})
        with open(self.sp, "w") as f:
            f.write(text)
        r = run_install(self.home, "--no-nightly", "--dry-run")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(self.sp) as f:
            self.assertEqual(f.read(), text)

    def test_ac266_uninstall_removes_it_and_keeps_other_hooks(self):
        os.makedirs(os.path.dirname(self.sp))
        foreign = {"type": "command", "command": "echo mine-subagent"}
        other = {"type": "command", "command": "echo other-precompact"}
        with open(self.sp, "w") as f:
            json.dump({"hooks": {"SubagentStart": [{"hooks": [foreign]}], "PreCompact": [{"hooks": [other]}]}}, f)
        self.install("--no-nightly")
        self.assertEqual(len(self.ours()), 1)
        self.assertIn(foreign, [h for _, h in self.sub_entries()])
        self.uninstall()
        s = self.settings()
        self.assertNotIn("--subagent-start", json.dumps(s))
        self.assertEqual([h for _, h in self.sub_entries(s)], [foreign])
        self.assertIn(other, [h for g in s["hooks"]["PreCompact"] for h in g["hooks"]])

    def test_ac266_uninstall_after_plain_install_leaves_no_subagent_start_entry(self):
        self.install("--no-nightly")
        self.uninstall()
        if os.path.exists(self.sp):
            self.assertNotIn("--subagent-start", json.dumps(self.settings()))


# ---------------------------------------------------------------- AC 267
class Health(Base):
    def last_row(self):
        with open(self.health_path()) as f:
            return json.loads([l for l in f.read().split("\n") if l][-1])

    def test_ac267_health_row_after_ac261_run(self):
        self.write_ledger([RULE_A, DEC, RULE_B, TASK])
        ctx = self.sub_ctx()
        row = self.last_row()
        self.assertEqual(row["event"], "subagent_start")
        self.assertEqual(row["agent_type"], ATYPE)
        self.assertEqual(row["rules"], 2)
        self.assertIsInstance(row["chars"], int)
        self.assertGreater(row["chars"], 0)
        self.assertEqual(row["hook_version"], helpers.HOOKS_VERSION)
        self.assertGreater(len(ctx), 0)

    def test_ac267_each_run_appends_one_row(self):
        self.write_ledger([RULE_A, RULE_B])
        self.sub_ctx()
        n = len(self.health_lines())
        self.sub_ctx(payload=self.start_input(atype="Explore"))
        rows = self.health_lines()
        self.assertEqual(len(rows), n + 1)
        self.assertEqual(json.loads(rows[-1])["agent_type"], "Explore")

    def test_ac267_row_without_rules_counts_zero(self):
        self.sub_ctx()  # no ledger: only the recall line
        row = self.last_row()
        self.assertEqual(row["event"], "subagent_start")
        self.assertEqual(row["rules"], 0)
        self.assertEqual(row["hook_version"], helpers.HOOKS_VERSION)


if __name__ == "__main__":
    unittest.main()
