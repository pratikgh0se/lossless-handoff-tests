"""F55 Recall subagent: ACs 248-251 of docs/spec.md. Code-blind: written from the spec only.
install.sh writes ~/.claude/agents/recall.md (with a marker line), uninstall.sh removes it only with the marker,
and the injected recall line gets one more sentence when the file exists with the marker.
Every installer run uses a temp HOME (helpers refuse the real HOME) with launchctl and the network off."""
import json, os, re, shutil, subprocess, sys, tempfile, time, unittest

from helpers import HOOKS_DIR, PRE, POST, PLAIN, run_install, run_uninstall
from test_f45_no_silent_miss import F45Base, iso
from test_f44_recall import key_for
from test_content import git

MARKER = "<!-- lossless-handoff:recall-agent -->"
NOT_OURS = "~/.claude/agents/recall.md exists and is not ours; left unchanged."
SENTENCE = ("For wide lookups (many hits, long messages, or a whole node), ask the recall subagent (Agent tool, "
            "subagent_type \"recall\") so the main context stays small; for one exact fact, search directly.")
FOREIGN = "---\nname: recall\ndescription: my own agent\n---\nThis is my own file. FOREIGN-MARK\n"
OLD_OURS = MARKER + "\nOLD-CONTENT-MARK from an older release\n"
BODY = "HANDOFF-BODY-F55 the agent note for this compaction\n"


class InstallBase(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="f55-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self.agent = os.path.join(self.home, ".claude", "agents", "recall.md")
        self.state = os.path.join(self.home, ".local", "state", "claude-handoffs")

    def put_agent(self, text):
        os.makedirs(os.path.dirname(self.agent), exist_ok=True)
        with open(self.agent, "w") as f:
            f.write(text)

    def wait_first_index(self):
        """install.sh starts a first recall index in the background; wait for its log so a later step is stable."""
        log = os.path.join(self.state, "recall", "index-all.log")
        end = time.time() + 20
        while time.time() < end:
            if os.path.exists(log) and os.path.getsize(log) > 0:
                break
            time.sleep(0.2)
        time.sleep(0.3)

    def install(self, *args):
        r = run_install(self.home, *args)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.wait_first_index()
        return r

    def text(self):
        with open(self.agent) as f:
            return f.read()


class Agent(InstallBase):
    def test_ac248_fresh_install_writes_agent_file(self):
        self.install("--no-nightly")
        self.assertTrue(os.path.isfile(self.agent), "no ~/.claude/agents/recall.md")
        t = self.text()
        lines = t.split("\n")
        self.assertIn(MARKER, lines)
        self.assertIn("name: recall", lines)
        self.assertIn("model: haiku", lines)
        self.assertIn("tools: Bash, Read", lines)
        self.assertIn("recall.py", t)

    def test_ac248_frontmatter_and_body_rules(self):
        self.install("--no-nightly")
        t = self.text()
        self.assertTrue(t.startswith("---\n"), t[:40])
        fm = t.split("\n---", 1)[0]
        desc = [l for l in fm.split("\n") if l.startswith("description:")]
        self.assertEqual(len(desc), 1, fm)
        d = desc[0].lower()
        self.assertIn("word for word", d)
        self.assertIn("message id", d)
        self.assertIn("main context", d)
        body = t.split("\n---", 1)[1]
        self.assertIn("python3 ~/.claude/hooks/recall.py", body)
        for sub in ("map", "search", "describe", "open"):
            self.assertRegex(body, r"\b%s\b" % sub)
        self.assertIn("15", body)
        self.assertIn("300", body)
        self.assertIn("not found", body)
        self.assertIn("<session8>:<line>", body)

    def test_ac249_foreign_file_left_unchanged(self):
        self.put_agent(FOREIGN)
        before = open(self.agent, "rb").read()
        r = self.install("--no-nightly")
        self.assertEqual(open(self.agent, "rb").read(), before)
        self.assertIn(NOT_OURS, r.stdout + r.stderr)

    def test_ac249_our_old_file_is_replaced(self):
        self.put_agent(OLD_OURS)
        self.install("--no-nightly")
        t = self.text()
        self.assertNotIn("OLD-CONTENT-MARK", t)
        self.assertIn(MARKER, t.split("\n"))
        self.assertIn("name: recall", t.split("\n"))

    def test_ac249_our_file_install_prints_no_not_ours_line(self):
        self.put_agent(OLD_OURS)
        r = self.install("--no-nightly")
        self.assertNotIn("not ours", r.stdout + r.stderr)

    def test_ac249_dry_run_writes_no_agent_file(self):
        r = run_install(self.home, "--no-nightly", "--dry-run")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(os.path.exists(self.agent))

    def test_ac249_dry_run_keeps_old_file(self):
        self.put_agent(OLD_OURS)
        r = run_install(self.home, "--no-nightly", "--dry-run")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.text(), OLD_OURS)


class Uninstall(InstallBase):
    def test_ac250_uninstall_removes_our_file(self):
        self.install("--no-nightly")
        self.assertTrue(os.path.isfile(self.agent))
        r = run_uninstall(self.home)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(os.path.exists(self.agent))

    def test_ac250_uninstall_keeps_foreign_file(self):
        self.put_agent(FOREIGN)
        self.install("--no-nightly")
        r = run_uninstall(self.home)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(os.path.isfile(self.agent))
        self.assertEqual(self.text(), FOREIGN)


# ---------------------------------------------------------------- AC 251 and F55.c: the recall line
class RecallLine(F45Base):
    LEDGER_ENV = None

    def setUp(self):
        super().setUp()
        self.rt = os.path.realpath(self.tmp)
        self.home = os.path.join(self.rt, "home")
        self.hd = os.path.join(self.home, ".local", "state", "claude-handoffs")
        self.proj = os.path.join(self.rt, "r", "proj")
        os.makedirs(self.proj)
        git(self.proj, "init", "-q")
        self.agent = os.path.join(self.home, ".claude", "agents", "recall.md")

    def put_agent(self, text):
        os.makedirs(os.path.dirname(self.agent), exist_ok=True)
        with open(self.agent, "w") as f:
            f.write(text)

    def compact_ctx(self, sid="S", part="1"):
        # a real PreCompact run writes the handoff (with its recall line)
        self.write_transcript([{"type": "user", "message": {"content": "An early message long enough to count"}}])
        r = self.run_pre({"session_id": sid, "cwd": self.proj, "trigger": "auto", "transcript_path": self.tpath})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        p = {"session_id": sid, "cwd": self.proj, "hook_event_name": "SessionStart", "source": "compact",
             "transcript_path": self.tpath}
        r = self.run_post(p, args=("--part", part))
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout)
        return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"] if r.stdout.strip() else ""

    def recall_line(self, text):
        ls = [l for l in text.split("\n") if l.startswith("- recall:")]
        self.assertEqual(len(ls), 1, text[:600])
        return ls[0]

    def test_ac251_sentence_with_agent_file(self):
        self.put_agent(OLD_OURS)
        out = self.compact_ctx()
        line = self.recall_line(out)
        self.assertTrue(line.endswith(SENTENCE), line[-300:])
        self.assertEqual(out.count(SENTENCE), 1)

    def test_ac251_no_sentence_without_agent_file(self):
        out = self.compact_ctx()
        self.assertNotIn(SENTENCE, out)
        self.assertNotIn("recall subagent", out)
        self.assertTrue(self.recall_line(out).endswith("recall shows history, not current rules."))

    def test_ac251_no_sentence_for_file_without_marker(self):
        self.put_agent(FOREIGN)
        out = self.compact_ctx()
        self.assertNotIn(SENTENCE, out)

    def test_f55c_sentence_in_precompact_handoff_file(self):
        self.put_agent(OLD_OURS)
        self.write_transcript([{"type": "user", "message": {"content": "Please remember the blue palette decision"}}])
        r = self.run_pre({"session_id": "S", "cwd": self.proj, "trigger": "auto", "transcript_path": self.tpath})
        self.assertEqual(r.returncode, 0, r.stderr)
        line = self.recall_line(self.latest("S"))
        self.assertTrue(line.endswith(SENTENCE), line[-300:])

    def test_f55c_precompact_handoff_without_agent_file_unchanged(self):
        self.write_transcript([{"type": "user", "message": {"content": "Please remember the blue palette decision"}}])
        r = self.run_pre({"session_id": "S", "cwd": self.proj, "trigger": "auto", "transcript_path": self.tpath})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn(SENTENCE, self.latest("S"))

    def _ledger(self):
        d = os.path.join(self.hd, "projects", key_for(self.proj))
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "decisions.md"), "w") as f:
            f.write("# Project decisions: %s\n- D1 [2026-03-01] Use the blue palette | why: brand rule\n" % self.proj)

    def test_f55c_sentence_in_ledger_part_one(self):
        self._ledger()
        self.put_agent(OLD_OURS)
        r = self.run_post({"session_id": "S", "cwd": self.proj, "hook_event_name": "SessionStart", "source": "compact"},
                          args=("--ledger", "--part", "1"))
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout)
        out = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("D1", out)
        self.assertTrue(self.recall_line(out).endswith(SENTENCE))

    def test_f55c_ledger_part_one_without_agent_file_unchanged(self):
        self._ledger()
        r = self.run_post({"session_id": "S", "cwd": self.proj, "hook_event_name": "SessionStart", "source": "compact"},
                          args=("--ledger", "--part", "1"))
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout)
        out = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertNotIn(SENTENCE, out)


if __name__ == "__main__":
    unittest.main()
