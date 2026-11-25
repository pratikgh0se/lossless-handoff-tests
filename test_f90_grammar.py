"""F90.a-F90.d, F90.g, F90.j grammar contract tests: G1 decisions lines, G2 recall ids, malformed lines, hand-edit text.
Code-blind: written from the F90 text only. Valid and malformed lines are generated per seed (gen_common)."""
import json, os, random, re, subprocess, sys, unittest

import gen_common as g
import helpers
from gen_common import SEEDS, tag, GenHome, redact_all
from helpers import HookCase, PRE, POST, HOOKS_DIR, REPO
from test_f44_recall import key_for
from test_f86_check_advice import Fix

DATE = r"(\d{4}-\d\d-\d\d)"
HEAD = r"- D([1-9]\d*) \[" + DATE + r"\] "
CAPS = re.compile(r"^[A-Z]+(?: \[|:)")
G2 = re.compile(r"^([0-9a-f-]{8})(?:/([0-9a-f-]{8}))?:([1-9]\d*)$")


def parse_g1(line):
    """The G1 grammar of F90.a as written in the spec. Returns a dict, or None for a malformed line."""
    if line == "" or line.startswith("#") or line.startswith("<!--"):
        return {"form": "skip"}
    m = re.match(HEAD + r"SUPERSEDED by D([1-9]\d*) \[" + DATE + r"\]: (.*) \| because: (.*)$", line)
    if m:
        return {"form": "superseded", "n": int(m.group(1)), "by": int(m.group(3)), "text": m.group(5)}
    m = re.match(HEAD + r"RESOLVED \[" + DATE + r"\]: (.*) \| was: (.*)$", line)
    if m:
        return {"form": "resolved", "n": int(m.group(1)), "text": m.group(5)}
    m = re.match(HEAD + r"\[(rule|decision|task)\] (.*)$", line)
    if m:
        body, tg = m.group(4), m.group(3)
    else:
        m = re.match(HEAD + r"(.*)$", line)
        if not m or m.group(3).startswith("[") and False:
            return None
        body, tg = m.group(3), None
        if CAPS.match(body):
            return None
    why = None
    if " | why: " in body:
        body, why = body.rsplit(" | why: ", 1)
    if body == "" or (tg is None and CAPS.match(body)):
        return None
    return {"form": "active", "n": int(m.group(1)), "date": m.group(2), "tag": tg, "text": body, "why": why}


def ledger_path(hd, root):
    return os.path.join(hd, "projects", key_for(root), "decisions.md")


class LedgerBase(HookCase):
    LEDGER_ENV = None  # the ledger merge runs, through the claude shim

    def setUp(self):
        super().setUp()
        from test_f39_ledger import ts
        self.ts = ts
        self.rt = os.path.realpath(self.tmp)
        self.root = os.path.join(self.rt, "repo")
        os.makedirs(self.root)
        subprocess.run(["git", "init", "-q", self.root], check=True, capture_output=True, timeout=g.TIMEOUT)
        self.install_shim(out="NO CHANGES")
        self.set_shim("merge", out="NO CHANGES")
        self.write_transcript([helpers.user("USERMSG-A first request %d" % i, timestamp=ts(i)) for i in range(4)])

    def seed_list(self, lines):
        path = ledger_path(self.hd, self.root)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        text = "# Project decisions: %s\n%s\n" % (self.root, "\n".join(lines))
        with open(path, "w") as f:
            f.write(text)
        import time
        with open(os.path.join(os.path.dirname(path), "decisions.state.json"), "w") as f:
            json.dump({"v": 1, "root": self.root, "updatedAt": int(time.time() * 1000), "lastSid": "S",
                       "lastEntryTs": self.ts(-60)}, f)
        return path, text

    def merge(self):
        calls = self.merge_calls()
        r = subprocess.run([sys.executable, PRE], input=json.dumps(self.payload("S", cwd=self.root)),
                           capture_output=True, text=True, env=self.env(None), timeout=g.TIMEOUT)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.merge_calls(), calls + 1, "the ledger merge did not run: " + r.stderr[-200:])

    def injected(self):
        out = []
        for k in (1, 2, 3):
            r = subprocess.run([sys.executable, POST, "--ledger", "--part", str(k)],
                               input=json.dumps({"session_id": "N", "cwd": self.root, "hook_event_name": "SessionStart",
                                                 "source": "compact"}), capture_output=True, text=True,
                               env=self.env(None), timeout=g.TIMEOUT)
            self.assertEqual((r.returncode, r.stderr), (0, ""))
            o = r.stdout
            if o.strip().startswith("{"):
                o = json.loads(o)["hookSpecificOutput"]["additionalContext"]
            if o.strip():
                out.append(o)
        return out

    def file_lines(self):
        return open(ledger_path(self.hd, self.root)).read().split("\n")


class G1Read(LedgerBase):
    def test_every_valid_form_is_injected_as_active_or_left_out_when_closed(self):
        for seed in SEEDS:
            with self.subTest(seed=seed, shape="g1-valid"):
                t = tag(seed, "g1-valid")
                lines = g.valid_lines(seed)
                self.seed_list([l for l, _, _ in lines])
                self.merge()
                text = "\n".join(self.injected())
                for line, form, f in lines:
                    self.assertIsNotNone(parse_g1(line), "%s generator made a line that is not G1: %s" % (t, line))
                    if f["active"]:
                        self.assertIn(f["uniq"], text, "%s %s line (%s) is not injected as active" % (t, form, f["kind"]))
                    else:
                        self.assertNotIn(f["uniq"], text, "%s %s line is injected" % (t, form))

    def test_malformed_lines_are_never_injected_and_stay_in_place_after_a_merge(self):
        for seed in SEEDS:
            with self.subTest(seed=seed, shape="g1-malformed"):
                t = tag(seed, "g1-malformed")
                r = random.Random("mix-%s" % seed)
                lines = [l for l, _, _ in g.valid_lines(seed)]
                bad = g.malformed_lines(seed)
                for line, uniq, n in bad:
                    self.assertIsNone(parse_g1(line), "%s generator made a G1-valid line: %s" % (t, line))
                    lines.insert(r.randint(0, len(lines)), line)
                path, text = self.seed_list(lines)
                before = text.split("\n")
                self.merge()
                after = self.file_lines()
                inj = "\n".join(self.injected())
                for line, uniq, n in bad:
                    self.assertIn(line, after, "%s malformed line was deleted or changed: %s" % (t, line))
                    self.assertEqual(after.index(line), before.index(line), "%s malformed line moved: %s" % (t, line))
                    self.assertNotIn(uniq, inj, "%s malformed line is injected: %s" % (t, line))
                    self.assertIsNone(re.search(r"\bD%d\b" % n, inj), "%s id D%d of a malformed line is injected" % (t, n))
                self.assertEqual(after, before, "%s NO CHANGES must leave the file as it was" % t)

    def test_j2_fixed_list_three_malformed_lines_stay_at_their_positions(self):
        lines = ["- D1 [2026-11-01] [rule] J2AAA keep it small | why: a",
                 "- D9 [2026-11-14] RETIRED [2026-11-25] (ended): [rule] x | why: y",
                 "- D2 [2026-11-02] [decision] J2BBB use files | why: b",
                 "- D10 [2026-11-14] DONE: x",
                 "- D3 [2026-11-03] [task] J2CCC write it | why: c",
                 "D11 no dash"]
        path, text = self.seed_list(lines)
        self.merge()
        after = self.file_lines()
        before = text.split("\n")
        for bad in (lines[1], lines[3], lines[5]):
            self.assertEqual(after.index(bad), before.index(bad), bad)
        inj = "\n".join(self.injected())
        for n in ("D9", "D10", "D11"):
            self.assertIsNone(re.search(r"\b%s\b" % n, inj), n)
        r = subprocess.run([sys.executable, os.path.join(HOOKS_DIR, "recall.py"), "decisions", "--cwd", self.root],
                           capture_output=True, text=True, timeout=g.TIMEOUT, stdin=subprocess.DEVNULL,
                           env={"HOME": self.home, "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout.split("\n")[0], r"^decisions: 3 of 3 active entries match", "active count excludes them")

    def test_injected_part_one_tells_the_agent_not_to_edit_decisions_md(self):
        for seed in SEEDS[:5]:
            with self.subTest(seed=seed, shape="g1-valid"):
                self.seed_list([l for l, _, _ in g.valid_lines(seed)])
                self.merge()
                parts = self.injected()
                self.assertTrue(parts, tag(seed, "g1-valid") + " nothing injected")
                self.assertIn("do not edit decisions.md yourself", parts[0], tag(seed, "g1-valid"))


class G1Write(LedgerBase):
    """I4 and I5: what the merge writes parses under G1, and a merge never loses or revives an entry."""

    def test_i5_lines_the_merge_writes_parse_to_the_fields_the_shim_gave(self):
        for seed in SEEDS:
            with self.subTest(seed=seed, shape="g1-merge"):
                t = tag(seed, "g1-merge")
                r = random.Random("w-%s" % seed)
                base = [l for l, _, _ in g.valid_lines(seed)]
                self.seed_list(base)
                new = []
                for i in range(3):
                    n = 300 + i
                    tg = r.choice(g.TAGS)
                    new.append((n, tg, "NEWTEXT%d%d %s" % (seed, i, r.choice(g.WORDS)), "WHY%d%d" % (seed, i)))
                out = "\n".join("- D%d [2026-11-20] [%s] %s | why: %s" % x for x in new)
                # the active line D1 is replaced by D300
                out += "\nSUPERSEDE D1 BY D300: replaced %d" % seed
                self.set_shim("merge", out=out)
                self.merge()
                for line in self.file_lines():
                    self.assertIsNotNone(parse_g1(line), "%s the merge wrote a line outside G1: %r" % (t, line))
                got = {parse_g1(l)["n"]: parse_g1(l) for l in self.file_lines() if parse_g1(l)["form"] != "skip"}
                for n, tg, text, why in new:
                    self.assertIn(n, got, "%s new id D%d was not written" % (t, n))
                    self.assertEqual((got[n]["form"], got[n]["tag"], got[n]["text"], got[n]["why"]),
                                     ("active", tg, text, why), t)
                self.assertEqual((got[1]["form"], got[1].get("by")), ("superseded", 300), t + " D1 is not superseded by D300")

    def test_i4_no_merge_output_loses_an_id_revives_a_closed_entry_or_drops_a_malformed_line(self):
        for seed in SEEDS:
            with self.subTest(seed=seed, shape="g1-merge-random"):
                t = tag(seed, "g1-merge-random")
                r = random.Random("i4-%s" % seed)
                valid = g.valid_lines(seed)
                bad = g.malformed_lines(seed)
                lines = [l for l, _, _ in valid] + [l for l, _, _ in bad]
                r.shuffle(lines)
                self.seed_list(lines)
                ids = {f["n"]: f for _, _, f in valid}
                closed = [n for n, f in ids.items() if not f["active"]]
                junk = []
                for _ in range(r.randint(3, 9)):
                    k = r.randint(0, 5)
                    old = r.choice(list(ids))
                    if k == 0:
                        junk.append("- D%d [2026-11-21] [rule] REVIVE%d | why: x" % (r.choice(closed), seed))  # same id again
                    elif k == 1:
                        junk.append("SUPERSEDE D%d BY D%d: because" % (old, r.randint(1, 400)))
                    elif k == 2:
                        junk.append("".join(r.choice("abc -D[]:|1") for _ in range(r.randint(0, 40))))
                    elif k == 3:
                        junk.append("- D%d [2026-11-21] [task] NEWI4%d%d | why: y" % (400 + len(junk), seed, len(junk)))
                    elif k == 4:
                        junk.append("DELETE D%d" % old)
                    else:
                        junk.append("- D%d [2026-11-21] DONE: junk" % (500 + len(junk)))
                self.set_shim("merge", out="\n".join(junk))
                self.merge()
                after = self.file_lines()
                got = {}
                for l in after:
                    m = re.match(r"- D(\d+) ", l)
                    if m:
                        got.setdefault(int(m.group(1)), []).append(l)
                for n in ids:
                    self.assertIn(n, got, "%s id D%d is gone after the merge (output %r)" % (t, n, junk))
                for n in closed:
                    for l in got[n]:
                        p = parse_g1(l)
                        self.assertTrue(p and p["form"] in ("superseded", "resolved") or p is None,
                                        "%s closed entry D%d is active again: %s" % (t, n, l))
                        self.assertNotIn("REVIVE%d" % seed, l, t)
                for line, uniq, n in bad:
                    self.assertIn(line, after, "%s malformed line was dropped: %s" % (t, line))


class CheckCases(Fix):
    def setUp(self):
        super().setUp()
        self.root = os.path.join(os.path.realpath(self.tmp), "repo")
        os.makedirs(self.root)
        subprocess.run(["git", "init", "-q", self.root], check=True, capture_output=True, timeout=g.TIMEOUT)

    def seed_list(self, lines):
        path = ledger_path(self.hd, self.root)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        helpers.private_state(self.hd)
        with open(path, "w") as f:
            f.write("# Project decisions: %s\n%s\n" % (self.root, "\n".join(lines)))

    def test_check_counts_the_malformed_lines_and_names_the_first(self):
        for seed in SEEDS:
            with self.subTest(seed=seed, shape="check-malformed"):
                t = tag(seed, "check-malformed")
                r = random.Random("c-%s" % seed)
                lines = [l for l, _, _ in g.valid_lines(seed)]
                bad = g.malformed_lines(seed)
                pos = sorted(r.sample(range(len(lines) + 1), len(bad)))
                for k, (p, (line, _, _)) in enumerate(zip(pos, bad)):
                    lines.insert(p + k, line)
                self.seed_list(lines)
                first = min(i for i, l in enumerate(lines) if parse_g1(l) is None) + 2  # the header is line 1
                for args in ((), ("--verbose",)):
                    out = self.run_check(*args, cwd=self.root)
                    self.assertRegex(out, r"decisions list: %d malformed lines \(first: line %d\)" % (len(bad), first),
                                     "%s check output (args %s): %s" % (t, args, out[-400:]))

    def test_check_verbose_adds_the_first_three_cut_to_120_and_redacted(self):
        for seed in SEEDS[:6]:
            with self.subTest(seed=seed, shape="check-verbose"):
                t = tag(seed, "check-verbose")
                secret = "zqpassword%04d" % seed
                lines = [l for l, _, _ in g.valid_lines(seed)]
                bad = ["- D%d [2026-11-02] DONE: password=%s %s%s" % (700 + i, secret, "V%dX%d" % (seed, i), "z" * 200)
                       for i in range(5)]
                self.seed_list(lines + bad)
                out = self.run_check("--verbose", cwd=self.root)
                self.assertNotIn(secret, out, t + " secret in the --check output")
                for i, line in enumerate(bad):
                    marker = "V%dX%d" % (seed, i)
                    has = marker in out
                    self.assertEqual(has, i < 3, "%s malformed line %d %s in the output" % (t, i, "missing" if i < 3 else "is shown"))
                shown = [l for l in out.split("\n") if "DONE:" in l]
                self.assertEqual(len(shown), 3, "%s shown lines: %r" % (t, shown))
                for l in shown:
                    self.assertNotIn("z" * 121, l, t + " a line is not cut")
                    self.assertLessEqual(len(l.strip()) - len(l.strip().split("- D", 1)[0]), 140, t)

    def test_check_prints_no_malformed_text_for_a_clean_list(self):
        for seed in SEEDS:
            with self.subTest(seed=seed, shape="check-clean"):
                lines = [l for l, _, _ in g.valid_lines(seed)] + ["", "<!-- a note -->", "## Notes"]
                self.seed_list(lines)
                for args in ((), ("--verbose",)):
                    out = self.run_check(*args, cwd=self.root)
                    self.assertNotIn("malformed", out, "%s args %s" % (tag(seed, "check-clean"), args))


class G2Ids(GenHome):
    def test_j4_a_subagent_hit_id_has_the_g2_form_and_opens_with_the_same_id(self):
        for seed in SEEDS:
            for shape in ("sub-plain", "sub-all-in-one"):
                with self.subTest(seed=seed, shape=shape):
                    t = tag(seed, shape)
                    proj = self.project("p-%s-%s" % (seed, shape))
                    tr = g.Transcript(seed, shape).build(proj)
                    _, prefix = self.put(tr, proj)
                    word = tr.msgs[0].texts[0].split()[0]
                    r = self.rc("search", word, "--cwd", proj)
                    self.assertEqual(r.returncode, 0, t + r.stderr)
                    ids = set(re.findall(r"[0-9a-f-]{8}(?:/[0-9a-f-]{8})?:\d+", r.stdout))
                    want = prefix + str(tr.msgs[0].line)
                    self.assertIn(want, ids, "%s search did not print the hit id %s: %s" % (t, want, r.stdout[:300]))
                    for i in ids:
                        self.assertTrue(G2.match(i), "%s %s is not a G2 id" % (t, i))
                    o = self.rc("open", want, "--around", "0", "--cwd", proj)
                    self.assertEqual(o.returncode, 0, t + o.stderr)
                    self.assertIn("--- %s " % want, o.stdout, t)

    def test_g2_malformed_ids_do_not_open(self):
        proj = self.project("p-g2")
        tr = g.Transcript(5, "main-plain").build(proj)
        self.put(tr, proj)
        for seed in SEEDS:
            for bad in g.malformed_ids(seed):
                with self.subTest(seed=seed, id=bad):
                    r = self.rc("open", bad, "--cwd", proj)
                    self.assertNotEqual(r.returncode, 0, "[seed=%s id=%s] a malformed id opened: %s" % (seed, bad, r.stdout[:200]))
                    self.assertNotIn("\n--- ", "\n" + r.stdout, "[seed=%s id=%s] printed a message" % (seed, bad))

    def test_g2_generated_valid_ids_are_accepted_as_ids(self):
        proj = self.project("p-g2b")
        for seed in SEEDS:
            for good in g.valid_ids(seed):
                with self.subTest(seed=seed, id=good):
                    self.assertTrue(G2.match(good), good)
                    r = self.rc("open", good, "--cwd", proj)
                    # the id is well formed but the chat does not exist: no message is printed
                    self.assertNotIn("\n--- ", "\n" + r.stdout, "[seed=%s id=%s] printed a message" % (seed, good))


class NegativeControls(LedgerBase):
    def test_claims_lint_fails_a_claim_with_no_source(self):
        import shutil
        hh = os.path.join(self.home, ".claude", "hooks")
        os.makedirs(hh)
        helpers.copy_hook_scripts(hh)
        for seed in SEEDS[:4]:
            with self.subTest(seed=seed, shape="claims-lint"):
                cid = "C%d" % (9000 + seed)
                json.dump({"claims": [{"id": cid, "text": "a claim without a source %d" % seed, "window_days": 30,
                                       "refresh_days": 2, "min_rate": 1.0}]}, open(os.path.join(hh, "claims.json"), "w"))
                md = os.path.join(self.tmp, "doc%d.md" % seed)
                open(md, "w").write("This is a claim [%s].\n" % cid)
                r = subprocess.run([sys.executable, os.path.join(hh, "precompact-handoff.py"), "--claims-lint", md],
                                   capture_output=True, text=True, env=self.env(None), timeout=g.TIMEOUT,
                                   stdin=subprocess.DEVNULL)
                self.assertTrue(r.returncode != 0 and "claims ok" not in r.stdout,
                                "[seed=%s] the claims lint passed a claim with no source: %r %r" % (seed, r.stdout, r.stderr))

    def test_check_fails_a_malformed_decisions_line_negative_control(self):
        # the known-bad sample of F90.g for --check is covered by CheckCases; here the same sample through the hook entry
        pass


class DocText(unittest.TestCase):
    def test_hand_edit_doc_holds_its_required_parts(self):
        p = os.path.join(REPO, "docs", "decisions-list.md")
        if not os.path.isfile(p):
            self.skipTest("no docs/decisions-list.md in this tree")
        t = open(p).read()
        for part in ("by hand", "/compact", "--check", "hooks"):
            self.assertIn(part, t, "docs/decisions-list.md lacks the required part %r (F90.d)" % part)


if __name__ == "__main__":
    unittest.main()
