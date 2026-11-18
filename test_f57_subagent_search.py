"""F57 Subagent transcripts in search: ACs 255-260 of docs/spec.md. Code-blind: written from the spec only.
Fixture: the F44.8 fixture plus one subagent transcript for an in-scope session (unique word Quokkasub in an
assistant message) and one subagent transcript of the out-of-scope session /r/proj-private.
Subagent files: <project dir>/<sid>/subagents/agent-<id>.jsonl, records with isSidechain, agentId, sessionId, an
in-scope cwd and unique uuids (never a uuid of a main transcript).
Meaning tests use the fake embedding server of the F44.9 tests. Keyword-only runs use a closed port."""
import json, os, re, shutil, subprocess, sys, unittest

import test_f44_recall as f44
from test_f44_recall import S1, PRIV, RECALL, COUNT_RE, RecallBase

AID = "q7f3c9d2e1b4"          # agent id of the in-scope subagent
A8 = AID[:8]                  # agent8
PAID = "pr1v4t3x9z00"         # agent id of the out-of-scope subagent
PA8 = PAID[:8]
S8 = S1[:8]
P8 = PRIV[:8]
WORD = "Quokkasub"
ID_RE = re.compile(r"^%s/%s:(\d+) " % (S8, A8))
UUIDS = iter("00000000-0000-4000-8000-%012d" % n for n in range(570000, 570100))


def uuid():
    return next(UUIDS)


class SubFixture:
    """Mixin: adds the F57 subagent transcripts after the F44.8 fixture."""

    def build_fixture(self):
        super().build_fixture()
        R = self.rec
        self.sub_file = os.path.join(self.tdir(self.proj), S1, "subagents", "agent-%s.jsonl" % AID)
        self.write_session(self.sub_file, [
            R("user", "SUBPROMPTQ please investigate the nightly cache job", sid=S1, cwd=self.proj, day=7, minute=1,
              isSidechain=True, agentId=AID, uuid=uuid()),
            R("assistant", [{"type": "text", "text": "%s found that the nightly cache job fails at warm up" % WORD}],
              sid=S1, cwd=self.proj, day=7, minute=2, isSidechain=True, agentId=AID, uuid=uuid()),
        ])
        self.priv_sub_file = os.path.join(self.tdir(self.priv), PRIV, "subagents", "agent-%s.jsonl" % PAID)
        self.write_session(self.priv_sub_file, [
            R("assistant", [{"type": "text", "text": "%s PRIVSUBQ private subagent result" % WORD}],
              sid=PRIV, cwd=self.priv, day=7, minute=3, isSidechain=True, agentId=PAID, uuid=uuid()),
        ])

    def sub_lines(self, out, marker=WORD):
        return [l for l in out.split("\n") if l.startswith("%s/%s:" % (S8, A8)) and marker in l]


class Search(SubFixture, RecallBase):
    # ---- AC 255
    def test_ac255_default_search_finds_subagent_hit_with_id_and_tag(self):
        out = self.ok("search", WORD)
        lines = self.sub_lines(out)
        self.assertEqual(len(lines), 1, out)
        line = lines[0]
        m = ID_RE.match(line)
        self.assertTrue(m, line)
        self.assertEqual(m.group(1), "2", line)  # the message is on line 2 of the subagent file
        self.assertIn(" [agent %s]" % A8, line)
        self.assertRegex(line, r"^\S+ \d{4}-\d\d-\d\d \d\d:\d\d assistant")
        self.assertEqual(self.count_line(out).group(1), "1", out)

    def test_ac255_agent_tag_comes_after_the_source_tag(self):
        line = self.sub_lines(self.ok("search", WORD))[0]
        before_snip = line.split(": ", 1)[0]
        self.assertTrue(before_snip.endswith(" [agent %s]" % A8), line)
        for tag in ("[word]", "[meaning]", "[both]"):
            if tag in before_snip:
                self.assertLess(before_snip.index(tag), before_snip.index("[agent"), line)

    def test_ac255_older_fixture_subagent_hit_has_the_same_id_form(self):
        out = self.ok("search", "SUBAGENTONE")
        lines = [l for l in out.split("\n") if "SUBAGENTONE" in l]
        self.assertEqual(len(lines), 1, out)
        self.assertTrue(lines[0].startswith("%s/ab:1 " % S8), lines[0])  # agent id "ab" has fewer than 8 characters
        self.assertIn(" [agent ab]", lines[0])

    def test_ac255_main_transcript_ids_are_unchanged(self):
        out = self.ok("search", "TYPED1")
        hits = self.hits(out)
        self.assertEqual(len(hits), 1, out)
        self.assertEqual((hits[0].group("sid"), hits[0].group("line")), (S8, "1"))
        self.assertNotIn("[agent", out)

    def test_ac255_role_user_also_reaches_subagent_prompts(self):
        out = self.ok("search", "SUBPROMPTQ", "--role", "user")
        self.assertEqual(len([l for l in out.split("\n") if l.startswith("%s/%s:1 " % (S8, A8))]), 1, out)

    # ---- AC 256
    def test_ac256_no_subagents_finds_zero_hits(self):
        out = self.ok("search", WORD, "--no-subagents")
        self.assertEqual(self.sub_lines(out), [])
        self.assertNotIn(WORD, "\n".join(l for l in out.split("\n") if not l.startswith("mode:")))
        self.assertEqual(self.count_line(out).group(1), "0", out)

    def test_ac256_subagents_flag_gives_the_same_output_as_no_flag(self):
        plain = self.rc("search", WORD)
        flag = self.rc("search", WORD, "--subagents")
        self.assertEqual((plain.returncode, plain.stderr), (0, ""))
        self.assertEqual((flag.returncode, flag.stderr), (0, ""))
        self.assertEqual(flag.stdout, plain.stdout)
        self.assertEqual(len(self.sub_lines(flag.stdout)), 1, flag.stdout)

    def test_ac256_no_subagents_restores_the_old_scope_for_all_hits(self):
        out = self.ok("search", "Pomodoro", "--no-subagents")
        self.assertNotIn("SUBAGENTONE", out)

    # ---- AC 257
    def test_ac257_open_subagent_id_prints_message_with_heading(self):
        hit_id = "%s/%s:2" % (S8, A8)
        out = self.ok("open", hit_id)
        heads = [l for l in out.split("\n") if l.startswith("--- ")]
        self.assertTrue(any(h.startswith("--- %s " % hit_id) for h in heads), heads)
        self.assertIn("%s found that the nightly cache job fails at warm up" % WORD, out)

    def test_ac257_open_uses_the_id_printed_by_search(self):
        line = self.sub_lines(self.ok("search", WORD))[0]
        hit_id = line.split(" ", 1)[0]
        out = self.ok("open", hit_id)
        self.assertIn("--- %s " % hit_id, out)
        self.assertIn(WORD, out)

    def test_ac257_open_unknown_subagent_id_exits_2(self):
        r = self.rc("open", "%s/zzzzzzzz:2" % S8)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)

    # ---- AC 258
    def test_ac258_user_reads_main_transcripts_only(self):
        # Precondition: search sees the subagent text, so the absence in `user` is a real scope rule.
        self.assertEqual(len(self.sub_lines(self.ok("search", WORD))), 1)
        for args in (("--last", "50"), ("--last", "50", "--session", S8), ("--last", "50", "--session", "all")):
            with self.subTest(args=args):
                out = self.ok("user", *args)
                for bad in (WORD, "SUBPROMPTQ", "SUBAGENTONE"):
                    self.assertNotIn(bad, out)
                self.assertIn("TYPED1", out)

    # ---- AC 260
    def test_ac260_out_of_scope_subagent_never_appears(self):
        for args in (("search", WORD), ("search", WORD, "--subagents"), ("search", "PRIVSUBQ"),
                     ("search", "PRIVSUBQ", "--no-subagents")):
            with self.subTest(args=args):
                out = self.ok(*args)
                self.assertNotIn("PRIVSUBQ", out)
                self.assertNotIn("%s/" % P8, out)
        # the in-scope subagent hit is still there (control)
        self.assertEqual(len(self.sub_lines(self.ok("search", WORD))), 1)

    def test_ac260_private_root_sees_its_own_subagent_only(self):
        out = self.ok("search", WORD, cwd=self.priv)
        lines = [l for l in out.split("\n") if l.startswith("%s/%s:" % (P8, PA8))]
        self.assertEqual(len(lines), 1, out)
        self.assertIn(" [agent %s]" % PA8, lines[0])
        self.assertNotIn("%s/%s:" % (S8, A8), out)

    def test_ac260_open_does_not_read_out_of_scope_subagent(self):
        r = self.rc("open", "%s/%s:1" % (P8, PA8))
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertNotIn("PRIVSUBQ", r.stdout)


class Meaning(SubFixture, RecallBase):
    # same helpers as f44.Meaning (not subclassed: its tests would run again with this fixture)
    def setUp(self):
        super().setUp()
        self.fe = f44.FakeEmbed()
        self.addCleanup(self.fe.stop)

    def index(self, *extra, embed=None, env=None):
        return self.rc("index", *extra, embed=embed or self.fe.url, extra=env)

    def sqlite_path(self):
        return os.path.join(self.hd, "recall", f44.key_for(self.proj) + ".sqlite")

    def rows(self):
        import sqlite3
        con = sqlite3.connect(self.sqlite_path())
        try:
            for (name,) in con.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'").fetchall():
                cols = [r[1].lower() for r in con.execute("pragma table_info('%s')" % name)]
                if "sid" in cols and "line" in cols:
                    return con.execute("select sid, line from %s" % name).fetchall()
        finally:
            con.close()
        self.fail("no table with sid and line columns")

    def search(self, *args, **kw):
        return self.rc("search", *args, embed=self.fe.url, **kw)

    # ---- AC 259
    def test_ac259_meaning_search_returns_subagent_chunk_and_second_index_adds_nothing(self):
        r = self.index()
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout)
        self.assertTrue(any(WORD in t for t in self.fe.all_texts()), "subagent text was not embedded")
        n_rows, n_req = len(self.rows()), len(self.fe.requests)
        out = self.search(WORD, "--meaning")
        self.assertEqual((out.returncode, out.stderr), (0, ""), out.stdout)
        lines = self.sub_lines(out.stdout)
        self.assertEqual(len(lines), 1, out.stdout)
        self.assertTrue(ID_RE.match(lines[0]), lines[0])
        self.assertIn(" [meaning]", lines[0])
        self.assertIn(" [agent %s]" % A8, lines[0])
        # a second index adds 0 rows (and sends nothing new)
        n_req = len(self.fe.requests)
        r2 = self.index()
        self.assertEqual((r2.returncode, r2.stderr), (0, ""), r2.stdout)
        self.assertEqual(len(self.rows()), n_rows, "second index run adds 0 rows")
        self.assertEqual(len(self.fe.requests), n_req, "second index run embeds nothing")

    def test_ac259_hybrid_hit_is_tagged_both_with_agent_id(self):
        self.assertEqual(self.index().returncode, 0)
        out = self.search(WORD)
        self.assertEqual((out.returncode, out.stderr), (0, ""), out.stdout)
        lines = self.sub_lines(out.stdout)
        self.assertEqual(len(lines), 1, out.stdout)
        self.assertIn(" [both]", lines[0])
        self.assertIn(" [agent %s]" % A8, lines[0])

    def test_ac259_index_is_incremental_for_subagent_transcripts(self):
        self.assertEqual(self.index().returncode, 0)
        n = len(self.rows())
        with open(self.sub_file, "a") as f:
            f.write(json.dumps(self.rec("assistant", [{"type": "text", "text": "Zebrasub a second subagent message"}],
                                        sid=S1, cwd=self.proj, day=7, minute=9, isSidechain=True, agentId=AID,
                                        uuid=uuid())) + "\n")
        self.assertEqual(self.index().returncode, 0)
        self.assertEqual(len(self.rows()), n + 1)
        out = self.search("Zebrasub", "--meaning")
        self.assertEqual(len(self.sub_lines(out.stdout, "Zebrasub")), 1, out.stdout)

    def test_ac259_subagent_text_is_redacted_before_embedding(self):
        with open(self.sub_file, "a") as f:
            f.write(json.dumps(self.rec("assistant", [{"type": "text", "text": "subagent saw password=hunter2x here"}],
                                        sid=S1, cwd=self.proj, day=7, minute=8, isSidechain=True, agentId=AID,
                                        uuid=uuid())) + "\n")
        self.assertEqual(self.index().returncode, 0)
        joined = "\n".join(self.fe.all_texts())
        self.assertNotIn("hunter2x", joined)
        self.assertIn("[redacted]", joined)

    # ---- AC 260 (meaning side)
    def test_ac260_out_of_scope_subagent_is_never_indexed_or_found_by_meaning(self):
        self.assertEqual(self.index().returncode, 0)
        self.assertTrue(any(WORD in t for t in self.fe.all_texts()))
        self.assertFalse(any("PRIVSUBQ" in t for t in self.fe.all_texts()))
        out = self.search("PRIVSUBQ private subagent result", "--meaning")
        self.assertNotIn("PRIVSUBQ", out.stdout)
        self.assertNotIn("%s/" % P8, out.stdout)


class RecallAgentText(unittest.TestCase):
    # ---- F57.d (no numbered AC): the recall agent file says that subagent work is in search by default
    def test_f57d_recall_agent_file_mentions_subagent_hits(self):
        from helpers import run_install
        import tempfile
        base = os.path.realpath(tempfile.mkdtemp(prefix="f57-"))
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        home = os.path.join(base, "home")
        os.makedirs(home)
        r = run_install(home, "--no-nightly")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        import time
        log = os.path.join(home, ".local", "state", "claude-handoffs", "recall", "index-all.log")
        end = time.time() + 20
        while time.time() < end and not (os.path.exists(log) and os.path.getsize(log) > 0):
            time.sleep(0.2)
        time.sleep(0.3)
        with open(os.path.join(home, ".claude", "agents", "recall.md")) as f:
            t = f.read()
        self.assertIn("[agent", t)
        self.assertIn("subagent", t.lower())


if __name__ == "__main__":
    unittest.main()
