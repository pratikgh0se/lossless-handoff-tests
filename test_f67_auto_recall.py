"""F67 Auto-recall, opt-in (code-blind: written from the orchestrator contract contract-0.15.md, F67.a-e; no hook or installer
source was read). Release 0.19.0, hooks 1.21.0.

F67.a  `hooks/auto-recall.py` is a UserPromptSubmit command hook (`python3 <hooks dir>/auto-recall.py`, timeout 5). It is
       opt-in: `install.sh --auto-recall`. `--save-defaults` writes `auto_recall=1`; `--no-auto-recall` turns a saved
       default off for one run; a re-install never removes it and prints `auto-recall: already installed, kept`.
       Uninstall removes the file and its settings entry. `--dry-run` lists it. `HANDOFF_AUTO_RECALL=0` = no output.
F67.b  The hook fires only when the prompt does not start with `/` and has a past-reference cue (16 phrases, case
       insensitive) or a double-quoted phrase of 3 or more words.
F67.c  Query: the prompt without the cue phrases, the 8 longest words of 4+ characters; fewer than 2 such words = no
       output. Top 3 hits of the project's transcripts, snippet at most 300 characters, redacted. Output: header line, one
       `- <id> <YYYY-MM-DD HH:MM> <role>: <snippet>` line per hit, and `Open one in full: python3
       ~/.claude/hooks/recall.py open <id>`. The current prompt is excluded. No hits = no output. Exit code is always 0.
F67.d  Each run that passes the trigger appends one JSON line {"ts","session_id","fired":true,"hits","ms","timed_out"} to
       `~/.local/state/claude-handoffs/auto-recall.jsonl`: no prompt text, no snippets.
F67.e  Product 0.19.0, HOOK_VERSION 1.21.0 (auto-recall.py too).

Assumptions (the contract is silent): stdout may be the plain text or a JSON `hookSpecificOutput.additionalContext` object;
both are accepted. The last line is exact, with a literal `<id>`. Fixtures are fake transcripts in a temp HOME;
embeddings are off (closed port), so the search is word only."""
import hashlib, json, os, re, shutil, subprocess, sys, tempfile, time, unittest

import helpers
from helpers import HOOKS_DIR, REPO, HookCase, installed_home, run_install, run_uninstall
from test_content import git
from test_f64_minimal_install import Base as InstBase, DEFAULTS_REL, read_settings, tree, window_of

HOOK = os.path.join(HOOKS_DIR, "auto-recall.py")
HEADER = "Lossless Handoff auto-recall: earlier messages that match your words. Verify them before you rely on them."
KEPT = "auto-recall: already installed, kept"
HOOK_REL = ".claude/hooks/auto-recall.py"
HIT_RE = re.compile(r"^- (?P<id>\S+) (?P<ts>\d{4}-\d\d-\d\d \d\d:\d\d) (?P<role>user|assistant): (?P<snip>.*)$")
OPEN_LINE = "Open one in full: python3 ~/.claude/hooks/recall.py open <id>"  # F67.c: exact text, a literal <id>
CUES = ["what did i say", "what did you say", "what did we decide", "did we decide", "did we agree", "did i say",
        "did i tell you", "we decided", "we agreed", "i told you", "i said", "you said", "you mentioned", "i mentioned",
        "last time", "previously", "as we discussed", "as discussed", "which one did", "earlier you", "earlier i",
        "earlier we", "said earlier", "said before", "as before", "like before", "same as before", "do you remember",
        "remember when", "remember what"]  # F67.b as amended 2026-11-22
BARE = ["run the tests before you commit postgres billing", "an earlier version of the postgres billing database",
        "remember to check the postgres billing database", "did i forget the postgres billing database",
        "did we ship the postgres billing database", "what was the postgres billing database",
        "before postgres billing database", "earlier postgres billing database", "remember postgres billing database",
        "did i postgres billing database", "did we postgres billing database"]


def auto_entries(settings):
    out = []
    for g in (settings.get("hooks") or {}).get("UserPromptSubmit", []):
        for h in g.get("hooks", []):
            if "auto-recall.py" in h.get("command", ""):
                out.append(h)
    return out


# ------------------------------------------------------------------ F67.a install
class Install(InstBase):
    def defaults_path(self, home=None):
        return os.path.join(home or self.home, DEFAULTS_REL)

    def test_f67_a_default_install_has_no_auto_recall(self):
        home, _ = installed_home()
        self.assertFalse(os.path.exists(os.path.join(home, HOOK_REL)))
        s = read_settings(home)
        self.assertEqual(auto_entries(s), [])
        self.assertNotIn("auto-recall", json.dumps(s))

    def test_f67_a_flag_installs_and_registers_a_user_prompt_submit_command(self):
        self.install("--auto-recall")
        self.assertTrue(os.path.isfile(self.p(HOOK_REL)))
        entries = auto_entries(read_settings(self.home))
        self.assertEqual(len(entries), 1, entries)
        e = entries[0]
        self.assertEqual(e.get("type"), "command")
        self.assertEqual(e.get("timeout"), 5)
        self.assertRegex(e["command"], r"^python3 \S*/\.claude/hooks/auto-recall\.py$|^python3 <HOME>/\.claude/hooks/auto-recall\.py$")

    def test_f67_a_flag_adds_only_the_hook_and_its_entry(self):
        base, _ = installed_home()
        self.install("--auto-recall")
        self.assertEqual(tree(self.home), tree(base) | {HOOK_REL})
        mine, theirs = read_settings(self.home), read_settings(base)
        mine["hooks"].pop("UserPromptSubmit", None)
        theirs["hooks"].pop("UserPromptSubmit", None)
        self.assertEqual(mine, theirs)

    def test_f67_a_installed_file_is_the_repo_file(self):
        self.install("--auto-recall")
        with open(HOOK, "rb") as a, open(self.p(HOOK_REL), "rb") as b:
            self.assertEqual(a.read(), b.read())

    def test_f67_a_dry_run_lists_it_only_with_the_flag(self):
        r = run_install(self.home, "--dry-run", "--auto-recall")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("auto-recall.py", r.stdout + r.stderr)
        self.assertIn("UserPromptSubmit", r.stdout + r.stderr)
        self.assertEqual(sorted(os.listdir(self.home)), [])
        r = run_install(self.home, "--dry-run")
        plan = "\n".join(l for l in (r.stdout + r.stderr).split("\n") if "not selected" not in l)
        self.assertNotIn("auto-recall.py", plan)
        self.assertNotIn("UserPromptSubmit", plan)

    def test_f67_a_help_lists_both_flags(self):
        r = run_install(self.home, "--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("--auto-recall", r.stdout)
        self.assertIn("--no-auto-recall", r.stdout)

    def test_f67_a_save_defaults_writes_the_line_and_a_plain_run_applies_it(self):
        self.install("--auto-recall", "--save-defaults")
        self.assertIn("auto_recall=1", open(self.defaults_path()).read().split("\n"))
        home2 = os.path.join(self.tmp, "home2")
        os.makedirs(os.path.join(home2, ".config", "lossless-handoff"))
        shutil.copy(self.defaults_path(), self.defaults_path(home2))
        r = run_install(home2)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(os.path.isfile(os.path.join(home2, HOOK_REL)))
        self.assertEqual(len(auto_entries(read_settings(home2))), 1)

    def test_f67_a_no_auto_recall_turns_a_saved_default_off_for_one_run(self):
        self.install("--auto-recall", "--save-defaults")
        home2 = os.path.join(self.tmp, "home2")
        os.makedirs(os.path.join(home2, ".config", "lossless-handoff"))
        shutil.copy(self.defaults_path(), self.defaults_path(home2))
        r = run_install(home2, "--no-auto-recall")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(os.path.exists(os.path.join(home2, HOOK_REL)))
        self.assertEqual(auto_entries(read_settings(home2)), [])
        self.assertIn("auto_recall=1", open(self.defaults_path(home2)).read().split("\n"), "the file is unchanged")

    def test_f67_a_save_defaults_with_no_flag_removes_the_line(self):
        self.install("--auto-recall", "--save-defaults")
        self.install("--no-auto-recall", "--save-defaults")
        self.assertNotIn("auto_recall=1", open(self.defaults_path()).read().split("\n"))
        # the installed part stays (a --no-* flag only skips adding)
        self.assertTrue(os.path.isfile(self.p(HOOK_REL)))

    def test_f67_a_without_save_defaults_no_line_is_written(self):
        self.install("--auto-recall")
        path = self.defaults_path()
        if os.path.exists(path):
            self.assertNotIn("auto_recall=1", open(path).read().split("\n"))

    def test_f67_a_rerun_keeps_it_and_prints_the_kept_line(self):
        self.install("--auto-recall")
        before = open(self.p(HOOK_REL), "rb").read()
        r = self.install()
        lines = [l for l in (r.stdout + r.stderr).split("\n") if l.startswith(KEPT)]
        self.assertEqual(len(lines), 1, r.stdout + r.stderr)
        self.assertEqual(open(self.p(HOOK_REL), "rb").read(), before)
        self.assertEqual(len(auto_entries(read_settings(self.home))), 1)
        r = self.install("--no-auto-recall")
        self.assertTrue(os.path.isfile(self.p(HOOK_REL)))
        self.assertEqual(len(auto_entries(read_settings(self.home))), 1)

    def test_f67_a_rerun_with_the_flag_does_not_register_it_twice(self):
        self.install("--auto-recall")
        self.install("--auto-recall")
        self.assertEqual(len(auto_entries(read_settings(self.home))), 1)

    def test_f67_a_no_kept_line_without_an_install(self):
        r = self.install()
        self.assertNotIn(KEPT, r.stdout + r.stderr)
        r = self.install("--auto-recall")
        self.assertNotIn(KEPT, r.stdout + r.stderr)

    def test_f67_a_uninstall_removes_the_file_and_the_settings_entry(self):
        before = {"permissions": {"allow": ["Bash(ls:*)"]}, "hooks": {"UserPromptSubmit": [
            {"hooks": [{"type": "command", "command": "echo mine"}]}]}}
        self.put_settings(before)
        self.install("--auto-recall")
        self.assertEqual(len(auto_entries(read_settings(self.home))), 1)
        self.uninstall()
        self.assertFalse(os.path.exists(self.p(HOOK_REL)))
        with open(self.sp()) as f:
            self.assertEqual(json.load(f), before)


# ------------------------------------------------------------------ F67.b-d the hook
class HookBase(HookCase):
    def setUp(self):
        super().setUp()
        self.rt = os.path.realpath(self.tmp)
        self.proj = os.path.join(self.rt, "proj")
        os.makedirs(self.proj)
        git(self.proj, "init", "-q")
        self.sid = "67676767-0000-4000-8000-000000000067"
        tdir = os.path.join(self.home, ".claude", "projects", re.sub(r"[^A-Za-z0-9]", "-", self.proj))
        os.makedirs(tdir)
        self.session = os.path.join(tdir, self.sid + ".jsonl")
        self.n = 0

    def seed(self, messages, current=None):
        """messages: list of (role, text). `current` is appended as the last user message (Claude Code writes the
        prompt to the transcript before the hook runs)."""
        with open(self.session, "w") as f:
            for role, text in list(messages) + ([("user", current)] if current else []):
                self.n += 1
                f.write(json.dumps({"type": role, "sessionId": self.sid, "cwd": self.proj,
                                    "timestamp": "2026-03-01T12:%02d:00.000Z" % (self.n % 60),
                                    "message": {"role": role, "content": text if role == "user" else
                                                [{"type": "text", "text": text}]}}) + "\n")

    def env2(self, extra=None):
        e = {"HOME": self.home, "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8", "TZ": "UTC",
             "RECALL_EMBED_URL": "http://127.0.0.1:9"}
        e.update(extra or {})
        return e

    def run_hook(self, prompt, extra=None, raw=None, payload_extra=None):
        payload = {"session_id": self.sid, "transcript_path": self.session, "cwd": self.proj, "prompt": prompt,
                   "hook_event_name": "UserPromptSubmit"}
        payload.update(payload_extra or {})
        t0 = time.time()
        r = subprocess.run([sys.executable, HOOK], input=json.dumps(payload) if raw is None else raw,
                           capture_output=True, text=True, env=self.env2(extra), timeout=30, cwd=self.tmp)
        self.elapsed = time.time() - t0
        return r

    @staticmethod
    def context(stdout):
        """The additional context: plain stdout, or the additionalContext of a JSON hookSpecificOutput."""
        s = stdout.strip("\n")
        if s.startswith("{"):
            try:
                return json.loads(s)["hookSpecificOutput"]["additionalContext"].strip("\n")
            except (ValueError, KeyError, TypeError):
                pass
        return s

    def ctx(self, prompt, **kw):
        r = self.run_hook(prompt, **kw)
        self.assertEqual(r.returncode, 0, r.stderr)
        return self.context(r.stdout)

    def silent(self, prompt, **kw):
        r = self.run_hook(prompt, **kw)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "", r.stdout[:300])

    def log_lines(self):
        p = os.path.join(self.hd, "auto-recall.jsonl")
        if not os.path.exists(p):
            return []
        with open(p) as f:
            return [json.loads(l) for l in f if l.strip()]


MSGS = [("user", "We decided to use the postgres database for the billing service BILLINGMARK"),
        ("assistant", "Understood: postgres for the billing service, with nightly backups"),
        ("user", "The kubernetes cluster needs three nodes for the staging deployment"),
        ("assistant", "I will plan three nodes for the staging deployment")]
CURRENT = "ZQCURRENT"


class Trigger(HookBase):
    def setUp(self):
        super().setUp()
        self.seed(MSGS)

    def test_f67_b_no_cue_prints_nothing(self):
        self.silent("Please design the postgres billing database schema")

    def test_f67_b_slash_prompt_prints_nothing(self):
        self.silent("/recall what did i say about the postgres billing database")

    def test_f67_b_each_cue_fires(self):
        for cue in CUES:
            with self.subTest(cue):
                out = self.ctx("%s the postgres billing database" % cue)
                self.assertTrue(out.startswith(HEADER), (cue, out[:200]))

    def test_f67_b_bare_words_do_not_fire(self):
        for prompt in BARE:
            with self.subTest(prompt):
                self.silent(prompt)
        self.assertEqual(self.log_lines(), [], "no cue, so no health line")

    def test_f67_b_cues_match_whole_words_only(self):
        for prompt in ("unwe decided postgres billing database", "previouslyx postgres billing database",
                       "we decidedly postgres billing database"):
            with self.subTest(prompt):
                self.silent(prompt)

    def test_f67_b_cues_are_case_insensitive(self):
        for cue in ("WHAT DID I SAY", "Last Time", "DO YOU REMEMBER"):
            with self.subTest(cue):
                self.assertTrue(self.ctx("%s the postgres billing database" % cue).startswith(HEADER))

    def test_f67_b_quoted_phrase_of_three_words_fires(self):
        out = self.ctx('use "postgres billing database" please')
        self.assertTrue(out.startswith(HEADER), out[:200])

    def test_f67_b_quoted_phrase_of_two_words_does_not_fire(self):
        self.silent('use "postgres billing" please')

    def test_f67_b_off_switch_prints_nothing_and_logs_nothing(self):
        self.silent("what did i say about the postgres billing database", extra={"HANDOFF_AUTO_RECALL": "0"})
        self.assertEqual(self.log_lines(), [])

    def test_f67_b_other_off_switch_values_do_not_disable_it(self):
        out = self.ctx("what did i say about the postgres billing database", extra={"HANDOFF_AUTO_RECALL": "1"})
        self.assertTrue(out.startswith(HEADER))


class Query(HookBase):
    def setUp(self):
        super().setUp()
        self.seed(MSGS)

    def test_f67_c_fewer_than_two_long_words_prints_nothing(self):
        self.silent("what did i say about it")
        self.silent("what did i say on postgres")  # one word of 4+ characters

    def test_f67_c_two_long_words_are_enough(self):
        out = self.ctx("what did i say about postgres database")  # `about` is a stop word since 0.19.0
        self.assertTrue(out.startswith(HEADER), out[:200])

    def test_f67_c_cue_phrases_do_not_count_as_query_words(self):
        # `previously` and `as discussed` are cues; only `postgres` is left
        self.silent("previously as discussed postgres")

    def test_f67_c_no_hits_prints_nothing(self):
        self.silent("what did i say about zebra giraffe antelope")


class Output(HookBase):
    def test_f67_c_format_header_hit_lines_and_open_line(self):
        self.seed(MSGS)
        out = self.ctx("what did i say about the postgres billing database")
        lines = out.split("\n")
        self.assertEqual(lines[0], HEADER)
        hits = [HIT_RE.match(l) for l in lines[1:-1]]
        self.assertTrue(hits and all(hits), lines)
        self.assertLessEqual(len(hits), 3)
        self.assertEqual(lines[-1], OPEN_LINE)
        self.assertTrue(any("billing" in h.group("snip") for h in hits))

    def test_f67_c_at_most_three_hits(self):
        self.seed([("user", "Note %d about the postgres billing database design" % i) for i in range(8)])
        out = self.ctx("what did i say about the postgres billing database")
        hits = [l for l in out.split("\n") if HIT_RE.match(l)]
        self.assertEqual(len(hits), 3, out)

    def test_f67_c_snippet_is_at_most_300_characters(self):
        self.seed([("user", "postgres billing database " + "filler " * 200 + "TAILMARK")])
        out = self.ctx("what did i say about the postgres billing database")
        hits = [HIT_RE.match(l) for l in out.split("\n") if HIT_RE.match(l)]
        self.assertTrue(hits, out)
        for h in hits:
            self.assertLessEqual(len(h.group("snip")), 300, len(h.group("snip")))
        self.assertNotIn("TAILMARK", out)

    def test_f67_c_snippet_whitespace_is_collapsed(self):
        self.seed([("user", "postgres\n\n  billing\t\tdatabase\n\nnotes   here")])
        out = self.ctx("what did i say about the postgres billing database")
        hits = [HIT_RE.match(l) for l in out.split("\n") if HIT_RE.match(l)]
        self.assertTrue(hits, out)
        for h in hits:
            self.assertNotRegex(h.group("snip"), r"\s{2,}|\t")

    def test_f67_c_snippet_is_redacted(self):
        key = "sk-" + "FAKEautorecall" * 3 + "0001"
        self.seed([("user", "gateway deployment password=zqautorecall0042 and key %s end" % key)])
        out = self.ctx("what did i say about the gateway deployment")
        self.assertIn("[REDACTED:", out)
        self.assertNotIn("zqautorecall0042", out)
        self.assertNotIn(key, out)

    def test_f67_c_current_prompt_is_excluded(self):
        self.seed(MSGS, current="what did i say about the postgres billing database %s" % CURRENT)
        out = self.ctx("what did i say about the postgres billing database %s" % CURRENT)
        self.assertTrue(out.startswith(HEADER), out[:200])
        self.assertNotIn(CURRENT, out)
        self.assertFalse(any("what did i say" in l for l in out.split("\n")[1:]))

    def test_f67_c_only_the_current_prompt_matches_prints_nothing(self):
        self.seed(MSGS, current="what did i say about the zebra giraffe antelope %s" % CURRENT)
        self.silent("what did i say about the zebra giraffe antelope %s" % CURRENT)

    def test_f67_c_other_chats_of_the_project_are_searched(self):
        other = os.path.join(os.path.dirname(self.session), "a1a1a1a1-0000-4000-8000-0000000000aa.jsonl")
        with open(other, "w") as f:
            f.write(json.dumps({"type": "user", "sessionId": "a1a1a1a1-0000-4000-8000-0000000000aa", "cwd": self.proj,
                                "timestamp": "2026-02-01T09:00:00.000Z",
                                "message": {"role": "user", "content": "the zeppelin rollout uses canary releases"}}) + "\n")
        self.seed(MSGS)
        out = self.ctx("what did i say about the zeppelin rollout canary")
        self.assertIn("zeppelin", out)


class NeverFails(HookBase):
    def setUp(self):
        super().setUp()
        self.seed(MSGS)

    def test_f67_c_bad_input_exits_0(self):
        for raw in ("{not json", "", "[]", "null", "{}", json.dumps({"prompt": 5}), json.dumps({"prompt": None})):
            with self.subTest(raw[:20]):
                r = self.run_hook("x", raw=raw)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(r.stdout.strip(), "")

    def test_f67_c_missing_transcript_exits_0(self):
        r = self.run_hook("what did i say about the postgres billing database",
                          payload_extra={"transcript_path": os.path.join(self.tmp, "missing.jsonl")})
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_f67_c_missing_cwd_exits_0(self):
        r = self.run_hook("what did i say about the postgres billing database",
                          payload_extra={"cwd": os.path.join(self.tmp, "no", "such", "dir")})
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_f67_c_missing_home_state_exits_0(self):
        shutil.rmtree(os.path.join(self.home, ".claude"))
        r = self.run_hook("what did i say about the postgres billing database")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_f67_c_finishes_within_the_time_budget(self):
        self.run_hook("what did i say about the postgres billing database")
        self.assertLess(self.elapsed, 5.0, self.elapsed)


class Health(HookBase):
    def setUp(self):
        super().setUp()
        self.seed(MSGS)

    def test_f67_d_a_fired_run_appends_one_line_with_the_fields(self):
        out = self.ctx("what did i say about the postgres billing database")
        hits = [l for l in out.split("\n") if HIT_RE.match(l)]
        rows = self.log_lines()
        self.assertEqual(len(rows), 1, rows)
        row = rows[0]
        self.assertTrue({"ts", "session_id", "fired", "hits", "ms", "timed_out"} <= set(row), row)
        self.assertIs(row["fired"], True)
        self.assertEqual(row["session_id"], self.sid)
        self.assertEqual(row["hits"], len(hits))
        self.assertIs(type(row["hits"]), int)
        self.assertIs(type(row["ms"]), int)
        self.assertIs(row["timed_out"], False)
        self.assertIsInstance(row["ts"], str)

    def test_f67_d_cue_field_is_the_matched_cue_phrase(self):
        for cue in ("what did we decide", "last time", "you mentioned", "do you remember"):
            with self.subTest(cue):
                n = len(self.log_lines())
                self.ctx("%s the postgres billing database" % cue)
                rows = self.log_lines()
                self.assertEqual(len(rows), n + 1)
                self.assertEqual(rows[-1]["cue"], cue)

    def test_f67_d_cue_field_is_quote_for_a_quoted_phrase(self):
        self.ctx('use "postgres billing database" please')
        self.assertEqual(self.log_lines()[-1]["cue"], "quote")

    def test_f67_d_cue_field_holds_no_prompt_text(self):
        self.ctx("what did i say about the postgres billing database ZQCUE")
        row = self.log_lines()[-1]
        self.assertEqual(row["cue"], "what did i say")
        self.assertNotIn("ZQCUE", json.dumps(row))

    def test_f67_d_log_holds_no_prompt_text_and_no_snippets(self):
        self.ctx("what did i say about the postgres billing database")
        with open(os.path.join(self.hd, "auto-recall.jsonl")) as f:
            text = f.read()
        for word in ("postgres", "billing", "BILLINGMARK", "kubernetes", "about the"):
            self.assertNotIn(word, text)

    def test_f67_d_a_run_without_hits_logs_zero_hits(self):
        self.silent("what did i say about zebra giraffe antelope")
        rows = self.log_lines()
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual((rows[0]["fired"], rows[0]["hits"]), (True, 0))

    def test_f67_d_runs_that_do_not_pass_the_trigger_log_nothing(self):
        self.silent("Please design the postgres billing database schema")
        self.silent("/recall what did i say about the postgres billing database")
        self.assertEqual(self.log_lines(), [])

    def test_f67_d_two_runs_append_two_lines(self):
        self.ctx("what did i say about the postgres billing database")
        self.ctx("did we decide the kubernetes staging deployment")
        self.assertEqual(len(self.log_lines()), 2)


# ------------------------------------------------------------------ F67.e versions
class Versions(unittest.TestCase):
    def test_f67_e_install_sh_version_is_0_20_0(self):
        home = os.path.realpath(tempfile.mkdtemp(prefix="f67v-"))
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        r = run_install(home, "--version")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("0.20.0", r.stdout + r.stderr)

    def test_f67_e_installed_manifest_version_is_1_22_0(self):
        home, _ = installed_home()
        with open(os.path.join(home, ".claude", "hooks", ".handoff-manifest.json")) as f:
            self.assertEqual(json.load(f)["version"], "1.22.0")

    def test_f67_e_changelog_has_0_20_0_first(self):
        with open(os.path.join(REPO, "CHANGELOG.md")) as f:
            heads = re.findall(r"(?m)^## \[([0-9.]+)\]", f.read())
        self.assertEqual(heads[0], "0.20.0")

    def test_f67_e_hook_version_constants_are_1_22_0(self):
        for n in ("precompact-handoff.py", "postcompact-inject.py", "auto-recall.py"):
            p = os.path.join(HOOKS_DIR, n)
            self.assertTrue(os.path.isfile(p), n)
            with open(p) as f:
                self.assertRegex(f.read(), r"""HOOK_VERSION\s*=\s*["']1\.22\.0["']""", n)

    def test_f67_e_auto_recall_file_is_in_the_manifest_when_installed(self):
        home, _ = installed_home("--auto-recall")
        with open(os.path.join(home, ".claude", "hooks", ".handoff-manifest.json")) as f:
            self.assertIn("auto-recall.py", json.load(f)["files"])


if __name__ == "__main__":
    unittest.main()
