"""F88 Decisions list at scale (0.21.0, hooks 1.23.0). Code-blind: written from the F88 text only.
F88.a / f.1-f.5: `recall.py decisions`. F88.b-c / f.6-f.9: pointers, the subagent rule index, the ledger parts.
F88.d / f.10-f.11: the room signal of `--check`. F88.e / f.12: the `clear` entry of the installer. F88.f.13: the version checks are in
test_f90_version.py. Every child process gets a built environment (CLAUDE_CODE_SESSION_ID is set only where a test sets it)."""
import json, os, re, shutil, subprocess, sys, tempfile, unittest

from helpers import run_install, run_uninstall
from test_content import git
from test_f42_lossless_rules import entry
from test_f44_recall import key_for
from test_f58_subagent_start import Base as SubBase, rule_line
from test_f86_check_advice import Fix
from test_f87_safety import Home, SA, SB

INDEX_LINE = "INDEX (rules not shown in full above):"
NOTE = "Index entries are summaries: before you act on one, read the full entry: python3 "
COUNT_LINE = re.compile(r'^- \((\d+) more active entries not listed; search them: python3 \S*recall\.py decisions "<words>"\)$')
POINTER = "recall.py decisions"
ADVICE = "Run the installer again, then restart Claude Code."

R1 = "- D1 [2026-10-01] [rule] RULEAAA keep commit messages short | why: x"
R2 = "- D2 [2026-10-02] [rule] RULEBBB alert on grafana dashboards | why: x"
R3 = "- D3 [2026-10-03] [rule] RULECCC run builders three at once | why: x"
D4 = "- D4 [2026-10-04] [decision] DECDDD use sqlite for storage | why: x"
D5 = "- D5 [2026-10-05] DECEEE untagged choose postgres | why: x"
D6 = "- D6 [2026-10-06] [decision] DECFFF disk usage limit set | why: x"
D7 = "- D7 [2026-10-07] [decision] DECGGG use tabs in code | why: x"
T8 = "- D8 [2026-10-08] [task] TASKHHH approve the draft | why: x"
T9 = "- D9 [2026-10-09] [task] TASKIII check the disk backup | why: x"
S10 = "- D10 [2026-10-10] SUPERSEDED by D3 [2026-10-03]: [rule] OLDRULE use five builders | because: replaced"
X11 = "- D11 [2026-10-11] RESOLVED [2026-10-12]: finished | was: [task] TASKGONE approve the plan | why: y"
LEDGER = [R1, R2, R3, D4, D5, D6, D7, T8, T9, S10, X11]
ACTIVE_ORDER = [R3, R2, R1, D7, D6, D5, D4, T9, T8]  # F42.3: rules, decisions, tasks; newest first


def entry_lines(out):
    return [l for l in out.split("\n") if l.startswith("- D")]


# ------------------------------------------------------------------ F88.a: lookup
class Lookup(Home):
    def ledger(self, proj, lines):
        d = os.path.join(self.hd, "projects", key_for(proj))
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "decisions.md")
        with open(path, "w") as f:
            f.write("# Project decisions: %s\n%s\n" % (proj, "\n".join(lines)))
        return path

    def dec(self, *args, cwd=None, sid=None, proc_cwd=None):
        r = self.rc("decisions", *args, cwd=cwd, sid=sid, proc_cwd=proc_cwd or self.A)
        return r

    def ok(self, *args, **kw):
        r = self.dec(*args, **kw)
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout)
        return r.stdout

    def test_f88_f1_all_nine_active_lines_in_f42_order(self):
        path = self.ledger(self.A, LEDGER)
        out = self.ok(cwd=self.A)
        lines = out.rstrip("\n").split("\n")
        self.assertEqual(lines[0], "decisions: 9 of 9 active entries match (%s)" % path)
        self.assertEqual(entry_lines(out), ACTIVE_ORDER)
        self.assertEqual(lines[1:], ACTIVE_ORDER)

    def test_f88_f1_kind_decision_keeps_four_lines_with_the_untagged_one(self):
        self.ledger(self.A, LEDGER)
        out = self.ok("--kind", "decision", cwd=self.A)
        self.assertEqual(entry_lines(out), [D7, D6, D5, D4])
        self.assertTrue(out.startswith("decisions: 4 of 9 active entries match ("), out[:120])

    def test_f88_a_kind_rule_and_kind_task(self):
        self.ledger(self.A, LEDGER)
        self.assertEqual(entry_lines(self.ok("--kind", "rule", cwd=self.A)), [R3, R2, R1])
        self.assertEqual(entry_lines(self.ok("--kind", "task", cwd=self.A)), [T9, T8])

    def test_f88_f1_closed_adds_the_superseded_and_the_resolved_entry(self):
        self.ledger(self.A, LEDGER)
        out = self.ok("--closed", cwd=self.A)
        lines = entry_lines(out)
        self.assertEqual(len(lines), 11, out)
        self.assertEqual(lines[:9], ACTIVE_ORDER)
        self.assertEqual(sorted(lines[9:]), sorted([S10, X11]))
        self.assertTrue(out.startswith("decisions: 9 of 9 active entries match ("), out[:120])

    def test_f88_a_the_default_leaves_the_closed_entries_out(self):
        self.ledger(self.A, LEDGER)
        out = self.ok(cwd=self.A)
        self.assertNotIn("OLDRULE", out)
        self.assertNotIn("TASKGONE", out)

    def test_f88_f2_an_id_prints_the_full_line(self):
        self.ledger(self.A, LEDGER)
        out = self.ok("D2", cwd=self.A)
        self.assertEqual(entry_lines(out), [R2])
        self.assertTrue(out.startswith("decisions: 1 of 9 active entries match ("), out[:120])

    def test_f88_f2_two_patterns_print_each_matching_entry_one_time(self):
        self.ledger(self.A, LEDGER)
        out = self.ok("grafana", "disk", cwd=self.A)
        self.assertEqual(entry_lines(out), [R2, D6, T9])
        self.assertTrue(out.startswith("decisions: 3 of 9 active entries match ("), out[:120])

    def test_f88_f2_an_entry_with_both_words_is_printed_once(self):
        self.ledger(self.A, LEDGER + ["- D12 [2026-10-12] [decision] DECBOTH grafana and disk alerts | why: x"])
        out = self.ok("grafana", "disk", cwd=self.A)
        self.assertEqual(entry_lines(out).count("- D12 [2026-10-12] [decision] DECBOTH grafana and disk alerts | why: x"), 1)
        self.assertEqual(len(entry_lines(out)), 4, out)

    def test_f88_a_case_does_not_matter(self):
        self.ledger(self.A, LEDGER)
        self.assertEqual(entry_lines(self.ok("GRAFANA", cwd=self.A)), [R2])

    def test_f88_a_a_pattern_with_no_match_prints_zero_of_nine(self):
        self.ledger(self.A, LEDGER)
        out = self.ok("nomatchwordxyz", cwd=self.A)
        self.assertTrue(out.startswith("decisions: 0 of 9 active entries match ("), out[:120])
        self.assertEqual(entry_lines(out), [])

    def test_f88_f3_a_planted_token_is_redacted(self):
        token = "ghp_" + "Ab1Cd2Ef3Gh4Ij5Kl6Mn7Op8Qr9St0Uv1Wx2"
        self.ledger(self.A, LEDGER + ["- D12 [2026-10-12] [decision] DECKEY we keep %s in the env | why: x" % token])
        out = self.ok("DECKEY", cwd=self.A)
        self.assertIn("[REDACTED:github]", out)
        self.assertNotIn(token, out)
        self.assertNotIn(token[4:], out)

    def test_f88_f4_no_ledger_prints_the_message_exit_0_and_creates_no_folder(self):
        r = self.dec(cwd=self.A)
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertIn("no decisions list", r.stdout)
        self.assertIn(self.A, r.stdout)
        self.assertEqual(r.stdout.strip().count("\n"), 0, r.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.hd, "projects", key_for(self.A))))
        self.assertFalse(os.path.exists(self.hd), "no state folder is created")

    def test_f88_a_the_command_writes_no_file(self):
        path = self.ledger(self.A, LEDGER)
        def snap():
            out = {}
            for d, dirs, files in os.walk(self.hd):
                for n in dirs + files:
                    p = os.path.join(d, n)
                    st = os.lstat(p)
                    out[p] = (st.st_size, st.st_mtime_ns)
            return out
        before = snap()
        self.ok("grafana", cwd=self.A)
        self.ok("--closed", cwd=self.A)
        self.assertEqual(snap(), before)
        self.assertTrue(os.path.exists(path))

    def test_f88_a_without_cwd_the_current_folder_is_used(self):
        self.ledger(self.A, LEDGER)
        r = self.rc("decisions", "D2", proc_cwd=self.A)
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertEqual(entry_lines(r.stdout), [R2])

    def test_f88_a_a_cut_output_ends_with_the_count_line(self):
        lines = [entry(n, "rule", 350) for n in range(1, 301)]
        self.ledger(self.A, lines)
        out = self.ok(cwd=self.A)
        last = out.rstrip("\n").split("\n")[-1]
        m = re.match(r"^\((\d+) more; add a pattern or --kind\)$", last)
        self.assertIsNotNone(m, last)
        self.assertGreater(int(m.group(1)), 0)
        shown = entry_lines(out)
        self.assertEqual(len(shown) + int(m.group(1)), 300)
        self.assertTrue(out.startswith("decisions: 300 of 300 active entries match ("), out[:120])

    def test_f88_f5_another_project_exits_2_with_the_session_of_project_a(self):
        self.ledger(self.B, LEDGER)
        r = self.dec(cwd=self.B, sid=SA)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual(r.stdout, "")
        self.assertIn("is another project", r.stderr)

    def test_f88_a_the_own_project_works_with_the_session_variable(self):
        self.ledger(self.A, LEDGER)
        r = self.dec(cwd=self.A, sid=SA)
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertEqual(entry_lines(r.stdout), ACTIVE_ORDER)


# ------------------------------------------------------------------ F88.c: the subagent rule index
class SubagentIndex(SubBase):
    def last_row(self):
        with open(self.health_path()) as f:
            return json.loads([l for l in f.read().split("\n") if l][-1])

    def test_f88_f6_sixty_rules_give_an_index_and_each_id_once(self):
        lines = [rule_line(n, 350) for n in range(1, 61)]
        path = self.write_ledger(lines)
        ctx = self.sub_ctx()
        self.assertLessEqual(len(ctx), 9900, len(ctx))
        out = ctx.split("\n")
        self.assertEqual(out.count(INDEX_LINE), 1, ctx[-800:])
        for n in range(1, 61):
            self.assertEqual(len([l for l in out if l.startswith("- D%d " % n)]), 1, n)
        row = self.last_row()
        self.assertEqual(row["rules"] + row["rules_index"], 60, row)
        at = out.index(INDEX_LINE)
        idx = [l for l in out[at + 1:] if re.match(r"^- D\d+ \[rule\] ", l)]
        self.assertEqual(len(idx), row["rules_index"], row)
        self.assertGreater(len(idx), 0)
        full = [l for l in out[:at] if l in set(lines)]
        self.assertEqual(len(full), row["rules"])
        ids_full = [int(re.match(r"- D(\d+) ", l).group(1)) for l in full]
        ids_idx = [int(re.match(r"- D(\d+) ", l).group(1)) for l in idx]
        self.assertEqual(ids_full, list(range(60, 60 - len(ids_full), -1)), "newest first")
        self.assertEqual(ids_idx, list(range(60 - len(ids_full), 60 - len(ids_full) - len(ids_idx), -1)), "index newest first")
        for l in idx:
            body = re.sub(r"(…|\.\.\.)$", "", re.match(r"^- D\d+ \[rule\] (.*)$", l).group(1))
            self.assertLessEqual(len(body), 90, l)
        more = [l for l in out if l.startswith("[more rules:")]
        self.assertEqual(len(more), 1)
        self.assertIn("recall.py decisions --kind rule", more[0])
        self.assertIn(path, more[0])
        self.assertNotIn('recall.py search "rule"', more[0])
        self.assertGreater(out.index(more[0]), out.index(idx[-1]), "the pointer line follows the index")

    def test_f88_f6_the_full_text_stays_within_4000_characters(self):
        lines = [rule_line(n, 350) for n in range(1, 61)]
        self.write_ledger(lines)
        ctx = self.sub_ctx()
        full = [l for l in ctx.split("\n") if l in set(lines)]
        self.assertLessEqual(sum(len(l) + 1 for l in full), 4000)
        self.assertGreaterEqual(len(full), 4)

    def test_f88_f7_two_rules_have_no_index_line_and_both_in_full(self):
        from test_f58_subagent_start import RULE_A, RULE_B
        self.write_ledger([RULE_A, RULE_B])
        ctx = self.sub_ctx()
        self.assertNotIn("INDEX", ctx)
        lines = ctx.split("\n")
        self.assertEqual(lines.count(RULE_A), 1)
        self.assertEqual(lines.count(RULE_B), 1)
        row = self.last_row()
        self.assertEqual(row["rules"], 2)
        self.assertEqual(row.get("rules_index", 0), 0)

    def test_f88_f8_four_hundred_rules_end_with_a_pointer_line_that_gives_a_count(self):
        lines = [rule_line(n, 350) for n in range(1, 401)]
        path = self.write_ledger(lines)
        ctx = self.sub_ctx()
        self.assertLessEqual(len(ctx), 9900, len(ctx))
        out = [l for l in ctx.split("\n") if l.strip()]
        more = [l for l in out if l.startswith("[more rules:")]
        self.assertEqual(len(more), 1, ctx[-600:])
        last_rule_pos = max(i for i, l in enumerate(out) if l.startswith("- D"))
        self.assertGreater(out.index(more[0]), last_rule_pos, "the pointer line comes after every rule line")
        self.assertEqual([l for l in out[out.index(more[0]) + 1:] if not l.startswith("- recall: ")], [])
        text = more[0].replace(path, "").replace("recall.py", "")
        self.assertRegex(text, r"\b\d+\b", more[0])
        self.assertIn("recall.py decisions --kind rule", more[0])
        row = self.last_row()
        self.assertLess(row["rules"] + row["rules_index"], 400)

    def test_f88_c_the_list_with_few_rules_keeps_the_old_shape(self):
        from test_f58_subagent_start import RULE_A, RULE_B, DEC, TASK
        self.write_ledger([RULE_A, DEC, RULE_B, TASK])
        ctx = self.sub_ctx()
        self.assertNotIn("INDEX", ctx)
        self.assertNotIn("[more rules:", ctx)
        self.assertNotIn('recall.py search "rule"', ctx)


# ------------------------------------------------------------------ F88.b: the ledger parts
class Parts(SubBase):
    def parts(self):
        outs = []
        for k in (1, 2, 3):
            r = self.run_post({"cwd": self.proj, "session_id": "N", "hook_event_name": "SessionStart", "source": "compact"},
                              args=("--ledger", "--part", str(k)))
            self.assertEqual((r.returncode, r.stderr), (0, ""))
            o = r.stdout
            if o.strip().startswith("{"):
                o = json.loads(o)["hookSpecificOutput"]["additionalContext"]
            outs.append(o)
        return outs

    def test_f88_f9_a_ledger_over_the_room_has_the_new_pointers(self):
        lines = [entry(n, "rule", 350) for n in range(1, 151)] + [entry(n, "decision", 350) for n in range(151, 301)]
        self.write_ledger(lines)
        outs = self.parts()
        for k, o in enumerate(outs, 1):
            self.assertLess(len(o), 10000, "part %d" % k)
        text = "\n".join(outs)
        self.assertIn(NOTE, text)
        i = text.index(NOTE)
        self.assertIn("recall.py decisions D<n>", text[i:i + 400])
        counts = [l for l in text.split("\n") if COUNT_LINE.match(l)]
        self.assertEqual(len(counts), 1, text[-800:])
        self.assertNotIn("read the full ledger)", text)
        self.assertNotIn("read the full entry in ", text)

    def test_f88_b_the_count_line_is_the_last_line_of_the_last_part_with_text(self):
        lines = [entry(n, "rule", 350) for n in range(1, 151)] + [entry(n, "decision", 350) for n in range(151, 301)]
        self.write_ledger(lines)
        outs = [o for o in self.parts() if o.strip()]
        last = outs[-1].rstrip("\n").split("\n")[-1]
        self.assertRegex(last, COUNT_LINE)


# ------------------------------------------------------------------ F88.d: the room signal
INFO = re.compile(r"^info: decisions list: (\d+) rules, (\d+) of (\d+) characters of full-text room \((\d+)%\); "
                  r"(\d+) active entries; (\d+) not listed$", re.M)


class Room(Fix):
    def setUp(self):
        super().setUp()
        self.rroot = os.path.join(os.path.realpath(self.tmp), "r", "proj")
        os.makedirs(self.rroot)
        git(self.rroot, "init", "-q")
        self.pdir = os.path.join(self.hd, "projects", key_for(self.rroot))

    def ledger(self, lines):
        os.makedirs(self.pdir, exist_ok=True)
        os.chmod(self.hd, 0o700)
        os.chmod(os.path.dirname(self.pdir), 0o700)
        with open(os.path.join(self.pdir, "decisions.md"), "w") as f:
            f.write("# Project decisions: %s\n%s\n" % (self.rroot, "\n".join(lines)))

    def verbose(self):
        out = self.run_check("--verbose", cwd=self.rroot)
        m = INFO.search(out)
        self.assertIsNotNone(m, out)
        return out, tuple(int(x) for x in m.groups())

    def plain(self):
        return self.run_check(cwd=self.rroot)

    def rules(self, n, width=300, last_width=None):
        lines = [entry(i, "rule", width) for i in range(1, n + 1)]
        if last_width:
            lines[-1] = entry(n, "rule", last_width)
        return lines

    def test_f88_f10_three_short_rules_print_the_info_line_and_no_problem(self):
        self.ledger([R1, R2, R3])
        out, (r, c, room, p, a, u) = self.verbose()
        self.assertEqual((r, a, u), (3, 3, 0), out)
        self.assertGreater(room, 0)
        self.assertGreater(c, 0)
        self.assertLessEqual(c, room)
        self.assertLessEqual(abs(p - c * 100 / room), 1.0, out)
        self.assertNotIn("decisions list:", self.plain().replace("info: decisions list:", ""))

    def test_f88_f10_the_info_line_counts_active_entries_of_all_kinds(self):
        self.ledger(LEDGER)
        out, (r, c, room, p, a, u) = self.verbose()
        self.assertEqual((r, a), (3, 9), out)

    def test_f88_d_the_info_line_is_only_in_verbose(self):
        self.ledger([R1, R2, R3])
        self.assertNotIn("info: decisions list:", self.plain())

    def test_f88_f11_rules_at_95_percent_of_the_room_are_a_data_problem(self):
        n = 1
        while True:
            self.ledger(self.rules(n))
            p = self.verbose()[1][3]
            if p >= 95 or n >= 250:
                break
            n += 1
        self.assertGreaterEqual(p, 95)
        lo, hi = 20, 300
        while lo < hi:
            mid = (lo + hi) // 2
            self.ledger(self.rules(n, last_width=mid))
            if self.verbose()[1][3] >= 95:
                hi = mid
            else:
                lo = mid + 1
        self.ledger(self.rules(n, last_width=lo))
        out, (r, c, room, p, a, u) = self.verbose()
        self.assertEqual(p, 95, out)
        text = self.plain()
        self.assertIn("rules use 95% of the room", text)
        self.assertIn("decisions list: rules use 95% of the room; retire or merge rules (recall.py decisions --kind rule)", text)
        self.assertNotIn("installer", text, "a data problem gives no installer advice")

    def test_f88_d_rules_under_90_percent_are_no_problem(self):
        n = 1
        while True:
            self.ledger(self.rules(n))
            p = self.verbose()[1][3]
            if p >= 80 or n >= 250:
                break
            n += 1
        self.assertLess(p, 90)
        self.assertNotIn("of the room", self.plain())

    def test_f88_f11_rules_that_do_not_fit_are_index_lines_only(self):
        self.ledger(self.rules(150, width=350))
        text = self.plain()
        m = re.search(r"decisions list: (\d+) rules are index lines only", text)
        self.assertIsNotNone(m, text)
        k = int(m.group(1))
        self.assertGreater(k, 0)
        self.assertNotIn("installer", text, "a data problem gives no installer advice")
        shown = 0
        self.LEDGER_ENV = None  # the proof fixtures switch the ledger off; the parts need it on
        for part in (1, 2, 3):
            r = self.run_post({"cwd": self.rroot, "session_id": "N", "hook_event_name": "SessionStart", "source": "compact"},
                              args=("--ledger", "--part", str(part)))
            o = r.stdout
            if o.strip().startswith("{"):
                o = json.loads(o)["hookSpecificOutput"]["additionalContext"]
            shown += len([l for l in o.split("\n") if re.match(r"^- D\d+ \[\d{4}-\d\d-\d\d\] \[rule\] ", l)])
        self.assertEqual(shown + k, 150, (shown, k))

    def test_f88_d_both_data_lines_come_without_installer_advice(self):
        self.ledger(self.rules(150, width=350))
        out = self.plain()
        self.assertNotIn(ADVICE, out)


# ------------------------------------------------------------------ F88.e: the clear entry
def matcher_has(group, name):
    return name in (group.get("matcher") or "").split("|")


def clear_commands(settings, name="clear"):
    return [h for g in settings.get("hooks", {}).get("SessionStart", []) if matcher_has(g, name) for h in g.get("hooks", [])]


def ledger_parts(cmds):
    found = set()
    for h in cmds:
        m = re.search(r"postcompact-inject\.py\s+--ledger\s+--part[ =](\d)(\s|$)", h.get("command", ""))
        if m:
            found.add(int(m.group(1)))
    return found


class ClearEntry(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="f88-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self.sp = os.path.join(self.home, ".claude", "settings.json")

    def install(self, *args):
        r = run_install(self.home, "--no-nightly", *args)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r

    def settings(self):
        with open(self.sp) as f:
            return json.load(f)

    def test_f88_f12_install_registers_the_three_ledger_commands_for_clear(self):
        self.install()
        s = self.settings()
        cmds = clear_commands(s)
        self.assertEqual(ledger_parts(cmds), {1, 2, 3}, cmds)
        ledger = [h for h in cmds if "--ledger" in h.get("command", "")]
        self.assertEqual(len(ledger), 3, cmds)

    def test_f88_e_the_clear_entry_has_the_rules_of_the_startup_entry(self):
        self.install()
        s = self.settings()
        def shape(name):
            return sorted((h.get("type"), h.get("timeout"), re.sub(r".*(--ledger\s+--part[ =]\d).*", r"\1", h["command"]))
                          for h in clear_commands(s, name) if "--ledger" in h.get("command", ""))
        self.assertEqual(shape("clear"), shape("startup"))
        self.assertEqual(len(shape("clear")), 3)

    def test_f88_f12_a_second_install_adds_none(self):
        self.install()
        before = self.settings()["hooks"]["SessionStart"]
        self.install()
        after = self.settings()["hooks"]["SessionStart"]
        self.assertEqual(after, before)
        self.assertEqual(len([h for h in clear_commands(self.settings()) if "--ledger" in h["command"]]), 3)

    def test_f88_e_dry_run_writes_nothing(self):
        r = run_install(self.home, "--no-nightly", "--dry-run")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(os.path.exists(self.sp))

    def test_f88_e_dry_run_keeps_a_settings_file_without_the_entry(self):
        os.makedirs(os.path.dirname(self.sp))
        text = json.dumps({"hooks": {"PreCompact": [{"hooks": [{"type": "command", "command": "echo other"}]}]}})
        with open(self.sp, "w") as f:
            f.write(text)
        r = run_install(self.home, "--no-nightly", "--dry-run")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(self.sp) as f:
            self.assertEqual(f.read(), text)

    def test_f88_f12_uninstall_removes_the_entry_and_keeps_other_hooks(self):
        os.makedirs(os.path.dirname(self.sp))
        foreign = {"type": "command", "command": "echo mine-clear"}
        other = {"type": "command", "command": "echo other-precompact"}
        with open(self.sp, "w") as f:
            json.dump({"hooks": {"SessionStart": [{"matcher": "clear", "hooks": [foreign]}],
                                 "PreCompact": [{"hooks": [other]}]}}, f)
        self.install()
        self.assertEqual(ledger_parts(clear_commands(self.settings())), {1, 2, 3})
        r = run_uninstall(self.home)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        s = self.settings()
        self.assertNotIn("postcompact-inject", json.dumps(clear_commands(s)))
        self.assertIn(foreign, clear_commands(s))
        self.assertIn(other, [h for g in s["hooks"]["PreCompact"] for h in g["hooks"]])


class ClearCheck(Fix):
    def drop_clear(self, d):
        groups = []
        for g in d["hooks"]["SessionStart"]:
            if matcher_has(g, "clear"):
                rest = [m for m in g["matcher"].split("|") if m != "clear"]
                if not rest:
                    continue
                g = dict(g, matcher="|".join(rest))
            groups.append(g)
        d["hooks"]["SessionStart"] = groups

    def test_f88_f12_a_settings_file_with_no_clear_entry_is_an_install_problem(self):
        self.write_settings(self.drop_clear)
        out = self.run_check()
        self.assertIn("clear", out)
        self.assertIn(ADVICE, out)

    def test_f88_e_a_full_install_has_no_clear_problem(self):
        self.write_settings()
        self.assertEqual(ledger_parts(clear_commands(json.load(open(self.settings)))), {1, 2, 3})
        out = self.run_check()
        self.assertNotIn("clear", out)


if __name__ == "__main__":
    unittest.main()
