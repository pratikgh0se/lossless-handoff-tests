"""F84 Batch recall calls (0.20.0, hooks 1.22.0). Code-blind: written from the F84 text only (acceptance 1 to 10).
`open` takes 1 to 10 ids, `search` takes 1 to 5 patterns, and every exit-2 error prints a usage line on stderr.
Single-id `open` and single-pattern `search` keep the old output: the tests compare them with the matching part of a
batch call, because the old bytes are not stored here. Fixtures: temp HOME, keyword-only recall."""
import os, re, subprocess, sys, unittest

from helpers import REPO, installed_home
from test_f44_recall import RecallBase, RECALL
from test_content import git

SID = "84000001-0000-4000-8000-000000000001"
SID2 = "84000002-0000-4000-8000-000000000002"
S8, S28 = SID[:8], SID2[:8]
COUNT = re.compile(r"^\d+ hits? shown of \d+")
USAGE = re.compile(r'^usage: python3 (?P<path>\S+recall\.py) search "<words>" \["<words>" \.\.\.\] \| open <id> \[<id> \.\.\.\] '
                   r'\| user --last 20$')
HEAD = re.compile(r"^--- (?P<id>\S+) \S+.* (user|assistant)")
CUT = re.compile(r"\[cut: (\d+) more chars")
NOT_SHOWN_IDS = re.compile(r"^\[not shown: (?P<ids>.+); run open again with these ids\]$")
NOT_SHOWN_PAT = re.compile(r'^\[not shown: (?P<pats>.+); run search again with these patterns\]$')
NO_MSG = re.compile(r"^recall\.py: no message for (?P<id>\S+) \((?P<why>.+)\)$")


class Base(RecallBase):
    def setUp(self):
        super().setUp()
        recs = []
        for i, w in enumerate(("GAMMAONE", "GAMMATWO", "GAMMATHREE"), 1):
            recs.append(self.rec("user" if i % 2 else "assistant", "%s message number %d of the fixture here" % (w, i),
                                 sid=SID, cwd=self.proj, day=6, minute=i))
        for i in range(4, 16):  # 12 messages that hold both search words
            recs.append(self.rec("assistant", [{"type": "text", "text": "alpha item %d together with beta item %d ok" % (i, i)}],
                                 sid=SID, cwd=self.proj, day=6, minute=i))
        recs.append(self.rec("user", "an unrelated closing prompt", sid=SID, cwd=self.proj, day=6, minute=30))
        self.write_session(os.path.join(self.tdir(self.proj), SID + ".jsonl"), recs)
        self.ok("index")

    def mid(self, n, sid8=S8):
        return "%s:%d" % (sid8, n)

    def blocks(self, out):
        return [m.group("id") for m in (HEAD.match(l) for l in out.split("\n")) if m]

    def long_session(self, n, size, tag="LONG"):
        recs = [self.rec("assistant", [{"type": "text", "text": ("%s%02d " % (tag, i)) + "x" * (size - 7)}], sid=SID2,
                         cwd=self.proj, day=7, minute=i) for i in range(1, n + 1)]
        self.write_session(os.path.join(self.tdir(self.proj), SID2 + ".jsonl"), recs)
        return [self.mid(i, S28) for i in range(1, n + 1)]

    def usage_ok(self, r):
        last = r.stderr.rstrip("\n").split("\n")[-1]
        m = USAGE.match(last)
        self.assertTrue(m, "stderr:\n" + r.stderr)
        self.assertTrue(os.path.samefile(m.group("path"), RECALL), m.group("path"))


class OpenMany(Base):
    def test_f84_1_open_three_ids_prints_three_blocks_in_order(self):
        a, b, c = self.mid(1), self.mid(2), self.mid(3)
        r = self.rc("open", a, b, c)
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout)
        self.assertEqual(self.blocks(r.stdout), [a, b, c])
        self.assertLess(r.stdout.index("GAMMAONE"), r.stdout.index("GAMMATWO"))
        self.assertLess(r.stdout.index("GAMMATWO"), r.stdout.index("GAMMATHREE"))

    def test_f84_1_the_blocks_follow_the_argument_order(self):
        a, b, c = self.mid(1), self.mid(2), self.mid(3)
        out = self.ok("open", c, a, b)
        self.assertEqual(self.blocks(out), [c, a, b])

    def test_f84_a_with_two_or_more_ids_the_default_around_is_zero(self):
        out = self.ok("open", self.mid(2), self.mid(5))
        self.assertEqual(self.blocks(out), [self.mid(2), self.mid(5)])

    def test_f84_a_an_explicit_around_applies_to_each_id(self):
        out = self.ok("open", self.mid(2), self.mid(8), "--around", "1")
        heads = self.blocks(out)
        for n in (1, 2, 3, 7, 8, 9):
            self.assertIn(self.mid(n), heads)
        self.assertEqual(len(heads), 6, heads)

    def test_f84_a_a_repeated_id_prints_one_time(self):
        out = self.ok("open", self.mid(1), self.mid(2), self.mid(1))
        self.assertEqual(self.blocks(out), [self.mid(1), self.mid(2)])
        self.assertEqual(out.count("GAMMAONE"), 1)

    def test_f84_a_repeated_ids_are_removed_first_so_open_a_a_is_open_a(self):
        a = self.mid(2)
        self.assertEqual(self.ok("open", a, a), self.ok("open", a))
        self.assertGreater(len(self.blocks(self.ok("open", a, a))), 1, "the old default around of one id")

    def test_f84_a_the_limit_of_10_counts_the_ids_as_given(self):
        ids = [self.mid(i) for i in range(1, 11)] + [self.mid(1)]
        r = self.rc("open", *ids)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("recall.py: at most 10 ids in one call", r.stdout + r.stderr)

    def test_f84_1_a_single_id_open_is_the_old_open(self):
        one = self.ok("open", self.mid(2))
        self.assertEqual(one, self.ok("open", self.mid(2), "--around", "2"), "the default around of one id is 2")
        self.assertGreater(len(self.blocks(one)), 1)
        self.assertNotIn("not shown", one)
        self.assertNotIn("no message for", one)

    def test_f84_1_each_block_of_a_batch_equals_the_single_open_of_that_id(self):
        ids = [self.mid(1), self.mid(2), self.mid(3)]
        multi = self.ok("open", *ids)
        for i in ids:
            single = self.ok("open", i, "--around", "0")
            self.assertIn(single.rstrip("\n"), multi, i)

    def test_f84_a_open_one_id_with_from_is_still_valid(self):
        mid = self.long_session(1, 5000)[0]
        r = self.rc("open", mid, "--full", "--from", "1000")
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout[-200:])
        self.assertIn("[chars 1000-", r.stdout)


class OpenErrors(Base):
    def test_f84_2_an_unknown_id_between_good_ids_is_reported_and_the_rest_continue(self):
        a, b = self.mid(1), self.mid(2)
        r = self.rc("open", a, "zzzzzzzz:5", b)
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout)
        lines = r.stdout.split("\n")
        ia = next(i for i, l in enumerate(lines) if l.startswith("--- %s " % a))
        ib = next(i for i, l in enumerate(lines) if l.startswith("--- %s " % b))
        ie = next(i for i, l in enumerate(lines) if NO_MSG.match(l))
        self.assertTrue(ia < ie < ib, (ia, ie, ib))
        self.assertEqual(NO_MSG.match(lines[ie]).group("id"), "zzzzzzzz:5")

    def test_f84_2_a_malformed_id_is_reported_the_same_way(self):
        r = self.rc("open", self.mid(1), "notanid")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(any(NO_MSG.match(l) and NO_MSG.match(l).group("id") == "notanid" for l in r.stdout.split("\n")), r.stdout)

    def test_f84_2_when_no_id_prints_a_message_the_exit_code_is_2(self):
        r = self.rc("open", "zzzzzzzz:5", "yyyyyyyy:6")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        ids = [NO_MSG.match(l).group("id") for l in r.stdout.split("\n") if NO_MSG.match(l)]
        self.assertEqual(ids, ["zzzzzzzz:5", "yyyyyyyy:6"])
        self.usage_ok(r)

    def test_f84_3_eleven_ids_exit_2_with_the_cap_text_and_the_usage_line(self):
        r = self.rc("open", *[self.mid(i) for i in range(1, 12)])
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("recall.py: at most 10 ids in one call", r.stdout + r.stderr)
        self.assertEqual(self.blocks(r.stdout), [])
        self.usage_ok(r)

    def test_f84_a_ten_ids_are_accepted(self):
        r = self.rc("open", *[self.mid(i) for i in range(1, 11)])
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout)
        self.assertEqual(len(self.blocks(r.stdout)), 10)

    def test_f84_3_from_with_two_ids_exits_2(self):
        r = self.rc("open", self.mid(1), self.mid(2), "--from", "0")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.usage_ok(r)


class OpenCaps(Base):
    def test_f84_4_ten_long_messages_are_cut_at_1000_and_the_total_is_12000_or_less(self):
        ids = self.long_session(10, 5000)
        r = self.rc("open", *ids)
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout[-300:])
        out = r.stdout
        self.assertEqual(self.blocks(out), ids)
        self.assertLessEqual(len(out), 12000, len(out))
        cuts = [int(m) for m in CUT.findall(out)]
        self.assertEqual(cuts, [4000] * 10, cuts)
        self.assertLessEqual(max(len(m) for m in re.findall(r"x+", out)), 1000)
        self.assertGreaterEqual(max(len(m) for m in re.findall(r"x+", out)), 990)

    def test_f84_a_two_long_messages_get_a_larger_cap_each(self):
        ids = self.long_session(2, 9000)
        out = self.ok("open", *ids)
        runs = [len(m) for m in re.findall(r"x+", out)]
        self.assertEqual(len(runs), 2, runs)
        self.assertTrue(all(4900 <= n <= 5000 for n in runs), runs)  # 10000 // 2
        self.assertEqual(len(CUT.findall(out)), 2)

    def test_f84_a_whole_ids_removed_by_the_total_cap_are_listed_on_the_last_line(self):
        ids = self.long_session(30, 5000)
        args = [ids[2], ids[9], ids[16], ids[23]]  # --around 2 for each: 20 messages of 1,000 characters at least
        r = self.rc("open", *args, "--around", "2")
        self.assertEqual(r.returncode, 0, r.stdout[-300:])
        lines = r.stdout.rstrip("\n").split("\n")
        m = NOT_SHOWN_IDS.match(lines[-1])
        self.assertTrue(m, lines[-1][-200:])
        missing = m.group("ids").split(" ")
        self.assertTrue(missing)
        self.assertEqual(missing, args[len(args) - len(missing):], "the ids left out are the last ones, in argument order")
        self.assertIn(args[0], self.blocks(r.stdout))
        for i in missing:
            self.assertNotIn(i, self.blocks(r.stdout))
        self.assertNotIn("not shown", "\n".join(lines[:-1]))
        self.assertLessEqual(len(r.stdout), 12500)

    def test_f84_a_with_full_the_caps_of_f44_12_stay(self):
        """With --full no message is cut below 40000 characters, a longer one gets the F44.12 marker, and every id is
        either printed or named on the `[not shown: ...]` line (the 12,000 character total cap is not used)."""
        ids = self.long_session(2, 50000)
        r = self.rc("open", *ids, "--full")
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout[-300:])
        lines = r.stdout.rstrip("\n").split("\n")
        shown = self.blocks(r.stdout)
        m = NOT_SHOWN_IDS.match(lines[-1])
        listed = m.group("ids").split(" ") if m else []
        self.assertEqual(shown + listed, ids)
        self.assertTrue(shown)
        first = shown[0]
        self.assertIn("[cut: 10000 more chars; continue with: recall.py open %s --full --from 40000]" % first, r.stdout)
        self.assertEqual(max(len(x) for x in re.findall(r"x+", r.stdout)), 40000 - len("LONG01 "),
                         "the first 40000 characters of the message are printed")


class SearchMany(Base):
    def sections(self, out):
        lines = out.rstrip("\n").split("\n")
        idx = [i for i, l in enumerate(lines) if l.startswith("== ")]
        res = {}
        for k, i in enumerate(idx):
            end = idx[k + 1] if k + 1 < len(idx) else len(lines)
            res[lines[i][3:]] = lines[i + 1:end]
        return lines, idx, res

    def test_f84_5_two_patterns_print_one_mode_line_then_a_section_for_each(self):
        out = self.ok("search", "GAMMAONE", "GAMMATWO")
        lines, idx, sec = self.sections(out)
        self.assertTrue(lines[0].startswith("mode:"), lines[0])
        self.assertEqual(sum(1 for l in lines if l.startswith("mode:")), 1)
        self.assertEqual(lines[idx[0]], "== GAMMAONE")
        self.assertEqual(lines[idx[1]], "== GAMMATWO")
        self.assertEqual(idx[0], 1)
        for p in ("GAMMAONE", "GAMMATWO"):
            body = sec[p]
            self.assertTrue(COUNT.match(body[-1]), body)
            hits = self.hits("\n".join(body))
            self.assertEqual(len(hits), 1, body)
            self.assertIn(p, body[0])

    def test_f84_5_sections_follow_the_argument_order(self):
        out = self.ok("search", "GAMMATWO", "GAMMAONE")
        self.assertLess(out.index("== GAMMATWO"), out.index("== GAMMAONE"))

    def test_f84_5_a_single_pattern_search_is_the_old_search(self):
        one = self.ok("search", "GAMMAONE").rstrip("\n").split("\n")
        multi = self.ok("search", "GAMMAONE", "GAMMATWO").rstrip("\n").split("\n")
        self.assertEqual(one[0], multi[0])
        self.assertTrue(all(not l.startswith("== ") for l in one), one)
        self.assertEqual(multi[2:2 + len(one) - 1], one[1:])

    def test_f84_6_six_patterns_exit_2_with_the_cap_text(self):
        r = self.rc("search", *["w%d" % i for i in range(6)])
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("recall.py: at most 5 patterns in one call", r.stdout + r.stderr)
        self.usage_ok(r)

    def test_f84_b_five_patterns_are_accepted(self):
        r = self.rc("search", "GAMMAONE", "GAMMATWO", "GAMMATHREE", "alpha", "beta")
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout)
        self.assertEqual(sum(1 for l in r.stdout.split("\n") if l.startswith("== ")), 5)

    def test_f84_6_without_limit_each_pattern_shows_at_most_8_hits(self):
        out = self.ok("search", "alpha", "beta")
        _, _, sec = self.sections(out)
        for p in ("alpha", "beta"):
            self.assertEqual(len(self.hits("\n".join(sec[p]))), 8, p)
            self.assertRegex(sec[p][-1], r"^8 hits shown of 12")

    def test_f84_b_limit_applies_to_each_pattern(self):
        out = self.ok("search", "alpha", "beta", "--limit", "3")
        _, _, sec = self.sections(out)
        for p in ("alpha", "beta"):
            self.assertEqual(len(self.hits("\n".join(sec[p]))), 3, p)

    def test_f84_b_flags_apply_to_every_pattern(self):
        out = self.ok("search", "alpha", "beta", "--role", "user")
        _, _, sec = self.sections(out)
        for p in ("alpha", "beta"):
            self.assertEqual(self.hits("\n".join(sec[p])), [], p)

    def test_f84_b_a_pattern_with_no_hit_still_gets_its_section_and_count_line(self):
        out = self.ok("search", "GAMMAONE", "qqqnomatchqqq")
        _, _, sec = self.sections(out)
        self.assertTrue(COUNT.match(sec["qqqnomatchqqq"][-1]), sec)
        self.assertRegex(sec["qqqnomatchqqq"][-1], r"^0 hits")

    def test_f84_b_the_total_cap_lists_whole_patterns_that_are_left_out(self):
        recs = [self.rec("assistant", [{"type": "text", "text": ("pat%dword " % p) + ("filler%d " % i) * 60}], sid=SID2,
                         cwd=self.proj, day=7, minute=(p * 20 + i) % 59)
                for p in range(1, 6) for i in range(8)]
        self.write_session(os.path.join(self.tdir(self.proj), SID2 + ".jsonl"), recs)
        self.ok("index")
        pats = ["pat%dword" % p for p in range(1, 6)]
        r = self.rc("search", *pats, "--limit", "10")
        self.assertEqual(r.returncode, 0, r.stdout[-300:])
        lines = r.stdout.rstrip("\n").split("\n")
        m = NOT_SHOWN_PAT.match(lines[-1])
        if len(r.stdout) <= 12000 and not m:
            self.skipTest("the fixture did not reach the total output cap")
        self.assertTrue(m, lines[-1][-200:])
        listed = re.findall(r'"([^"]+)"', m.group("pats"))
        shown = [l[3:] for l in lines if l.startswith("== ")]
        self.assertTrue(listed and shown)
        self.assertEqual(shown + listed, pats)
        self.assertLessEqual(len(r.stdout), 12500)


class SearchErrors(Base):
    def test_f84_7_zero_sessions_prints_the_f83b_warning_one_time_and_last(self):
        empty = os.path.join(self.rt, "r", "empty-proj")
        os.makedirs(empty)
        git(empty, "init", "-q")
        r = self.rc("search", "foo", "bar", cwd=empty)
        lines = r.stdout.rstrip("\n").split("\n")
        warn = [l for l in lines if l.startswith("recall.py: no sessions for project ")]
        self.assertEqual(len(warn), 1, r.stdout)
        self.assertEqual(lines[-1], warn[0])
        self.assertIn("== foo", lines)
        self.assertIn("== bar", lines)
        self.assertEqual(sum(1 for l in lines if l.startswith("mode:")), 1)

    def test_f84_8_search_with_no_pattern_exits_2_with_the_usage_line_last_on_stderr(self):
        r = self.rc("search")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.usage_ok(r)
        self.assertGreaterEqual(len(r.stderr.rstrip("\n").split("\n")), 2, "an error line comes before the usage line")

    def test_f84_c_every_exit_2_error_has_the_usage_line(self):
        for args in (("open", "x:1", "--from", "0", "y:2"), ("open", *["a:%d" % i for i in range(11)]),
                     ("search", *["p%d" % i for i in range(6)])):
            with self.subTest(args[:2]):
                r = self.rc(*args)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.usage_ok(r)


class Injection(unittest.TestCase):
    """F84.d and F84.f.9: the new recall line text. The part 1 size limit is held by test_f44_12_blockers (180 entries)."""
    NEW = ("(same full path for: open <id> [<id> ...]; user --last 20. One call takes several patterns or several ids. "
           "Do not use cd, a loop or a shell variable)")
    OLD = "(same full path for: open <id>; user --last 20; do not cd)"

    def test_f84_d_the_text_is_the_recall_line_constant_of_the_tests(self):
        from test_f44_recall import RECALL_LINE
        self.assertIn(self.NEW, RECALL_LINE)
        self.assertNotIn(self.OLD, RECALL_LINE)


class DocsAndVersion(unittest.TestCase):
    def read(self, *parts):
        with open(os.path.join(REPO, *parts)) as f:
            return f.read()

    def test_f84_e_readme_and_recall_docs_show_one_example_of_each_batch_call(self):
        for parts in (("README.md",), ("docs", "recall.md")):
            t = self.read(*parts)
            with self.subTest(parts):
                self.assertRegex(t, r'recall\.py search "[^"\n]+" "[^"\n]+"')
                self.assertRegex(t, r"recall\.py open [^\s`<\[]\S* [^\s`<\[]\S*")

    def test_f84_e_the_readme_version_line_names_0_20_0_and_hooks_1_22_0(self):
        t = self.read("README.md")
        self.assertTrue([l for l in t.split("\n") if "0.20.0" in l and "1.22.0" in l], "no README line names both")

    def test_f84_d_the_recall_agent_file_says_one_call_takes_several_ids_or_patterns(self):
        home, _ = installed_home()
        with open(os.path.join(home, ".claude", "agents", "recall.md")) as f:
            t = f.read()
        self.assertRegex(t, r"(?i)several (ids|patterns)|(ids|patterns) in one call|one call takes")
        self.assertRegex(t, r"(?i)several ids|ids")
        self.assertRegex(t, r"(?i)several patterns|patterns")


if __name__ == "__main__":
    unittest.main()
