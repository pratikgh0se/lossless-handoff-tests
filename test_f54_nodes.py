"""F54 Summary nodes: ACs 236-247 of docs/spec.md. Code-blind: written from the spec only.
Leaf nodes come from `compact_boundary` records in Claude Code transcripts. The fixtures are real-looking JSONL
transcripts (user and assistant records, boundary records, and the isCompactSummary record after each boundary).
Temp HOME. Embedding server is a closed port, so every run is keyword only."""
import hashlib, json, os, re, subprocess, sys, time, unittest

from helpers import HOOKS_DIR, PRE, POST, PLAIN
from test_f44_recall import slug, key_for, closed_port_url
from test_content import git
from test_f45_no_silent_miss import F45Base, iso

RECALL = os.path.join(HOOKS_DIR, "recall.py")
SID = "f54aaaaa-0000-4000-8000-000000000001"
AID = "ab12cd34"
BODY = "HANDOFF-BODY-F54 the agent note for this compaction\n"
TOKEN = "NODETOKEN"
MAP_RE = re.compile(r"^(n[0-9a-f]{10}) (\d{4}-\d\d-\d\d \d\d:\d\d) ([0-9A-Za-z_-]{8})(?:/([0-9A-Za-z_-]{8}))? #(\d+) "
                    r"lines (\d+)-(\d+) (\S+) tokens: (.*)$")


def node_id(sid, uuid):
    return "n" + hashlib.sha1(("%s:%s" % (sid, uuid)).encode()).hexdigest()[:10]


def stamp(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t))


def work_text(k):
    return "CURRENTWORK-%d wire the exporter and run the unit tests" % k


def summary_text(k):
    return ("This session is being continued from a previous conversation that ran out of context. The summary below "
            "covers the earlier portion of the conversation.\n\nSummary:\n1. Primary Request and Intent:\n"
            "   The user asked for work item number %d. SUMTOKEN-%d. %s\n\n2. Key Technical Concepts:\n   - exporter, "
            "tests, parser\n\n8. Current Work:\n   %s\n\n9. Optional Next Step:\n   NEXTSTEP-%d finish the report. "
            "END-SUMTOKEN-%d" % (k, k, "Some long background text about the request. " * 8, work_text(k), k, k))


class Fx:
    """A transcript builder that knows the 1-based line of every record it writes."""

    def __init__(self, path, proj, sid=SID, agent=None, base=None):
        self.path, self.proj, self.sid, self.agent = path, proj, sid, agent
        self.base = base if base is not None else time.time() - 6 * 3600
        self.recs, self.info, self.written = [], [], 0
        self.last_boundary_line = 0

    def _add(self, kind, content, **kw):
        n = len(self.recs) + 1
        d = {"type": kind, "sessionId": self.sid, "cwd": self.proj, "timestamp": stamp(self.base + n * 60),
             "uuid": "11111111-2222-4333-8444-%012d" % n, "message": {"role": kind, "content": content}}
        if self.agent:
            d.update(isSidechain=True, agentId=self.agent)
        d.update(kw)
        self.recs.append(d)
        return n

    def user(self, text):
        return self._add("user", text)

    def asst(self, text):
        return self._add("assistant", [{"type": "text", "text": text}])

    def segment(self, token=False):
        self.user("Please continue with the exporter task, step %d" % len(self.recs))
        self.asst("Working on the exporter now, step %d" % len(self.recs))
        self.user(("Please check the %s value again" % TOKEN) if token else "Now run the unit tests for the parser")
        self.asst("The tests ran and the output looks fine")

    def boundary(self, pre=150000):
        k = len(self.info) + 1
        n = len(self.recs) + 1
        uuid = "b0b0b0b0-0000-4000-8000-%012d" % k
        ts = stamp(self.base + n * 60)
        self.recs.append({"type": "system", "subtype": "compact_boundary", "content": "Conversation compacted",
                          "uuid": uuid, "timestamp": ts, "sessionId": self.sid, "cwd": self.proj,
                          "compactMetadata": {"trigger": "auto", "preTokens": pre + k}})
        self._add("user", summary_text(k), isCompactSummary=True)
        self.info.append({"seq": k, "uuid": uuid, "line": n, "ts": ts, "pre": pre + k,
                          "first": self.last_boundary_line + 1, "last": n - 1, "id": node_id(self.sid, uuid)})
        self.last_boundary_line = n
        return self.info[-1]

    def live(self):
        self.user("After the compaction I still say %s here" % TOKEN)
        self.asst("Understood, continuing with the exporter")

    def write(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as f:
            for r in self.recs:
                f.write(json.dumps(r) + "\n")
        self.written = len(self.recs)

    def append(self):
        with open(self.path, "a") as f:
            for r in self.recs[self.written:]:
                f.write(json.dumps(r) + "\n")
        self.written = len(self.recs)

    @classmethod
    def standard(cls, path, proj, **kw):
        fx = cls(path, proj, **kw)
        fx.segment()
        fx.boundary()
        fx.segment(token=True)
        fx.boundary()
        fx.segment(token=True)
        fx.boundary()
        fx.live()
        fx.write()
        return fx


class NodesBase(F45Base):
    LEDGER_ENV = None

    def setUp(self):
        super().setUp()
        self.rt = os.path.realpath(self.tmp)
        self.home = os.path.join(self.rt, "home")
        self.hd = os.path.join(self.home, ".local", "state", "claude-handoffs")
        self.proj = os.path.join(self.rt, "r", "proj")
        os.makedirs(self.proj)
        git(self.proj, "init", "-q")
        self.down = closed_port_url()
        self.pdir = os.path.join(self.home, ".claude", "projects", slug(self.proj))
        os.makedirs(self.pdir, exist_ok=True)
        self.tpath = os.path.join(self.pdir, SID + ".jsonl")

    # ---- fixtures
    def standard(self):
        self.fx = Fx.standard(self.tpath, self.proj)
        return self.fx

    def fresh_handoff(self, key=SID):
        self.put_latest(BODY, sid=key)
        self.put_sidecar(sid=key, status="ok", age_s=30)
        self.add_health_row(SID, ts=iso(-30))

    def payload_compact(self, transcript=None, agent=None, source="compact"):
        p = {"session_id": SID, "cwd": self.proj, "hook_event_name": "SessionStart", "source": source,
             "transcript_path": transcript or self.tpath}
        if agent:
            p["agent_id"] = agent
            p["agent_type"] = "general-purpose"
            p["agent_transcript_path"] = os.path.join(self.pdir, SID, "subagents", "agent-%s.jsonl" % agent)
        return p

    def part1(self, payload=None, args=("--part", "1")):
        r = self.run_post(payload or self.payload_compact(), args=args)
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout)
        if r.stdout.strip() == "":
            return ""
        return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]

    def inject(self):
        """A real PreCompact run writes the handoff (with its recall line); then SessionStart compact part 1."""
        r = self.run_pre({"session_id": SID, "cwd": self.proj, "trigger": "auto", "transcript_path": self.tpath})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return self.part1()

    # ---- nodes file
    def nodes_path(self):
        found = []
        pr = os.path.join(self.hd, "projects")
        if os.path.isdir(pr):
            for k in os.listdir(pr):
                p = os.path.join(pr, k, "nodes.jsonl")
                if os.path.isfile(p):
                    found.append(p)
        self.assertEqual(len(found), 1, "expected one nodes.jsonl under %s: %s" % (pr, found))
        return found[0]

    def raw_lines(self):
        return [l for l in open(self.nodes_path()).read().split("\n") if l != ""]

    def nodes(self):
        out = []
        for l in self.raw_lines():
            try:
                out.append(json.loads(l))
            except ValueError:
                pass
        return out

    # ---- recall and prove
    def rc(self, *args, extra=None, timeout=90):
        env = {"HOME": self.home, "PATH": self.bin, "LANG": "C.UTF-8", "TZ": "UTC", "RECALL_EMBED_URL": self.down}
        env.update(extra or {})
        return subprocess.run([sys.executable, RECALL, *args, "--cwd", self.proj], capture_output=True, text=True,
                              env=env, timeout=timeout, cwd=self.tmp)

    def ok(self, *args, **kw):
        r = self.rc(*args, **kw)
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout)
        return r.stdout

    def prove(self):
        r = subprocess.run([sys.executable, PRE, "--prove", "--days", "1"], stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, env=self.env(None), timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout


# ---------------------------------------------------------------- ACs 236-239 store and sync
class Store(NodesBase):
    def test_ac236_three_boundaries_three_leaves(self):
        fx = self.standard()
        self.inject()
        ns = self.nodes()
        self.assertEqual(len(ns), 3, ns)
        by_seq = {n["seq"]: n for n in ns}
        self.assertEqual(sorted(by_seq), [1, 2, 3])
        for info in fx.info:
            n = by_seq[info["seq"]]
            self.assertEqual(n["id"], info["id"])
            self.assertEqual(n["kind"], "leaf")
            self.assertEqual((n["first_line"], n["last_line"]), (info["first"], info["last"]), n)
            self.assertEqual(n["boundary_uuid"], info["uuid"])
            self.assertEqual(n["time"], info["ts"])
            self.assertEqual(n["trigger"], "auto")
            self.assertEqual(n["pre_tokens"], info["pre"])
            self.assertEqual(n["session"], SID)
            self.assertIsNone(n["agent"])
            self.assertEqual(os.path.realpath(n["transcript"]), os.path.realpath(self.tpath))
            self.assertIn("handoff", n)

    def test_ac236_prev_links_and_unique_ids(self):
        fx = self.standard()
        self.inject()
        by_seq = {n["seq"]: n for n in self.nodes()}
        self.assertIsNone(by_seq[1]["prev"])
        self.assertEqual(by_seq[2]["prev"], by_seq[1]["id"])
        self.assertEqual(by_seq[3]["prev"], by_seq[2]["id"])
        ids = [n["id"] for n in self.nodes()]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids, [i["id"] for i in fx.info])

    def test_ac236_line_ranges_are_the_expected_numbers(self):
        # layout: 4 lines, boundary 5, summary 6, 4 lines, boundary 11, summary 12, 4 lines, boundary 17, summary 18
        self.standard()
        self.inject()
        got = {n["seq"]: (n["first_line"], n["last_line"]) for n in self.nodes()}
        self.assertEqual(got, {1: (1, 4), 2: (6, 10), 3: (12, 16)})

    def test_ac236_missing_pre_tokens_is_null(self):
        fx = Fx(self.tpath, self.proj)
        fx.segment()
        fx.boundary()
        del fx.recs[fx.info[0]["line"] - 1]["compactMetadata"]["preTokens"]
        fx.live()
        fx.write()
        self.inject()
        ns = self.nodes()
        self.assertEqual(len(ns), 1)
        self.assertIsNone(ns[0]["pre_tokens"])

    def test_ac236_sync_error_does_not_change_output_or_exit(self):
        self.standard()
        # nodes.jsonl is a directory: every write to it fails
        os.makedirs(os.path.join(self.hd, "projects", key_for(self.proj), "nodes.jsonl"))
        out = self.inject()
        self.assertIn("Please continue with the exporter task", out)
        self.assertNotIn("Traceback", out)
        self.assertNotIn("summary node:", out)

    def test_ac237_run_twice_and_backfill_no_duplicates(self):
        self.standard()
        self.inject()
        self.part1()
        self.assertEqual(len(self.nodes()), 3)
        out = self.ok("nodes", "--backfill")
        self.assertIn("nodes: 0 added, 3 total", out.split("\n"))
        ids = [n["id"] for n in self.nodes()]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(ids), 3)

    def test_ac237_backfill_alone_adds_all(self):
        self.standard()
        out = self.ok("nodes", "--backfill")
        self.assertIn("nodes: 3 added, 3 total", out.split("\n"))
        self.assertEqual(len(self.nodes()), 3)

    def test_ac238_fourth_boundary_appends_only(self):
        fx = self.standard()
        self.inject()
        before = self.raw_lines()
        self.assertEqual(len(before), 3)
        fx.segment()
        info4 = fx.boundary()
        fx.append()
        self.part1()
        after = self.raw_lines()
        self.assertEqual(len(after), 4, after)
        self.assertEqual(after[:3], before)
        n4 = json.loads(after[3])
        self.assertEqual((n4["seq"], n4["id"], n4["prev"]), (4, info4["id"], fx.info[2]["id"]))
        self.assertEqual((n4["first_line"], n4["last_line"]), (info4["first"], info4["last"]))

    def test_ac238_state_file_next_to_nodes(self):
        self.standard()
        self.inject()
        self.assertTrue(os.path.isfile(os.path.join(os.path.dirname(self.nodes_path()), "nodes.state.json")))

    def test_ac239_subagent_transcript_leaf(self):
        sub = os.path.join(self.pdir, SID, "subagents", "agent-%s.jsonl" % AID)
        fx = Fx(sub, self.proj, agent=AID)
        fx.segment()
        fx.boundary()
        fx.live()
        fx.write()
        # the parent transcript has no boundary
        parent = Fx(self.tpath, self.proj)
        parent.segment()
        parent.write()
        key = SID + "-a-" + AID
        self.put_latest(BODY, sid=key)
        self.put_sidecar(sid=key, status="ok", age_s=30)
        self.add_health_row(SID, ts=iso(-30))
        p = self.payload_compact(agent=AID)
        self.part1(p)
        ns = self.nodes()
        self.assertEqual(len(ns), 1, ns)
        self.assertEqual(ns[0]["agent"], AID)
        self.assertEqual(os.path.realpath(ns[0]["transcript"]), os.path.realpath(sub))
        self.assertEqual(ns[0]["id"], node_id(SID, fx.info[0]["uuid"]))


# ---------------------------------------------------------------- ACs 240-243 map and describe
class Commands(NodesBase):
    def setUp(self):
        super().setUp()
        self.fx = self.standard()

    def test_ac240_map_lines_oldest_first(self):
        out = self.ok("map")
        lines = [l for l in out.rstrip("\n").split("\n") if l]
        self.assertEqual(len(lines), 4, out)
        self.assertEqual(lines[-1], "3 nodes in 1 sessions")
        for line, info in zip(lines[:3], self.fx.info):
            m = MAP_RE.match(line)
            self.assertIsNotNone(m, line)
            self.assertEqual(m.group(1), info["id"])
            self.assertEqual(m.group(2), info["ts"][:10] + " " + info["ts"][11:16])
            self.assertEqual(m.group(3), SID[:8])
            self.assertIsNone(m.group(4))
            self.assertEqual(int(m.group(5)), info["seq"])
            self.assertEqual((int(m.group(6)), int(m.group(7))), (info["first"], info["last"]))
            self.assertEqual(m.group(8).replace(",", ""), str(info["pre"]))

    def test_ac240_gist_starts_with_current_work_text(self):
        out = self.ok("map")
        lines = [l for l in out.rstrip("\n").split("\n") if MAP_RE.match(l)]
        self.assertEqual(len(lines), 3)
        for line, info in zip(lines, self.fx.info):
            gist = MAP_RE.match(line).group(9)
            k = info["seq"]
            # the AC says the gist starts with the Current Work text; a leading heading is tolerated
            self.assertRegex(gist, r"^(?:\d+\.\s*)?(?:Current Work:?\s*)?" + re.escape(work_text(k)), gist)
            self.assertLessEqual(len(gist), 160)
            self.assertNotIn("Primary Request", gist)

    def test_ac240_map_has_agent_part_for_subagent_nodes(self):
        sub = os.path.join(self.pdir, SID, "subagents", "agent-%s.jsonl" % AID)
        fx = Fx(sub, self.proj, agent=AID)
        fx.segment()
        fx.boundary()
        fx.write()
        out = self.ok("map")
        subl = [MAP_RE.match(l) for l in out.split("\n")]
        subl = [m for m in subl if m and m.group(4)]
        self.assertEqual(len(subl), 1, out)
        self.assertEqual((subl[0].group(3), subl[0].group(4)), (SID[:8], AID[:8]))
        self.assertIn("4 nodes in 1 sessions", out.split("\n"))

    def test_ac242_describe_node_two(self):
        i2 = self.fx.info[1]
        out = self.ok("describe", i2["id"])
        lines = out.split("\n")
        self.assertIn("id: " + i2["id"], lines)
        self.assertIn("seq: 2", lines)
        self.assertIn("lines: %d-%d" % (i2["first"], i2["last"]), lines)
        opens = [l for l in lines if l.startswith("open: ")]
        self.assertEqual(opens, ["open: python3 ~/.claude/hooks/recall.py open %s:%d" % (SID[:8], i2["first"])])
        for field in ("session:", "agent:", "time:", "pre_tokens:", "prev:", "handoff:"):
            self.assertTrue(any(l.startswith(field) for l in lines), field)
        self.assertIn("SUMTOKEN-2", out)
        self.assertIn("END-SUMTOKEN-2", out)
        self.assertNotIn("SUMTOKEN-3", out)
        self.assertNotIn("SUMTOKEN-1", out)

    def test_ac242_describe_prev_is_node_one(self):
        out = self.ok("describe", self.fx.info[1]["id"])
        self.assertIn("prev: " + self.fx.info[0]["id"], out.split("\n"))

    def test_ac243_unknown_node(self):
        r = self.rc("describe", "nzzzzzzzzzz")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("no node nzzzzzzzzzz", r.stdout + r.stderr)

    def test_ac243_search_unknown_node(self):
        r = self.rc("search", TOKEN, "--node", "nzzzzzzzzzz")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("no node nzzzzzzzzzz", r.stdout + r.stderr)


class EmptyProject(NodesBase):
    def test_ac241_no_boundaries(self):
        fx = Fx(self.tpath, self.proj)
        fx.segment()
        fx.live()
        fx.write()
        r = self.rc("map")
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertEqual(r.stdout.strip(), "no summary nodes yet")


# ---------------------------------------------------------------- AC 244 search by node
class SearchNodes(NodesBase):
    HIT = re.compile(r"^([0-9A-Za-z_-]{8}):(\d+) ")

    def setUp(self):
        super().setUp()
        self.fx = self.standard()
        self.i1, self.i2, self.i3 = self.fx.info
        # token lines: the 3rd line of segment 2 (line 9), of segment 3 (line 15), and the live user line (19)
        self.l2, self.l3, self.live = 9, 15, 19

    def hit_lines(self, out):
        return [l for l in out.split("\n") if self.HIT.match(l)]

    def tag_for(self, hits, line):
        got = [h for h in hits if self.HIT.match(h).group(2) == str(line)]
        self.assertEqual(len(got), 1, (line, hits))
        return got[0]

    def test_ac244_node_filter_shows_only_node_two(self):
        out = self.ok("search", TOKEN, "--keyword", "--node", self.i2["id"])
        hits = self.hit_lines(out)
        self.assertEqual([self.HIT.match(h).group(2) for h in hits], [str(self.l2)], out)

    def test_ac244_node_filter_node_three(self):
        out = self.ok("search", TOKEN, "--keyword", "--node", self.i3["id"])
        self.assertEqual([self.HIT.match(h).group(2) for h in self.hit_lines(out)], [str(self.l3)], out)

    def test_ac244_plain_search_tags_each_hit(self):
        out = self.ok("search", TOKEN, "--keyword")
        hits = self.hit_lines(out)
        self.assertEqual(len(hits), 3, out)
        self.assertTrue(self.tag_for(hits, self.l2).endswith(" [node %s]" % self.i2["id"]))
        self.assertTrue(self.tag_for(hits, self.l3).endswith(" [node %s]" % self.i3["id"]))

    def test_ac244_hit_after_last_boundary_is_live(self):
        out = self.ok("search", TOKEN, "--keyword")
        self.assertTrue(self.tag_for(self.hit_lines(out), self.live).endswith(" [node live]"))

    def test_ac244_hybrid_mode_hits_also_tagged(self):
        # the embedding server is down: hybrid falls back to keyword; the node tag is still on every hit
        out = self.ok("search", TOKEN)
        hits = self.hit_lines(out)
        self.assertEqual(len(hits), 3, out)
        self.assertTrue(self.tag_for(hits, self.l2).endswith(" [node %s]" % self.i2["id"]))
        self.assertTrue(self.tag_for(hits, self.live).endswith(" [node live]"))


# ---------------------------------------------------------------- ACs 245-246 inject
class Inject(NodesBase):
    def line_for(self, info):
        return ("- summary node: this chat continues after node %s (compaction #%d, lines %d-%d). See all nodes: "
                "python3 ~/.claude/hooks/recall.py map; one node: recall.py describe %s."
                % (info["id"], info["seq"], info["first"], info["last"], info["id"]))

    def test_ac245_compact_output_has_node_line(self):
        fx = self.standard()
        out = self.inject()
        self.assertIn(self.line_for(fx.info[2]), out.split("\n"))

    def test_ac245_node_line_is_right_after_recall_line(self):
        fx = self.standard()
        lines = self.inject().split("\n")
        rec = [i for i, l in enumerate(lines) if l.startswith("- recall:")]
        self.assertEqual(len(rec), 1, lines[:12])
        self.assertEqual(lines[rec[0] + 1], self.line_for(fx.info[2]))

    def test_ac245_startup_and_resume_do_not_get_the_line(self):
        self.standard()
        self.inject()
        for src in ("startup", "resume"):
            for args in (("--ledger",), ("--part", "1"), ("--check",)):
                r = self.run_post(self.payload_compact(source=src), args=args)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertNotIn("summary node:", r.stdout, (src, args))

    def test_ac246_no_boundary_no_line(self):
        fx = Fx(self.tpath, self.proj)
        fx.segment()
        fx.live()
        fx.write()
        out = self.inject()
        self.assertIn("Please continue with the exporter task", out)
        self.assertNotIn("summary node:", out)

    def test_ac246_malformed_line_in_nodes_file(self):
        fx = self.standard()
        self.inject()
        p = self.nodes_path()
        lines = self.raw_lines()
        with open(p, "w") as f:
            f.write("{this is not json\n")
            f.write(lines[0] + "\n")
            f.write("\n")
            f.write("[1, 2\n")
            f.write("\n".join(lines[1:]) + "\n")
        r = self.rc("map")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("Traceback", r.stdout + r.stderr)
        ids = [m.group(1) for m in (MAP_RE.match(l) for l in r.stdout.split("\n")) if m]
        self.assertEqual(ids, [i["id"] for i in fx.info])
        self.assertIn("3 nodes in 1 sessions", r.stdout.split("\n"))


# ---------------------------------------------------------------- AC 247 prove
class Prove(NodesBase):
    LINE = re.compile(r"^nodes: (\d+) boundaries, (\d+) leaves, (\d+) bad$", re.M)

    def test_ac247_prove_good(self):
        self.standard()
        self.inject()
        out = self.prove()
        self.assertIn("nodes: 3 boundaries, 3 leaves, 0 bad", out.split("\n"))

    def test_ac247_prove_without_prior_sync(self):
        # the nodes check runs after its own sync
        self.standard()
        out = self.prove()
        self.assertIn("nodes: 3 boundaries, 3 leaves, 0 bad", out.split("\n"))

    def test_ac247_overlapping_ranges_are_bad_and_fail(self):
        self.standard()
        self.inject()
        p = self.nodes_path()
        rows = [json.loads(l) for l in self.raw_lines()]
        for r in rows:
            if r["seq"] == 3:
                r["first_line"] = 8  # overlaps the range of leaf 2 (6-10)
        with open(p, "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        out = self.prove()
        m = self.LINE.search(out)
        self.assertIsNotNone(m, out)
        self.assertGreater(int(m.group(3)), 0, out)
        fm = re.search(r"failed (\d+)", out)
        self.assertIsNotNone(fm, out)
        self.assertGreaterEqual(int(fm.group(1)), 1, out)


if __name__ == "__main__":
    unittest.main()
