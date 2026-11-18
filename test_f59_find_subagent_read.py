"""F59 Find what a subagent read: ACs 268-273 of docs/spec.md. Code-blind: written from the spec only.
Fixture: the F44.8 fixture plus one subagent transcript for an in-scope session. The subagent has an assistant
tool_use Read of led-1.txt on line L (2) and the tool_result with the same id on a later line R (4). The result text
holds `ledger-key: AH8X-2548-MJ8D`. Keyword-only runs use a closed port. Installer and hook tests use a temp HOME."""
import json, os, re, shutil, tempfile, time, unittest

from helpers import HookCase, run_install
from test_f44_recall import S1, RecallBase

AID = "led9f3c2a1b7"
A8 = AID[:8]
S8 = S1[:8]
L, R = 2, 4
VALUE = "AH8X-2548-MJ8D"
TOOL_ID = "toolu_led1_f59"
UUIDS = iter("00000000-0000-4000-8000-%012d" % n for n in range(590000, 590100))
RESULT_PTR = re.compile(r" -> result (\S+)$")


def uuid():
    return next(UUIDS)


class Fixture:
    def build_fixture(self):
        super().build_fixture()
        Rec = self.rec
        kw = dict(sid=S1, cwd=self.proj, day=8, isSidechain=True, agentId=AID)
        self.sub_file = os.path.join(self.tdir(self.proj), S1, "subagents", "agent-%s.jsonl" % AID)
        self.write_session(self.sub_file, [
            Rec("user", "SUBPROMPTF59 please read the ledger file", minute=1, uuid=uuid(), **kw),
            Rec("assistant", [{"type": "tool_use", "id": TOOL_ID, "name": "Read",
                               "input": {"file_path": "/work/led-1.txt"}}], minute=2, uuid=uuid(), **kw),
            Rec("assistant", [{"type": "text", "text": "Now I wait for the file"}], minute=3, uuid=uuid(), **kw),
            Rec("user", [{"type": "tool_result", "tool_use_id": TOOL_ID, "content": "ledger-key: %s" % VALUE}],
                minute=4, uuid=uuid(), **kw),
        ])

    def agent_lines(self, out, line=None):
        pre = "%s/%s:%s " % (S8, A8, line) if line else "%s/%s:" % (S8, A8)
        return [l for l in out.split("\n") if l.startswith(pre)]


class Search(Fixture, RecallBase):
    # ---- AC 268
    def test_ac268_space_pattern_finds_result_line_with_dash_text(self):
        out = self.ok("search", "ledger key")
        lines = [l for l in self.agent_lines(out, R) if VALUE in l]
        self.assertEqual(len(lines), 1, out)

    def test_ac268_other_separators_also_match(self):
        for pat in ("ledger_key", "ledger-key", "ledger  key", "ledger - key"):
            with self.subTest(pat=pat):
                out = self.ok("search", pat)
                self.assertEqual(len([l for l in self.agent_lines(out, R) if VALUE in l]), 1, out)

    # ---- AC 269
    def test_ac269_fixed_keeps_the_match_exact(self):
        out = self.ok("search", "ledger key", "--fixed")
        self.assertNotIn(VALUE, out)
        self.assertEqual(self.agent_lines(out, R), [], out)
        # control: the exact text still matches with --fixed
        out2 = self.ok("search", "ledger-key", "--fixed")
        self.assertEqual(len([l for l in self.agent_lines(out2, R) if VALUE in l]), 1, out2)

    # ---- AC 270
    def test_ac270_tool_call_hit_ends_with_result_pointer(self):
        out = self.ok("search", "led-1.txt")
        lines = self.agent_lines(out, L)
        self.assertEqual(len(lines), 1, out)
        self.assertTrue(lines[0].endswith(" -> result %s/%s:%d" % (S8, A8, R)), lines[0])
        self.assertEqual(len(RESULT_PTR.findall(lines[0])), 1, lines[0])

    def test_ac270_hit_without_matching_result_is_unchanged(self):
        with open(self.sub_file, "a") as f:
            f.write(json.dumps(self.rec("assistant", [{"type": "tool_use", "id": "toolu_orphan_f59", "name": "Read",
                                                       "input": {"file_path": "/work/orphan-9.txt"}}],
                                        sid=S1, cwd=self.proj, day=8, minute=5, isSidechain=True, agentId=AID,
                                        uuid=uuid())) + "\n")
        out = self.ok("search", "orphan-9.txt")
        lines = self.agent_lines(out, 5)
        self.assertEqual(len(lines), 1, out)
        self.assertNotIn("-> result", lines[0])

    def test_ac270_text_hit_has_no_pointer(self):
        out = self.ok("search", "SUBPROMPTF59")
        lines = self.agent_lines(out, 1)
        self.assertEqual(len(lines), 1, out)
        self.assertNotIn("-> result", lines[0])

    # ---- AC 271
    def test_ac271_open_pointer_id_prints_the_result(self):
        line = self.agent_lines(self.ok("search", "led-1.txt"), L)[0]
        rid = RESULT_PTR.search(line).group(1)
        self.assertEqual(rid, "%s/%s:%d" % (S8, A8, R))
        out = self.ok("open", rid)
        self.assertIn(VALUE, out)

    # ---- AC 272
    def test_ac272_regex_dot_keeps_regex_meaning(self):
        out = self.ok("search", "ledger.key")
        self.assertEqual(len([l for l in self.agent_lines(out, R) if VALUE in l]), 1, out)

    def test_ac272_alternation_keeps_regex_meaning(self):
        out = self.ok("search", "zzz|ledger-key")
        self.assertEqual(len([l for l in self.agent_lines(out, R) if VALUE in l]), 1, out)

    def test_ac272_alternation_with_space_is_not_loosened(self):
        # `|` is outside the loose-separator character set, so the pattern keeps its exact meaning.
        out = self.ok("search", "zzz|ledger key")
        self.assertEqual(self.agent_lines(out, R), [], out)


class RecallText(HookCase):
    # ---- AC 273
    def test_ac273_installed_recall_md_holds_result_pointer_text(self):
        base = os.path.realpath(tempfile.mkdtemp(prefix="f59-"))
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        home = os.path.join(base, "home")
        os.makedirs(home)
        r = run_install(home, "--no-nightly")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        log = os.path.join(home, ".local", "state", "claude-handoffs", "recall", "index-all.log")
        end = time.time() + 20
        while time.time() < end and not (os.path.exists(log) and os.path.getsize(log) > 0):
            time.sleep(0.2)
        time.sleep(0.3)
        with open(os.path.join(home, ".claude", "agents", "recall.md")) as f:
            self.assertIn("-> result", f.read())

    def test_ac273_compact_recall_line_holds_result_pointer_text(self):
        proj = os.path.join(os.path.realpath(self.tmp), "r", "proj")
        os.makedirs(proj)
        from test_content import git
        git(proj, "init", "-q")
        self.write_transcript([{"type": "user", "message": {"content": "An early message long enough to count"}}])
        r = self.run_pre({"session_id": "S", "cwd": proj, "trigger": "auto", "transcript_path": self.tpath})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        p = {"session_id": "S", "cwd": proj, "hook_event_name": "SessionStart", "source": "compact",
             "transcript_path": self.tpath}
        r = self.run_post(p, args=("--part", "1"))
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout)
        ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
        lines = [l for l in ctx.split("\n") if l.startswith("- recall:")]
        self.assertEqual(len(lines), 1, ctx[:600])
        self.assertIn("-> result", lines[0])


if __name__ == "__main__":
    unittest.main()
