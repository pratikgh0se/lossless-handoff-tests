"""Amendments of 2026-11-22 to the 0.16.0 contract (F68, F69, F70, F71, F72 and the file modes). Code-blind: written from
contract-0.16.md only. See the class docstrings for the rule that each class covers."""
import json, os, re, stat, subprocess, sys, threading, unittest

from helpers import copy_hook_scripts, run_install, run_uninstall
from levers_common import (Lab, Mcp, RULE_A, RULE_SENTENCE, additional_context, usage_entry, write_transcript)
from test_f55_recall_agent import MARKER as AGENT_MARKER, SENTENCE as AGENT_SENTENCE
from test_f58_subagent_start import PREAMBLE
from test_f67_auto_recall import HookBase, HEADER
from test_f71_claim_guard import Base as GuardBase, CUES, REASON, user, tool_use, tool_result, text_reply, injection, SCRIPT as GUARD
from test_f70_reanchor import Base as AnchorBase

UNSET_PATH = "~/.claude/hooks/recall.py"


def mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


class Hooks(Lab):
    """A fake HOME with the live hooks folder (no marker, no optional files) and a private folder P."""
    keep = ()

    def setUp(self):
        super().setUp()
        self.n = 0
        self.ledger([RULE_A])

    def private(self, **kw):
        self.n += 1
        d = os.path.join(self.tmp, "priv%d" % self.n)
        os.makedirs(d)
        copy_hook_scripts(d)
        for n in ("recall-mcp.py", "reanchor.py", "claim-guard.py"):
            p = os.path.join(d, n)
            if os.path.exists(p) and not kw.get(n):
                os.remove(p)
        return d

    def run_in(self, folder, name, args=(), payload=None, override=None, extra=None):
        e = dict(extra or {})
        if override:
            e["HANDOFF_HOOKS_HOME"] = override
        return subprocess.run([sys.executable, os.path.join(folder, name), *args], input=json.dumps(payload),
                              capture_output=True, text=True, env=self.env(e), cwd=self.proj, timeout=60)

    def part1(self, folder, override, source="compact"):
        r = self.run_in(folder, "postcompact-inject.py", ("--ledger", "--part", "1"),
                        {"cwd": self.proj, "session_id": "N", "hook_event_name": "SessionStart", "source": source},
                        override)
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout)
        return r.stdout

    def sub(self, folder, override):
        r = self.run_in(folder, "postcompact-inject.py", ("--subagent-start",),
                        {"session_id": "58585858-0000-4000-8000-000000000058", "cwd": self.proj, "prompt_id": "p-1",
                         "agent_id": "a1b2c3d4e5f6a7b8", "agent_type": "general-purpose",
                         "hook_event_name": "SubagentStart",
                         "transcript_path": os.path.join(self.home, ".claude", "projects", "x", "s.jsonl")}, override)
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout)
        return r.stdout


# ------------------------------------------------------------------ F72 amendment: printed commands name the override
class PrintedPaths(Hooks):
    def test_f72_recall_line_names_the_override_path(self):
        p = self.private()
        for name, out in (("part1", self.part1(p, p)), ("sub", self.sub(p, p))):
            with self.subTest(name):
                text = additional_context(out)
                self.assertIn("python3 %s/recall.py search" % p, text)
                self.assertNotIn("~/.claude/hooks", text)
                self.assertNotIn(UNSET_PATH, text)

    def test_f72_unset_text_is_byte_identical_to_before(self):
        p = self.private()
        text = additional_context(self.part1(p, None))
        pass
        self.assertIn("python3 ~/.claude/hooks/recall.py search", text)
        self.assertNotIn(p, text)
        self.assertNotIn(p, additional_context(self.sub(p, None)))

    def test_f72_a_missing_folder_gives_the_unset_text(self):
        p = self.private()
        text = additional_context(self.part1(p, os.path.join(self.tmp, "no-such-folder")))
        self.assertIn("python3 ~/.claude/hooks/recall.py search", text)

    def test_f72_handoff_text_names_the_override_path(self):
        tp = os.path.join(self.home, ".claude", "projects", "x", "S.jsonl")
        write_transcript(tp, [{"type": "user", "message": {"role": "user", "content": "Please fix the billing exporter now"}},
                              {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "ok"}]}}])
        p = self.private()
        r = subprocess.run([sys.executable, os.path.join(p, "precompact-handoff.py")],
                           input=json.dumps({"session_id": "S", "cwd": self.proj, "trigger": "auto", "transcript_path": tp}),
                           capture_output=True, text=True,
                           env=self.env({"HANDOFF_HAIKU_FALLBACK": "0", "HANDOFF_HOOKS_HOME": p}), cwd=self.proj, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        text = open(os.path.join(self.hd, "S-latest.md")).read()
        self.assertIn("%s/recall.py" % p, text)
        self.assertNotIn("~/.claude/hooks", text)


class AgentFile(Hooks):
    """F72 amendment: with the override, the recall subagent file is looked up only at <override>/agents/recall.md."""

    def home_agent(self):
        d = os.path.join(self.home, ".claude", "agents")
        os.makedirs(d)
        open(os.path.join(d, "recall.md"), "w").write(AGENT_MARKER + "\n")

    def private_agent(self, p):
        os.makedirs(os.path.join(p, "agents"))
        open(os.path.join(p, "agents", "recall.md"), "w").write(AGENT_MARKER + "\n")

    def test_f72_home_agents_file_is_ignored_when_the_override_is_set(self):
        self.home_agent()
        p = self.private()
        for out in (self.part1(p, p), self.sub(p, p)):
            self.assertNotIn(AGENT_SENTENCE, additional_context(out))

    def test_f72_the_override_agents_file_is_used(self):
        p = self.private()
        self.private_agent(p)
        for out in (self.part1(p, p), self.sub(p, p)):
            self.assertIn(AGENT_SENTENCE, additional_context(out))

    def test_f72_unset_uses_the_home_agents_file(self):
        self.home_agent()
        p = self.private()
        self.assertIn(AGENT_SENTENCE, additional_context(self.part1(p, None)))

    def test_f72_a_private_agents_file_is_ignored_when_unset(self):
        p = self.private()
        self.private_agent(p)
        self.assertNotIn(AGENT_SENTENCE, additional_context(self.part1(p, None)))


class AutoRecallFooter(HookBase):
    def test_f72_footer_names_the_override_path_and_unset_is_unchanged(self):
        hooks = os.path.join(self.home, ".claude", "hooks")
        os.makedirs(hooks)
        copy_hook_scripts(hooks)
        self.seed([("user", "We decided to use the postgres database for the billing service BILLINGMARK")])
        p = os.path.join(self.tmp, "priv")
        os.makedirs(p)
        copy_hook_scripts(p)
        payload = {"session_id": self.sid, "transcript_path": self.session, "cwd": self.proj,
                   "prompt": "what did i say about the postgres billing database", "hook_event_name": "UserPromptSubmit"}
        for override in (p, None):
            env = self.env2({"HANDOFF_HOOKS_HOME": p} if override else None)
            r = subprocess.run([sys.executable, os.path.join(p, "auto-recall.py")], input=json.dumps(payload),
                               capture_output=True, text=True, env=env, timeout=30, cwd=self.tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            last = self.context(r.stdout).split("\n")[-1]
            want = ("Open one in full: python3 %s/recall.py open <id>" % p) if override else \
                "Open one in full: python3 ~/.claude/hooks/recall.py open <id>"
            self.assertEqual(last, want)


class McpInstructionsPath(HookBase):
    def test_f72_instructions_name_the_override_path_when_they_name_the_script(self):
        p = os.path.join(self.tmp, "priv")
        os.makedirs(p)
        copy_hook_scripts(p)
        c = Mcp([sys.executable, os.path.join(p, "recall-mcp.py")], self.env2({"HANDOFF_HOOKS_HOME": p}), self.proj)
        try:
            ins = c.init()["result"]["instructions"]
        finally:
            c.close()
        self.assertNotIn("~/.claude/hooks", ins)
        if "recall.py" in ins:
            self.assertIn("%s/recall.py" % p, ins)


# ------------------------------------------------------------------ F68 amendment: marker without a ledger
class MarkerNoLedger(Hooks):
    def setUp(self):
        super().setUp()
        os.remove(os.path.join(self.pdir, "decisions.md"))

    def test_f68_marker_and_no_ledger_prints_the_recall_line_and_the_rule_line(self):
        self.marker()
        for source in ("startup", "resume", "compact"):
            with self.subTest(source):
                out = self.part1(self.hooks, None, source)
                self.assertTrue(out.strip(), "empty output")
                lines = additional_context(out).split("\n")
                i = [k for k, l in enumerate(lines) if l.startswith("- recall:")]
                self.assertEqual(len(i), 1, lines)
                self.assertEqual(lines[i[0] + 1], RULE_SENTENCE)

    def test_f68_no_marker_and_no_ledger_stays_empty(self):
        for source in ("startup", "resume", "compact"):
            with self.subTest(source):
                self.assertEqual(self.part1(self.hooks, None, source), "")

    def test_f68_marker_off_switch_and_no_ledger_stays_empty(self):
        self.marker()
        r = self.run_in(self.hooks, "postcompact-inject.py", ("--ledger", "--part", "1"),
                        {"cwd": self.proj, "session_id": "N", "hook_event_name": "SessionStart", "source": "startup"},
                        extra={"HANDOFF_RECALL_RULES": "0"})
        self.assertEqual((r.returncode, r.stdout), (0, ""))


# ------------------------------------------------------------------ F70 amendments
class Reanchor(AnchorBase):
    def test_f70_parallel_runs_inject_once(self):
        tp = os.path.join(self.home, ".claude", "projects", "x", self.sid + ".jsonl")
        write_transcript(tp, [{"type": "user", "message": {"role": "user", "content": "Please keep going"}},
                              usage_entry(60000)])
        payload = {"session_id": self.sid, "transcript_path": tp, "cwd": self.proj, "hook_event_name": "PostToolUse",
                   "tool_name": "Bash", "tool_input": {"command": "ls"}, "tool_response": {"stdout": "x"}}
        outs = []

        def go():
            r = self.script("reanchor.py", (), payload)
            outs.append(r)

        ts = [threading.Thread(target=go) for _ in range(8)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(len(outs), 8)
        for r in outs:
            self.assertEqual((r.returncode, r.stderr), (0, ""))
        printed = [r for r in outs if r.stdout.strip()]
        self.assertEqual(len(printed), 1, [r.stdout[:40] for r in outs])
        self.assertEqual(len(self.health()), 1)

    def test_f70_block_has_no_subagent_preamble(self):
        text = json.loads(self.run_at(60000))["hookSpecificOutput"]["additionalContext"]
        self.assertNotIn(PREAMBLE, text)
        self.assertNotIn("These are the user's standing rules for the main session", text)
        self.assertIn("RULEAAA", text)

    def run_records(self, recs):
        tp = os.path.join(self.home, ".claude", "projects", "x", self.sid + ".jsonl")
        write_transcript(tp, [{"type": "user", "message": {"role": "user", "content": "Please keep going"}}] + recs)
        payload = {"session_id": self.sid, "transcript_path": tp, "cwd": self.proj, "hook_event_name": "PostToolUse",
                   "tool_name": "Bash", "tool_input": {"command": "ls"}, "tool_response": {"stdout": "x"}}
        r = self.script("reanchor.py", (), payload)
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout)
        return r.stdout

    def anchor(self):
        return json.load(open(os.path.join(self.hd, "reanchor-%s.json" % self.sid)))["anchor"]

    def test_f70_a_zero_usage_entry_is_skipped_and_does_not_reset_the_anchor(self):
        self.assertTrue(self.run_records([usage_entry(60000)]).strip())
        self.assertEqual(self.anchor(), 60000)
        self.assertEqual(self.run_records([usage_entry(80000), usage_entry(0)]).strip(), "")
        self.assertEqual(self.anchor(), 60000, "a zero entry must not reset the anchor")
        self.assertEqual(self.run_records([usage_entry(100000), usage_entry(0)]).strip(), "",
                         "100000 is only 40000 above the anchor 60000")
        self.assertTrue(self.run_records([usage_entry(110000), usage_entry(0)]).strip())

    def test_f70_a_transcript_with_only_zero_usage_prints_nothing(self):
        self.assertEqual(self.run_records([usage_entry(0)]).strip(), "")

    def test_f70_state_files_have_mode_0600(self):
        self.run_at(60000)
        st = os.path.join(self.hd, "reanchor-%s.json" % self.sid)
        lock = os.path.join(self.hd, "reanchor-%s.lock" % self.sid)
        self.assertEqual(mode(st), 0o600)
        self.assertTrue(os.path.exists(lock), os.listdir(self.hd))
        self.assertEqual(mode(lock), 0o600)

    def test_f70_a_run_that_prints_nothing_leaves_state_files_with_mode_0600(self):
        self.run_at(10000)
        for n in os.listdir(self.hd):
            if n.startswith("reanchor-"):
                self.assertEqual(mode(os.path.join(self.hd, n)), 0o600, n)


# ------------------------------------------------------------------ F71 amendments
class Guard(GuardBase):
    REPLY = "As we decided, the storage is postgres."

    def base(self, *middle, last=None):
        """A real user message, then `middle` entries, then maybe one more entry; the guard runs with a cue."""
        self.turn += 1
        recs = [user("An older question here", "u-old"), text_reply("An older answer"),
                user("a real question about storage", "u-%d" % self.turn), *middle]
        if last:
            recs.append(last)
        write = __import__("levers_common").write_transcript
        write(self.tp, recs)

    def evidence(self):
        return [tool_use("Bash", {"command": "python3 ~/.claude/hooks/recall.py search storage"}), tool_result()]

    def not_a_turn(self):
        return [("task-notification", user("<task-notification>done</task-notification>", "u-tn")),
                ("bash-input", user("<bash-input>ls</bash-input>", "u-bi")),
                ("bash-stdout", user("<bash-stdout>x</bash-stdout><bash-stderr></bash-stderr>", "u-bo")),
                ("local-command-stdout", user("<local-command-stdout>x</local-command-stdout>", "u-lc")),
                ("local-command-caveat", user("<local-command-caveat>x</local-command-caveat>", "u-lk")),
                ("compact-summary", dict(user("This session is being continued from a previous conversation", "u-cs"),
                                         isCompactSummary=True))]

    def test_f71_entries_that_are_not_real_user_prompts_do_not_end_the_evidence_window(self):
        for kind, entry in self.not_a_turn():
            with self.subTest(kind):
                self.base(*self.evidence(), entry)
                r = self.run_guard(self.REPLY)
                self.assert_quiet(r)
                self.assertEqual(self.rows(), [], "the recall call came after the last real user message")

    def test_f71_control_a_real_user_message_after_the_evidence_does_end_the_window(self):
        self.base(*self.evidence(), user("another real question", "u-real2"))
        self.assert_quiet(self.run_guard(self.REPLY))
        self.assertEqual(len(self.rows()), 1)

    def test_f71_no_lookback_an_injection_before_the_last_user_message_does_not_count(self):
        self.turn += 1
        write_transcript(self.tp, [user("older question", "u-old"),
                                   injection("Lossless Handoff auto-recall: earlier messages that match your words."),
                                   user("a real question about storage", "u-new")])
        self.assert_quiet(self.run_guard(self.REPLY))
        self.assertEqual(len(self.rows()), 1)

    def test_f71_an_injection_after_the_last_user_message_still_counts(self):
        self.base(injection("Lossless Handoff auto-recall: earlier messages that match your words."))
        self.assert_quiet(self.run_guard(self.REPLY))
        self.assertEqual(self.rows(), [])

    def test_f71_a_task_notification_does_not_start_a_new_turn_for_the_block_marker(self):
        live = {"HANDOFF_CLAIM_GUARD": "block"}
        self.base()
        self.assertTrue(self.blocked(self.run_guard(self.REPLY, extra=live)))
        entry = self.not_a_turn()[0][1]
        write_transcript(self.tp, [user("An older question here", "u-old"), text_reply("An older answer"),
                                   user("a real question about storage", "u-%d" % self.turn), entry])
        self.assert_quiet(self.run_guard(self.REPLY, extra=live))

    def test_f71_log_has_mode_0600(self):
        self.base()
        self.run_guard(self.REPLY)
        self.assertEqual(mode(os.path.join(self.hd, "claim-guard.jsonl")), 0o600)

    def test_f71_live_state_file_has_mode_0600(self):
        self.base()
        self.run_guard(self.REPLY, extra={"HANDOFF_CLAIM_GUARD": "block"})
        for n in os.listdir(self.hd):
            if n.startswith("claim-guard"):
                self.assertEqual(mode(os.path.join(self.hd, n)), 0o600, n)


# ------------------------------------------------------------------ F69 amendments
class McpAmend(HookBase):
    def setUp(self):
        super().setUp()
        self.hooks = os.path.join(self.home, ".claude", "hooks")
        os.makedirs(self.hooks)
        copy_hook_scripts(self.hooks)
        self.clients = []
        self.seed([("user", "We decided to use the postgres database for the billing service BILLINGMARK"),
                   ("user", "Run the exporter with the -x flag and the zebra option")])

    def tearDown(self):
        for c in self.clients:
            c.close()

    def start(self, cwd, extra=None, init=True):
        c = Mcp([sys.executable, os.path.join(self.hooks, "recall-mcp.py")], self.env2(extra), cwd)
        self.clients.append(c)
        if init:
            c.init()
        return c

    @staticmethod
    def text(r):
        return r["result"]["content"][0]["text"]

    def test_f69_claude_project_dir_picks_the_project(self):
        other = os.path.join(self.tmp, "elsewhere")
        os.makedirs(other)
        c = self.start(other, {"CLAUDE_PROJECT_DIR": self.proj})
        self.assertIn("BILLINGMARK", self.text(c.tool("search_earlier_chat", {"query": "BILLINGMARK"})))
        c2 = self.start(other)
        self.assertEqual(self.text(c2.tool("search_earlier_chat", {"query": "BILLINGMARK"})), "no matches")

    def test_f69_the_working_directory_is_used_when_the_variable_is_unset(self):
        c = self.start(self.proj)
        self.assertIn("BILLINGMARK", self.text(c.tool("search_earlier_chat", {"query": "BILLINGMARK"})))

    def test_f69_claude_project_dir_wins_over_the_working_directory(self):
        other = os.path.join(self.tmp, "elsewhere")
        os.makedirs(other)
        c = self.start(self.proj, {"CLAUDE_PROJECT_DIR": other})
        self.assertEqual(self.text(c.tool("search_earlier_chat", {"query": "BILLINGMARK"})), "no matches")

    def test_f69_a_query_that_starts_with_a_dash_is_searched_as_text(self):
        c = self.start(self.proj)
        r = c.tool("search_earlier_chat", {"query": "-x"})
        self.assertFalse(r["result"].get("isError", False), r)
        self.assertIn("-x flag", self.text(r))

    def test_f69_the_dash_query_does_not_act_as_an_option(self):
        c = self.start(self.proj)
        for q in ("--help", "-n", "--limit"):
            with self.subTest(q):
                r = c.tool("search_earlier_chat", {"query": q})
                self.assertFalse(r["result"].get("isError", False), r)
                self.assertEqual(self.text(r), "no matches")
        self.assertEqual(c.call("ping").get("result"), {})

    def test_f69_unknown_protocol_version_falls_back_to_2025_11_25(self):
        for v in ("1999-01-01", "", "x"):
            with self.subTest(v):
                c = self.start(self.proj, init=False)
                r = c.call("initialize", {"protocolVersion": v, "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}})
                self.assertEqual(r["result"]["protocolVersion"], "2025-11-25")

    def test_f69_state_log_has_mode_0600(self):
        c = self.start(self.proj)
        c.tool("search_earlier_chat", {"query": "BILLINGMARK"})
        self.assertEqual(mode(os.path.join(self.hd, "recall-mcp.jsonl")), 0o600)


class McpRerun(unittest.TestCase):
    """A re-install, when the server is already registered, prints `recall-mcp: already installed, kept` and runs no
    second `claude mcp add`. The fake `claude` records its calls and exits 0 for every call."""

    def test_f69_rerun_does_not_add_again_and_prints_the_kept_line(self):
        import shutil, tempfile
        tmp = os.path.realpath(tempfile.mkdtemp(prefix="lev-r-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        home = os.path.join(tmp, "home")
        os.makedirs(home)
        bindir = os.path.join(tmp, "fakebin")
        os.makedirs(bindir)
        log = os.path.join(tmp, "claude.log")
        with open(os.path.join(bindir, "claude"), "w") as f:
            f.write("#!/bin/sh\nprintf '%%s\\n' \"claude $*\" >> %s\nexit 0\n" % log)
        os.chmod(os.path.join(bindir, "claude"), 0o755)
        path = bindir + ":/usr/bin:/bin"
        r1 = run_install(home, "--recall-mcp", path=path)
        self.assertEqual(r1.returncode, 0, r1.stdout + r1.stderr)
        calls = lambda: [l for l in open(log).read().split("\n") if l.startswith("claude mcp add")]
        self.assertEqual(len(calls()), 1, open(log).read())
        r2 = run_install(home, path=path)
        self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
        self.assertEqual(len([l for l in (r2.stdout + r2.stderr).split("\n") if l.startswith("recall-mcp: already installed, kept")]), 1,
                         r2.stdout + r2.stderr)
        self.assertEqual(len(calls()), 1, "a second `claude mcp add` ran:\n" + open(log).read())
        r3 = run_install(home, "--recall-mcp", path=path)
        self.assertEqual(r3.returncode, 0, r3.stdout + r3.stderr)
        self.assertEqual(len(calls()), 1, "a third install with the flag ran `claude mcp add` again")


if __name__ == "__main__":
    unittest.main()
