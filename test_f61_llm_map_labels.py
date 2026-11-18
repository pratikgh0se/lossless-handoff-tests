"""F61 llm_map: ACs 281-286 of docs/spec.md. Code-blind: written from the spec only.
The fake `claude` (a Python script set by LLM_MAP_CLAUDE) logs the item numbers of each call.
It answers by mode (env FAKE_MODE):
  parity   : "even" or "odd" by item number (default)
  fixed    : the value in FAKE_VALUES (a "|" list) by item number, item n gets value (n-1) mod len
  fixed1   : like fixed, but the values apply only to items 1..len; later items get FAKE_REST
Every run uses a temp HOME; the network is never used."""
import json, os, re, shutil, subprocess, sys, tempfile, time, unittest

from helpers import HOOKS_DIR, run_install

LLM_MAP = os.path.join(HOOKS_DIR, "llm_map.py")

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
    f.write(json.dumps({"argv": argv, "prompt": text, "items": [int(i) for i, _ in items],
                        "size": len(items)}) + "\n")
mode = os.environ.get("FAKE_MODE", "parity")
values = os.environ.get("FAKE_VALUES", "").split("|")
rest = os.environ.get("FAKE_REST", "numeric value")
lines = []
for i, t in items:
    n = int(i)
    if mode == "fixed":
        out = values[(n - 1) % len(values)]
    elif mode == "fixed1":
        out = values[n - 1] if n <= len(values) else rest
    else:
        out = "even" if n % 2 == 0 else "odd"
    lines.append(json.dumps({"i": n, "out": out}))
print(json.dumps({"type": "result", "is_error": False, "result": "\n".join(lines),
                  "total_cost_usd": 0.01}))
'''


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="f61-"))
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


class Defaults(Base):
    def test_ac281_default_batch_is_100(self):
        src = self.items_file(250)
        r = self.run_map(["--in", src, "--prompt", "p", "--out", self.out])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        sizes = sorted(c["size"] for c in self.calls())
        self.assertEqual(sizes, [50, 100, 100])
        self.assertIn("250 items, 250 ok, 0 failed, 3 batches", self.last_line(r))
        self.assertEqual([x["i"] for x in self.rows()], list(range(1, 251)))

    def test_ac281_default_jobs_is_8(self):
        # With --batch 10 and 80 items, 8 batches can all run together at the default.
        # Each fake call waits at a barrier file; the run ends only if 8 calls run at once.
        barrier = os.path.join(self.tmp, "barrier")
        os.makedirs(barrier)
        fake2 = os.path.join(self.tmp, "fakebin", "fake-claude-wait")
        with open(fake2, "w") as f:
            f.write(FAKE.replace("PYTHON", sys.executable, 1).replace(
                "mode = os.environ.get",
                "import time, uuid\n"
                "b = os.environ['FAKE_BARRIER']\n"
                "open(os.path.join(b, uuid.uuid4().hex), 'w').close()\n"
                "t0 = time.time()\n"
                "while len(os.listdir(b)) < 8 and time.time() - t0 < 15:\n"
                "    time.sleep(0.05)\n"
                "mode = os.environ.get", 1))
        os.chmod(fake2, 0o755)
        src = self.items_file(80)
        t0 = time.time()
        r = self.run_map(["--in", src, "--prompt", "p", "--out", self.out, "--batch", "10"],
                         {"LLM_MAP_CLAUDE": fake2, "FAKE_BARRIER": barrier})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(os.listdir(barrier)), 8)
        # with fewer than 8 jobs, the first calls wait 15 s at the barrier
        self.assertLess(time.time() - t0, 10, "8 batches must run at the same time by default")


class Labels(Base):
    LABELS = "numeric value|human being|location"

    def test_ac282_label_mapping_and_second_try(self):
        src = self.items_file(4)
        r = self.run_map(["--in", src, "--prompt", "p", "--out", self.out, "--labels", self.LABELS],
                         {"FAKE_MODE": "fixed1", "FAKE_VALUES": "numeric|Human Being|location|1790",
                          "FAKE_REST": "1790"})
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        rows = self.rows()
        self.assertEqual([x["out"] for x in rows[:3]], ["numeric value", "human being", "location"])
        for x in rows[:3]:
            self.assertNotIn("error", x)
        self.assertIsNone(rows[3]["out"])
        self.assertTrue(rows[3]["error"].startswith("label:"), rows[3])
        self.assertIn("1790", rows[3]["error"])
        self.assertIn("1 failed", self.last_line(r))
        self.assertIn("3 ok", self.last_line(r))
        self.assertEqual(sum(1 for c in self.calls() if 4 in c["items"]), 2, "item 4 is sent once more")
        self.assertEqual(sum(1 for c in self.calls() if 1 in c["items"]), 1, "valid items are not resent")

    def test_ac282_prompt_lists_the_labels(self):
        src = self.items_file(2)
        r = self.run_map(["--in", src, "--prompt", "p", "--out", self.out, "--labels", self.LABELS],
                         {"FAKE_MODE": "fixed", "FAKE_VALUES": "location"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        p = self.calls()[0]["prompt"]
        for lab in ("numeric value", "human being", "location"):
            self.assertIn(lab, p)

    def test_ac282_second_try_can_succeed(self):
        # the first reply for item 2 is invalid; the retry reply is valid (a flag file flips the answer)
        fake2 = os.path.join(self.tmp, "fakebin", "fake-claude-flip")
        with open(fake2, "w") as f:
            f.write(FAKE.replace("PYTHON", sys.executable, 1).replace(
                "mode = os.environ.get",
                "seen = log + '.seen'\n"
                "mode = os.environ.get", 1).replace(
                "        out = \"even\" if n % 2 == 0 else \"odd\"",
                "        out = \"even\" if n % 2 == 0 else \"odd\"\n"
                "    if n == 2:\n"
                "        try:\n"
                "            os.close(os.open(seen, os.O_CREAT | os.O_EXCL | os.O_WRONLY)); out = '42'\n"
                "        except FileExistsError:\n"
                "            out = 'even'", 1))
        os.chmod(fake2, 0o755)
        src = self.items_file(3)
        r = self.run_map(["--in", src, "--prompt", "p", "--out", self.out, "--labels", "even|odd"],
                         {"LLM_MAP_CLAUDE": fake2})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        rows = self.rows()
        self.assertEqual(rows[1]["out"], "even")
        self.assertNotIn("error", rows[1])
        self.assertEqual(sum(1 for c in self.calls() if 2 in c["items"]), 2)

    def test_ac282_prefix_of_one_label_maps(self):
        src = self.items_file(2)
        r = self.run_map(["--in", src, "--prompt", "p", "--out", self.out, "--labels", "human being|location"],
                         {"FAKE_MODE": "fixed", "FAKE_VALUES": "human|numeric"})
        # "human" is a prefix of exactly one label; "numeric" matches no label.
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        rows = self.rows()
        self.assertEqual(rows[0]["out"], "human being")
        self.assertIsNone(rows[1]["out"])
        self.assertTrue(rows[1]["error"].startswith("label:"))

    def test_ac282_label_is_prefix_of_reply(self):
        src = self.items_file(1)
        r = self.run_map(["--in", src, "--prompt", "p", "--out", self.out, "--labels", "location|numeric value"],
                         {"FAKE_MODE": "fixed", "FAKE_VALUES": "Location of the city"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.rows()[0]["out"], "location")

    def test_ac282_labels_trimmed_and_canonical_text_kept(self):
        src = self.items_file(2)
        r = self.run_map(["--in", src, "--prompt", "p", "--out", self.out, "--labels", " Even | Odd "],
                         {"FAKE_MODE": "parity"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual([x["out"] for x in self.rows()], ["Odd", "Even"])

    def test_ac282_error_reply_cut_to_40_characters(self):
        src = self.items_file(1)
        long = "x" * 80
        r = self.run_map(["--in", src, "--prompt", "p", "--out", self.out, "--labels", "even|odd"],
                         {"FAKE_MODE": "fixed", "FAKE_VALUES": long})
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        err = self.rows()[0]["error"]
        self.assertTrue(err.startswith("label:"), err)
        self.assertIn("x" * 40, err)
        self.assertNotIn("x" * 41, err)

    def test_ac283_prefix_of_two_labels_is_invalid(self):
        src = self.items_file(2)
        r = self.run_map(["--in", src, "--prompt", "p", "--out", self.out, "--labels", "human being|history"],
                         {"FAKE_MODE": "fixed", "FAKE_VALUES": "h"})
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        for x in self.rows():
            self.assertIsNone(x["out"])
            self.assertTrue(x["error"].startswith("label:"), x)
        self.assertIn("2 failed", self.last_line(r))
        self.assertEqual(sum(1 for c in self.calls() if 1 in c["items"]), 2, "sent once more")

    def test_ac284_one_label_is_usage_error(self):
        src = self.items_file(3)
        r = self.run_map(["--in", src, "--prompt", "p", "--out", self.out, "--labels", "a"])
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertTrue(r.stderr.strip())
        self.assertFalse(os.path.exists(self.out))
        self.assertEqual(self.calls(), [])

    def test_ac284_labels_with_json_out_is_usage_error(self):
        src = self.items_file(3)
        r = self.run_map(["--in", src, "--prompt", "p", "--out", self.out, "--labels", "a|b", "--json-out"])
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertTrue(r.stderr.strip())
        self.assertFalse(os.path.exists(self.out))
        self.assertEqual(self.calls(), [])


class Progress(Base):
    def test_ac285_one_progress_line_per_batch(self):
        src = self.items_file(35)
        r = self.run_map(["--in", src, "--prompt", "p", "--out", self.out, "--batch", "10", "--jobs", "1"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        lines = re.findall(r"(?m)^llm_map: (\d+) of (\d+) items done\s*$", r.stderr)
        self.assertEqual(len(lines), 4, r.stderr)
        done = [int(a) for a, _ in lines]
        self.assertEqual(done, sorted(done))
        self.assertEqual(done[-1], 35)
        self.assertTrue(all(b == "35" for _, b in lines))
        self.assertNotIn("items done", r.stdout)
        self.assertRegex(self.last_line(r), r"^llm_map: 35 items, 35 ok, 0 failed, 4 batches, cost \$")

    def test_ac285_single_batch(self):
        src = self.items_file(5)
        r = self.run_map(["--in", src, "--prompt", "p", "--out", self.out])
        lines = re.findall(r"(?m)^llm_map: (\d+) of (\d+) items done\s*$", r.stderr)
        self.assertEqual(lines, [("5", "5")], r.stderr)


class Skill(unittest.TestCase):
    def test_ac286_installed_skill_text(self):
        tmp = os.path.realpath(tempfile.mkdtemp(prefix="f61i-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        home = os.path.join(tmp, "home")
        os.makedirs(home)
        r = run_install(home, "--no-nightly")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(os.path.join(home, ".claude", "skills", "llm-map", "SKILL.md")) as f:
            t = f.read()
        self.assertIn("--labels", t)
        self.assertIn("600000", t)
        self.assertIn("pgrep", t)
        m = re.search(r"(?ms)^---\n(.*?)\n---\n", t)
        self.assertIsNotNone(m, "frontmatter")
        desc = re.search(r"(?m)^description:(.*)$", m.group(1))
        self.assertIsNotNone(desc)
        self.assertIn("count", desc.group(1).lower())


if __name__ == "__main__":
    unittest.main()
