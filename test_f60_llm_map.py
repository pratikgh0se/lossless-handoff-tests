"""F60 llm_map: ACs 274-280 of docs/spec.md. Code-blind: written from the spec only.
A fake `claude` (a Python script in a temp folder, set by LLM_MAP_CLAUDE) logs its argv, cwd and prompt,
parses the numbered item lines `<i>: <text>` and answers one `{"i": n, "out": "<label>"}` line per item.
Label rule: "even" or "odd" by item number. Every run uses a temp HOME; the network is never used."""
import json, os, re, shutil, subprocess, sys, tempfile, unittest

from helpers import HOOKS_DIR, run_install, run_uninstall

LLM_MAP = os.path.join(HOOKS_DIR, "llm_map.py")
MARKER = "<!-- lossless-handoff:llm-map-skill -->"
NOT_OURS = "~/.claude/skills/llm-map/SKILL.md exists and is not ours; left unchanged."
FOREIGN = "---\nname: llm-map\ndescription: my own skill\n---\nThis is my own file. FOREIGN-MARK\n"

FAKE = r'''#!PYTHON
import json, os, re, sys
argv = sys.argv[1:]
text = "\n".join(argv)
items = re.findall(r"(?m)^(\d+): (.*)$", text)
if not items:
    try:
        text = sys.stdin.read()
    except Exception:
        text = ""
    items = re.findall(r"(?m)^(\d+): (.*)$", text)
log = os.environ["FAKE_LOG"]
with open(log, "a") as f:
    f.write(json.dumps({"argv": argv, "cwd": os.getcwd(), "prompt": text, "items": [int(i) for i, _ in items]}) + "\n")
drop_once = os.environ.get("FAKE_DROP_ONCE")
drop_always = os.environ.get("FAKE_DROP_ALWAYS")
lines = []
for i, t in items:
    n = int(i)
    if drop_always and str(n) == drop_always:
        continue
    if drop_once and str(n) == drop_once:
        flag = log + ".dropped"
        try:
            os.close(os.open(flag, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            continue
        except FileExistsError:
            pass
    lines.append(json.dumps({"i": n, "out": "even" if n % 2 == 0 else "odd"}))
print(json.dumps({"type": "result", "is_error": False, "result": "\n".join(lines),
                  "total_cost_usd": float(os.environ.get("FAKE_COST", "0.01"))}))
'''


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="f60-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = os.path.join(self.tmp, "home")
        self.work = os.path.join(self.tmp, "work")
        os.makedirs(self.home)
        os.makedirs(self.work)
        self.fake = os.path.join(self.tmp, "fakebin", "fake-claude")
        os.makedirs(os.path.dirname(self.fake))
        with open(self.fake, "w") as f:
            f.write(FAKE.replace("PYTHON", sys.executable, 1))
        os.chmod(self.fake, 0o755)
        self.log = os.path.join(self.tmp, "fake.log")
        self.out = os.path.join(self.work, "out.jsonl")

    def items_file(self, n, name="in.txt"):
        p = os.path.join(self.work, name)
        with open(p, "w") as f:
            for i in range(1, n + 1):
                f.write("item text %d\n" % i)
        return p

    def run_map(self, args, env=None, timeout=120):
        self.assertTrue(os.path.isfile(LLM_MAP), "no llm_map.py in the hooks folder: %s" % LLM_MAP)
        e = {"HOME": self.home, "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8",
             "LLM_MAP_CLAUDE": self.fake, "FAKE_LOG": self.log}
        e.update(env or {})
        return subprocess.run([sys.executable, LLM_MAP, *args], env=e, cwd=self.work, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=timeout)

    def calls(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as f:
            return [json.loads(l) for l in f if l.strip()]

    def rows(self):
        with open(self.out) as f:
            return [json.loads(l) for l in f if l.strip()]

    def last_line(self, r):
        return [l for l in r.stdout.split("\n") if l.strip()][-1]


class Basic(Base):
    def test_ac274_hundred_items_three_batches(self):
        src = self.items_file(100)
        r = self.run_map(["--in", src, "--prompt", "Label parity", "--out", self.out, "--batch", "40"],
                         {"FAKE_COST": "0.0123"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        rows = self.rows()
        self.assertEqual(len(rows), 100)
        self.assertEqual([x["i"] for x in rows], list(range(1, 101)))
        for x in rows:
            self.assertEqual(x["out"], "even" if x["i"] % 2 == 0 else "odd")
            self.assertEqual(x["text"], "item text %d" % x["i"])
            self.assertNotIn("error", x)
        last = self.last_line(r)
        self.assertTrue(last.startswith("llm_map: 100 items, 100 ok, 0 failed, 3 batches, cost $"), last)
        self.assertEqual(last.split("cost $")[1].strip(), "0.0369")
        self.assertEqual(len(self.calls()), 3)

    def test_ac274_prompt_and_numbered_lines_reach_the_model(self):
        src = self.items_file(5)
        r = self.run_map(["--in", src, "--prompt", "PROMPT-MARK-F60", "--out", self.out])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        calls = self.calls()
        self.assertEqual(len(calls), 1)
        p = calls[0]["prompt"]
        self.assertIn("PROMPT-MARK-F60", p)
        for i in range(1, 6):
            self.assertIn("%d: item text %d" % (i, i), p)
        self.assertEqual(calls[0]["items"], [1, 2, 3, 4, 5])

    def test_ac274_empty_lines_skipped_and_numbers_follow_items(self):
        src = os.path.join(self.work, "gaps.txt")
        with open(src, "w") as f:
            f.write("alpha\n\nbeta\n\n\ngamma\n")
        r = self.run_map(["--in", src, "--prompt", "p", "--out", self.out])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        rows = self.rows()
        self.assertEqual([(x["i"], x["text"]) for x in rows], [(1, "alpha"), (2, "beta"), (3, "gamma")])

    def test_ac274_jobs_run_batches_and_keep_order(self):
        src = self.items_file(60)
        r = self.run_map(["--in", src, "--prompt", "p", "--out", self.out, "--batch", "10", "--jobs", "4"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual([x["i"] for x in self.rows()], list(range(1, 61)))
        self.assertIn("6 batches", self.last_line(r))

    def test_ac274_json_out_keeps_json_values(self):
        src = self.items_file(4)
        r = self.run_map(["--in", src, "--prompt", "p", "--out", self.out, "--json-out"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual([x["i"] for x in self.rows()], [1, 2, 3, 4])
        self.assertEqual(self.rows()[1]["out"], "even")


class Retry(Base):
    def test_ac275_dropped_once_is_retried(self):
        src = self.items_file(20)
        r = self.run_map(["--in", src, "--prompt", "p", "--out", self.out, "--batch", "20"], {"FAKE_DROP_ONCE": "7"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        rows = self.rows()
        self.assertEqual(len(rows), 20)
        x = rows[6]
        self.assertEqual(x["i"], 7)
        self.assertEqual(x["out"], "odd")
        self.assertNotIn("error", x)
        self.assertIn("20 ok, 0 failed", self.last_line(r))
        sent = [c for c in self.calls() if 7 in c["items"]]
        self.assertEqual(len(sent), 2, "item 7 must be sent a second time")

    def test_ac275_never_answered_fails_with_error(self):
        src = self.items_file(20)
        r = self.run_map(["--in", src, "--prompt", "p", "--out", self.out, "--batch", "20"], {"FAKE_DROP_ALWAYS": "7"})
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        rows = self.rows()
        self.assertEqual(len(rows), 20)
        x = rows[6]
        self.assertEqual(x["i"], 7)
        self.assertIsNone(x["out"])
        self.assertTrue(x.get("error"), "item 7 needs a short error text")
        self.assertIn("1 failed", self.last_line(r))
        self.assertIn("19 ok", self.last_line(r))
        self.assertEqual(sum(1 for c in self.calls() if 7 in c["items"]), 2, "item 7 is sent once more, not more")
        for y in rows:
            if y["i"] != 7:
                self.assertNotIn("error", y)


class Jsonl(Base):
    def test_ac276_jsonl_keeps_id(self):
        src = os.path.join(self.work, "in.jsonl")
        with open(src, "w") as f:
            for i in range(1, 6):
                f.write(json.dumps({"id": "doc-%d" % i, "text": "jsonl text %d" % i}) + "\n")
        r = self.run_map(["--in", src, "--prompt", "p", "--out", self.out])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        rows = self.rows()
        self.assertEqual([x["id"] for x in rows], ["doc-%d" % i for i in range(1, 6)])
        self.assertEqual([x["i"] for x in rows], [1, 2, 3, 4, 5])
        self.assertEqual([x["text"] for x in rows], ["jsonl text %d" % i for i in range(1, 6)])
        self.assertEqual(rows[1]["out"], "even")
        self.assertIn("2: jsonl text 2", self.calls()[0]["prompt"])

    def test_ac276_jsonl_without_id_has_no_id_key(self):
        src = os.path.join(self.work, "in.jsonl")
        with open(src, "w") as f:
            f.write(json.dumps({"text": "only text"}) + "\n")
        r = self.run_map(["--in", src, "--prompt", "p", "--out", self.out])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("id", self.rows()[0])


class Budget(Base):
    def test_ac277_max_usd_stops_new_batches(self):
        src = self.items_file(100)
        r = self.run_map(["--in", src, "--prompt", "p", "--out", self.out, "--batch", "10", "--jobs", "1",
                          "--max-usd", "0.15"], {"FAKE_COST": "0.10"})
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        rows = self.rows()
        self.assertEqual(len(rows), 100)
        budget = [x for x in rows if x.get("error") == "budget"]
        self.assertGreater(len(budget), 0)
        for x in budget:
            self.assertIsNone(x["out"])
        n_calls = len(self.calls())
        self.assertGreaterEqual(n_calls, 1)
        self.assertLess(n_calls, 10, "fewer fake calls than the batch count")
        m = re.search(r"(\d+) ok, (\d+) failed", self.last_line(r))
        self.assertIsNotNone(m, self.last_line(r))
        self.assertEqual(int(m.group(2)), len(budget))
        self.assertEqual(int(m.group(1)) + int(m.group(2)), 100)


class Usage(Base):
    def test_ac278_missing_in_file(self):
        r = self.run_map(["--in", os.path.join(self.work, "nope.txt"), "--prompt", "p", "--out", self.out])
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertTrue(r.stderr.strip(), "a message on stderr")
        self.assertFalse(os.path.exists(self.out))
        self.assertEqual(self.calls(), [])

    def test_ac278_input_with_no_items(self):
        src = os.path.join(self.work, "empty.txt")
        with open(src, "w") as f:
            f.write("\n\n\n")
        r = self.run_map(["--in", src, "--prompt", "p", "--out", self.out])
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertTrue(r.stderr.strip(), "a message on stderr")
        self.assertFalse(os.path.exists(self.out))
        self.assertEqual(self.calls(), [])

    def test_ac278_zero_byte_input(self):
        src = os.path.join(self.work, "zero.txt")
        open(src, "w").close()
        r = self.run_map(["--in", src, "--prompt", "p", "--out", self.out])
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertFalse(os.path.exists(self.out))

    def test_ac278_bad_flag(self):
        src = self.items_file(3)
        r = self.run_map(["--in", src, "--prompt", "p", "--out", self.out, "--no-such-flag"])
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertFalse(os.path.exists(self.out))


class ModelCall(Base):
    def test_ac279_argv_cwd_and_no_handoff_rows(self):
        src = self.items_file(6)
        r = self.run_map(["--in", src, "--prompt", "p", "--out", self.out])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        calls = self.calls()
        self.assertEqual(len(calls), 1)
        c = calls[0]
        argv = c["argv"]
        self.assertIn("-p", argv)
        i = argv.index("--model")
        self.assertEqual(argv[i + 1], "haiku")
        joined = " ".join(argv)
        self.assertTrue("--output-format json" in joined or "--output-format=json" in joined, joined)
        self.assertRegex(joined, r"--tools|--allowedTools|--allowed-tools|--disallowedTools|--disallowed-tools",
                         "no-tool setting")
        self.assertRegex(joined, r"hooks|--bare|disableAllHooks|--setting-sources", "no-hook setting")
        self.assertNotEqual(os.path.realpath(c["cwd"]), os.path.realpath(self.work))
        self.assertNotEqual(os.path.realpath(c["cwd"]), os.path.realpath(self.home))
        self.assertFalse(os.path.exists(c["cwd"]), "the temp cwd must be deleted after the run")
        state = os.path.join(self.home, ".local", "state", "claude-handoffs")
        found = []
        for root, _, files in os.walk(state):
            found += [os.path.join(root, f) for f in files]
        self.assertEqual(found, [], "no handoff, ledger or health row may appear")

    def test_ac279_model_flag_is_passed(self):
        src = self.items_file(3)
        r = self.run_map(["--in", src, "--prompt", "p", "--out", self.out, "--model", "sonnet"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        argv = self.calls()[0]["argv"]
        self.assertEqual(argv[argv.index("--model") + 1], "sonnet")

    def test_ac279_every_batch_gets_its_own_deleted_cwd(self):
        src = self.items_file(30)
        r = self.run_map(["--in", src, "--prompt", "p", "--out", self.out, "--batch", "10", "--jobs", "3"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        calls = self.calls()
        self.assertEqual(len(calls), 3)
        for c in calls:
            self.assertNotEqual(os.path.realpath(c["cwd"]), os.path.realpath(self.work))
            self.assertFalse(os.path.exists(c["cwd"]))


class Install(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="f60i-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self.skill = os.path.join(self.home, ".claude", "skills", "llm-map", "SKILL.md")
        self.settings = os.path.join(self.home, ".claude", "settings.json")

    def install(self, *args):
        # F64 (spec F64.a): the llm_map hook and skill are opt-in, so every install in this class adds `--llm-map`
        r = run_install(self.home, *args, "--llm-map")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r

    def put(self, text):
        os.makedirs(os.path.dirname(self.skill), exist_ok=True)
        with open(self.skill, "w") as f:
            f.write(text)

    def text(self):
        with open(self.skill) as f:
            return f.read()

    def test_ac280_fresh_install(self):
        self.install("--no-nightly")
        self.assertTrue(os.path.isfile(self.skill))
        t = self.text()
        self.assertIn(MARKER, t.split("\n"))
        self.assertIn("name: llm-map", t.split("\n"))
        self.assertIn("llm_map.py", t)
        self.assertRegex(t, r"(?m)^description:.+")
        self.assertTrue(os.path.isfile(os.path.join(self.home, ".claude", "hooks", "llm_map.py")))

    def test_ac280_settings_hook_entries_unchanged_by_feature(self):
        self.install("--no-nightly")
        with open(self.settings) as f:
            first = f.read()
        self.assertNotIn("llm_map", first)
        self.assertTrue(os.path.isfile(self.skill), "the feature must be installed")
        self.install("--no-nightly")
        with open(self.settings) as f:
            self.assertEqual(json.load(f).get("hooks"), json.loads(first).get("hooks"))

    def test_ac280_unmarked_skill_left_alone(self):
        self.put(FOREIGN)
        r = self.install("--no-nightly")
        self.assertEqual(self.text(), FOREIGN)
        self.assertIn(NOT_OURS, r.stdout + r.stderr)

    def test_ac280_marked_old_skill_is_replaced(self):
        self.put(MARKER + "\nOLD-CONTENT-MARK\n")
        self.install("--no-nightly")
        self.assertNotIn("OLD-CONTENT-MARK", self.text())
        self.assertIn("llm_map.py", self.text())

    def test_ac280_dry_run_writes_nothing(self):
        self.install("--dry-run", "--no-nightly")
        self.assertFalse(os.path.exists(self.skill))
        self.install("--no-nightly")
        self.assertTrue(os.path.isfile(self.skill), "a real install writes the skill")

    def test_ac280_uninstall_removes_marked_file(self):
        self.install("--no-nightly")
        self.assertTrue(os.path.isfile(self.skill), "install must write the skill first")
        r = run_uninstall(self.home)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(os.path.exists(self.skill))

    def test_ac280_uninstall_keeps_unmarked_file(self):
        self.put(FOREIGN)
        self.install("--no-nightly")
        r = run_uninstall(self.home)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.text(), FOREIGN)


if __name__ == "__main__":
    unittest.main()
