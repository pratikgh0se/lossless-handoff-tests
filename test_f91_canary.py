"""F91 live canary and shape census (F91.a-F91.c, F91.e, F91.f items 1-6 and 9). Code-blind: written from the F91 text,
docs/spec.md (F47, F86, F90) and this repo only. Every fixture holds unique text tokens. A privacy test checks that no
token reaches the check line, a sample file, the census output or `shapes.json`. Versions come from the VERSION file.
F91.d (mutation gate) is a product-repo check and is not tested here. Also here (deferred from F90): the end-to-end
negative control of the proof check (F90.g) and the VERSION negative control (F90.j item 7)."""
import json, os, re, shutil, signal, stat, subprocess, sys, tempfile, time, unittest

import gen_common as g
import helpers
from gen_common import redact_all, secret_samples
from helpers import (HookCase, PRE, POST, HOOKS_DIR, REPO, VERSION_FILE, PRODUCT_VERSION, HOOKS_VERSION,
                     private_state, installed_home, run_install)
from test_f45_no_silent_miss import iso, BOUNDARY
from test_f47_proof_receipts import ProofBase, BTS
from test_f86_check_advice import Fix, ADVICE

TIMEOUT = 55


def mode(p):
    return stat.S_IMODE(os.lstat(p).st_mode)


def walk_json(x):
    """Yield every value of a parsed JSON tree, and every key."""
    if isinstance(x, dict):
        for k, v in x.items():
            yield k
            yield from walk_json(v)
    elif isinstance(x, list):
        for v in x:
            yield from walk_json(v)
    else:
        yield x


def has_count(x, name, n):
    """True when some dict in the tree maps `name` to the int `n`."""
    if isinstance(x, dict):
        if x.get(name) == n and isinstance(x.get(name), int):
            return True
        return any(has_count(v, name, n) for v in x.values())
    if isinstance(x, list):
        return any(has_count(v, name, n) for v in x)
    return False


# ============================================================ F91.a check line
class ProofLine(Fix):
    def rows(self, specs):
        """specs: [(age_seconds, {check: verdict}, {check: detail})]. Writes proofs.jsonl as `--prove` writes it."""
        os.makedirs(self.hd, exist_ok=True)
        private_state(self.hd)
        with open(os.path.join(self.hd, "proofs.jsonl"), "w") as f:
            for age, checks, details in specs:
                f.write(json.dumps({"ts": iso(-age), "receipt_ts": iso(-age - 60), "sid": "S", "agent_id": None,
                                    "checks": checks, "details": details}) + "\n")

    def two_recent_one_old(self):
        self.rows([(3600, {"lossless": "pass", "delivered": "fail"}, {"delivered": "head not found"}),
                   (2 * 86400, {"right_agent": "fail", "lossless": "skip"}, {"right_agent": "line not found"}),
                   (9 * 86400, {"lossless": "fail"}, {"lossless": "old failure"}),
                   (86400, {"lossless": "pass", "delivered": "skip"}, {})])

    def test_f91_f1_counts_only_the_failures_of_the_last_7_days(self):
        self.two_recent_one_old()
        out = self.run_check()
        self.assertTrue(out.startswith("HANDOFF CHECK: "), out)
        self.assertEqual(out.rstrip("\n").count("\n"), 0, out)
        self.assertIn("proof: 2 failed checks in the last 7 days", out)
        self.assertRegex(out, r"\(latest: delivered at \S+\)")  # the newest failure is the `delivered` row
        self.assertNotRegex(out, r"latest: (right_agent|lossless)")
        self.assertIn("precompact-handoff.py --prove --days 7", out)

    def test_f91_a_it_is_a_data_problem_without_installer_advice(self):
        self.two_recent_one_old()
        out = self.run_check()
        self.assertNotIn(ADVICE, out)
        self.assertNotIn("installer", out)

    def test_f91_a_the_count_is_in_checks_not_rows(self):
        self.rows([(600, {"lossless": "fail", "right_agent": "fail", "delivered": "fail"}, {}),
                   (700, {"lossless": "pass"}, {})])
        self.assertIn("proof: 3 failed checks in the last 7 days", self.run_check())

    def test_f91_a_the_injected_startup_line_holds_the_text(self):
        self.two_recent_one_old()
        cmds = []
        for grp in json.load(open(self.settings))["hooks"]["SessionStart"]:
            if grp.get("matcher", "") in ("startup", "resume", "startup|resume"):
                cmds += [h["command"] for h in grp["hooks"] if "--check" in h.get("command", "")]
        self.assertTrue(cmds, "no SessionStart startup hook runs --check")
        bindir = os.path.join(self.tmp, "pybin")
        os.makedirs(bindir)
        os.symlink(sys.executable, os.path.join(bindir, "python3"))
        env = {"HOME": self.home, "PATH": bindir + ":/usr/bin:/bin", "LANG": "C.UTF-8"}
        for c in cmds:
            r = subprocess.run(["/bin/sh", "-c", c], input="{}", capture_output=True, text=True, env=env,
                               timeout=TIMEOUT, cwd=self.home)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("HANDOFF CHECK: ", r.stdout)
            self.assertIn("proof: 2 failed", r.stdout)

    def test_f91_a_both_texts_when_the_old_notice_also_applies(self):
        self.two_recent_one_old()
        with open(os.path.join(self.hd, "proof-report.md"), "w") as f:
            f.write("proof 7d: receipts 3 · failed 2\n")
        out = self.run_check()
        self.assertIn("proof: 2 failed checks in the last 7 days", out)
        self.assertEqual(out.rstrip("\n").count("\n"), 0, out)
        out2 = self.run_check()  # the F47.c notice is once only; the F91 text stays while the failures are recent
        self.assertNotIn("proof failed", out2)
        self.assertIn("proof: 2 failed checks in the last 7 days", out2)

    def test_f91_f2_only_pass_and_skip_rows_give_no_proof_problem(self):
        self.rows([(100, {"lossless": "pass", "delivered": "skip"}, {}),
                   (200, {"right_agent": "skip", "decisions_safe": "skip"}, {"right_agent": "no handoff"}),
                   (300, {"lossless": "skip"}, {"lossless": "timeout"})])
        for args in ((), ("--verbose",)):
            out = self.run_check(*args)
            self.assertNotRegex(out, r"proof: \d+ failed", "args %s: %s" % (args, out))
            self.assertNotIn("proof failed", out)

    def test_f91_a_failures_older_than_7_days_give_no_problem(self):
        self.rows([(8 * 86400, {"lossless": "fail"}, {}), (30 * 86400, {"delivered": "fail"}, {})])
        self.assertNotRegex(self.run_check(), r"proof: \d+ failed")

    def test_f91_a_verbose_lists_up_to_3_latest_failures_cut_and_redacted(self):
        raw, needles = [s for s in secret_samples() if len(s[0]) <= 60][0]
        names = ["lossless", "right_agent", "delivered", "decisions_safe", "lossless"]
        specs, toks = [], []
        for i in range(5):  # i = 0 is the newest
            tok = "F91D%dX%d" % (i, os.getpid())
            toks.append(tok)
            detail = tok + " " + raw + " " + "x" * 90 + " ENDMARK%d" % i
            specs.append(((i + 1) * 3600, {names[i]: "fail"}, {names[i]: detail}))
        self.rows(specs)
        out = self.run_check("--verbose")
        for i in range(3):
            self.assertIn(toks[i], out, "the 3 latest failures are listed")
            line = [l for l in out.split("\n") if toks[i] in l][0]
            self.assertIn(names[i], line, "each failure line names its check")
        for i in (3, 4):
            self.assertNotIn(toks[i], out, "only 3 failures are listed")
        self.assertNotIn("ENDMARK", out, "the detail is cut at 100 characters")
        for n in needles:
            self.assertNotIn(n, out, "the detail is redacted")

    def test_f91_b_verbose_prints_the_count_of_samples(self):
        self.two_recent_one_old()
        d = os.path.join(self.hd, "samples")
        os.makedirs(d, mode=0o700, exist_ok=True)
        os.chmod(d, 0o700)
        for k, n in ((3, 3), (4, 4)):
            while len(os.listdir(d)) < k:
                p = os.path.join(d, "2026-11-2%dT00-00-0%dZ-lossless.json" % (len(os.listdir(d)), len(os.listdir(d))))
                open(p, "w").write("{}")
                os.chmod(p, 0o600)
            out = self.run_check("--verbose")
            self.assertRegex(out, r"(?i)sample[^\n]*\b%d\b|\b%d\b[^\n]*sample" % (n, n), out)


# ============================================================ F91.b samples
def fake_recall(path_transcript, sid8, how):
    """A recall.py that finds every message but fails the check: `alter` returns other text; `rc` makes `open` exit 1
    (a hit id that does not open); `empty` makes `open` print nothing and exit 0."""
    return '''#!/usr/bin/env python3
import json, sys
T, SID8, HOW = %r, %r, %r
args = sys.argv[1:]
rows = [json.loads(l) for l in open(T) if l.strip()]
def text(r):
    c = r.get("message", {}).get("content")
    return c if isinstance(c, str) else ""
if args and args[0] == "search":
    hits = [(i + 1, r) for i, r in enumerate(rows) if args[1] in text(r)]
    for i, r in hits:
        print("%%s:%%d 2026-03-08 12:00 %%s: %%s" %% (SID8, i, r.get("type", "user"), text(r)[:150]))
    print("%%d hits shown of %%d (1 sessions searched)" %% (len(hits), len(hits)))
elif args and args[0] == "open":
    if HOW == "rc":
        sys.stderr.write("no such message\\n"); sys.exit(1)
    if HOW == "empty":
        sys.exit(0)
    line = int(args[1].split(":")[1])
    r = rows[line - 1]
    print("--- %%s:%%d 2026-03-08 12:00 %%s" %% (SID8, line, r.get("type", "user")))
    print(text(r) + " ALTERED-BY-FAKE-RECALL")
''' % (path_transcript, sid8, how)


class ProveSamples(ProofBase):
    SESS = "f91b2222-0000-4000-8000-000000000001"
    HEADTXT = "HEAD-F91-DELIVERED"

    def setUp(self):
        super().setUp()
        self.proj = os.path.join(os.path.realpath(self.tmp), "projf91")
        os.makedirs(self.proj)
        self.tp = os.path.join(self.home, ".claude", "projects", re.sub(r"[^A-Za-z0-9]", "-", self.proj),
                               self.SESS + ".jsonl")
        self.tok = "F91TOK%d" % os.getpid()
        self.msgs = ["%s-%d message about the invoice reconciliation detail %s" % (self.tok, i, "pad" * (3 * i + 1))
                     for i in range(1, 8)]
        recs = [{"type": "user", "sessionId": self.SESS, "cwd": self.proj, "timestamp": "2026-03-08T12:%02d:00.000Z" % i,
                 "message": {"role": "user", "content": m}} for i, m in enumerate(self.msgs)]
        recs.append(dict(BOUNDARY, timestamp=BTS, sessionId=self.SESS, cwd=self.proj))
        recs.append(self.attach(self.HEADTXT, "2026-03-09T12:05:00.000Z"))
        self.write_jsonl(self.tp, recs)
        self.keys = sorted(recs[0].keys())
        self.samples = os.path.join(self.hd, "samples")
        self.hooks = os.path.join(self.tmp, "hooks-fake")

    def use_fake(self, how):
        if os.path.isdir(self.hooks):
            shutil.rmtree(self.hooks)
        shutil.copytree(HOOKS_DIR, self.hooks, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        with open(os.path.join(self.hooks, "recall.py"), "w") as f:
            f.write(fake_recall(self.tp, self.SESS[:8], how))

    def run_prove(self):
        env = self.env(None, extra={"RECALL_EMBED_URL": "http://127.0.0.1:9"})
        r = subprocess.run([sys.executable, os.path.join(self.hooks, "precompact-handoff.py"), "--prove"],
                           stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env, timeout=TIMEOUT)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r

    def receipts(self, n):
        out = []
        for _ in range(n):  # a unique receipt ts each: the default ts can repeat when the clock moves between calls
            self.rn = getattr(self, "rn", 0) + 1
            self.t0 = getattr(self, "t0", time.time())  # one fixed base: iso() moves with the clock
            ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.t0 - 100000 - self.rn))
            out.append(self.receipt(self.tp, key=self.SESS, sid=self.SESS, head=self.HEADTXT, ts=ts))
        return out

    def files(self):
        return sorted(os.listdir(self.samples)) if os.path.isdir(self.samples) else []

    def test_f91_f3_a_failed_prove_run_writes_one_structure_only_sample_0600(self):
        for how in ("alter", "rc", "empty"):
            with self.subTest(how=how):
                shutil.rmtree(self.hd, ignore_errors=True)
                self.use_fake(how)
                rc = self.receipts(1)[0]
                self.run_prove()
                v = self.verdict(rc)
                self.assertEqual(v["checks"]["lossless"], "fail", v)
                fs = self.files()
                self.assertEqual(len(fs), 1, fs)
                self.assertTrue(fs[0].endswith("-lossless.json"), fs)
                p = os.path.join(self.samples, fs[0])
                self.assertEqual(mode(p), 0o600)
                self.assertEqual(mode(self.samples), 0o700)
                raw = open(p).read()
                tree = json.loads(raw)
                vals = list(walk_json(tree))
                self.assertIn("user", vals, "the record type")
                self.assertIn("lossless", vals, "the check name")
                self.assertIn("string", vals, "message.content as a string")
                self.assertTrue(any(isinstance(x, list) and x == self.keys for x in self._lists(tree)),
                                "the sorted top-level keys %s are not in %s" % (self.keys, raw[:300]))
                lens = {len(m) for m in self.msgs}
                self.assertTrue(lens & {x for x in vals if isinstance(x, int) and not isinstance(x, bool)},
                                "no text length in the sample")

    @staticmethod
    def _lists(x):
        if isinstance(x, list):
            yield x
            for v in x:
                yield from ProveSamples._lists(v)
        elif isinstance(x, dict):
            for v in x.values():
                yield from ProveSamples._lists(v)

    def test_f91_f3_the_sample_holds_no_fixture_text_id_path_or_value(self):
        for how in ("alter", "rc"):
            with self.subTest(how=how):
                shutil.rmtree(self.hd, ignore_errors=True)
                self.use_fake(how)
                self.receipts(1)
                self.run_prove()
                self.assertTrue(self.files(), "the failed run wrote no sample")
                for f in self.files():
                    raw = open(os.path.join(self.samples, f)).read()
                    for bad in (self.tok, "invoice", "reconciliation", "pad" * 3, self.SESS, self.SESS[:8], self.proj,
                                self.tmp, self.home, "2026-03", self.HEADTXT, "ALTERED"):
                        self.assertNotIn(bad, raw, "the sample holds %r" % bad)

    def test_f91_f4_55_failures_give_50_samples_and_the_oldest_go_first(self):
        self.use_fake("alter")
        self.receipts(30)
        self.run_prove()
        first = set(self.files())
        self.assertEqual(len(first), 30, first)
        time.sleep(1.2)
        self.receipts(25)
        self.run_prove()
        after = set(self.files())
        self.assertEqual(len(after), 50, sorted(after))
        removed, kept = first - after, first & after
        self.assertTrue(removed, "no old sample was deleted")
        stamp = lambda n: n.split("-")[0]  # the time part; a same-second name may carry a counter suffix
        self.assertLessEqual(max(map(stamp, removed)), min(map(stamp, kept)), "the oldest samples are deleted first")
        self.assertTrue((after - first), "the samples of the second run are kept")
        self.assertEqual(len([v for v in self.verdicts() if v["checks"].get("lossless") == "fail"]), 55)

    def test_f90_g_negative_control_a_hit_id_that_does_not_open_fails_the_proof_check(self):
        for how in ("rc", "empty"):
            with self.subTest(how=how):
                shutil.rmtree(self.hd, ignore_errors=True)
                self.use_fake(how)
                rc = self.receipts(1)[0]
                self.run_prove()
                v = self.verdict(rc)
                self.assertEqual(v["checks"]["lossless"], "fail", "the proof check passed a hit that does not open: %s" % v)
                self.assertTrue(v["details"].get("lossless"), v)


# ============================================================ F91.c shape census
class Census(HookCase):
    LEDGER_ENV = "0"
    SID = "f91c3333-0000-4000-8000-000000000001"

    def setUp(self):
        super().setUp()
        self.proj = os.path.join(os.path.realpath(self.tmp), "projc91")
        os.makedirs(self.proj)
        self.dir = os.path.join(self.home, ".claude", "projects", re.sub(r"[^A-Za-z0-9]", "-", self.proj))
        self.tok = "F91CTOK%d" % os.getpid()
        self.main = os.path.join(self.dir, self.SID + ".jsonl")
        self.sub = os.path.join(self.dir, self.SID, "subagents", "agent-f91aaaa1.jsonl")
        self.lines = self.base_lines()
        self.write(self.main, self.lines)
        self.state = self.hd

    def rec(self, kind, content, **kw):
        d = {"type": kind, "sessionId": self.SID, "cwd": self.proj, "timestamp": iso(-3600),
             "message": {"role": kind, "content": content}}
        d.update(kw)
        return d

    def base_lines(self):
        t = self.tok
        return [self.rec("user", "%s user text one" % t),
                self.rec("assistant", [{"type": "thinking", "thinking": t + " thought", "signature": "s"},
                                       {"type": "text", "text": t + " answer"},
                                       {"type": "tool_use", "id": "tu1", "name": "Read", "input": {"file_path": "/x/" + t}}]),
                self.rec("user", [{"type": "tool_result", "tool_use_id": "tu1", "content": t + " result string"}]),
                self.rec("assistant", [{"type": "tool_use", "id": "tu2", "name": "Read", "input": {"p": t}}]),
                self.rec("user", [{"type": "tool_result", "tool_use_id": "tu2",
                                   "content": [{"type": "text", "text": t + " block a"}, {"type": "text", "text": t + " b"}]}]),
                self.rec("user", "%s user text two" % t)]

    def write(self, path, recs):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            for r in recs:
                f.write((r if isinstance(r, str) else json.dumps(r)) + "\n")

    def census(self, *args):
        r = subprocess.run([sys.executable, PRE, "--shape-census", *args], input="", capture_output=True, text=True,
                           env=self.env(None), timeout=TIMEOUT, cwd=self.home)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout

    @staticmethod
    def new_lines(out):
        return [l for l in out.split("\n") if re.match(r"^\s*new (record type|key): ", l)]

    def shapes(self, name="shapes.json"):
        with open(os.path.join(self.state, name)) as f:
            return json.load(f)

    def test_f91_c_first_run_writes_the_baseline_and_counts(self):
        out = self.census()
        self.assertEqual(self.new_lines(out), [], out)
        s = self.shapes()
        self.assertTrue(os.path.isfile(os.path.join(self.state, "shapes-baseline.json")))
        vals = list(walk_json(s))
        for name in ("user", "assistant", "sessionId", "cwd", "timestamp", "message", "text", "tool_use",
                     "tool_result", "thinking", "string", "list"):
            self.assertIn(name, vals, "shapes.json lacks %r" % name)
        self.assertTrue(has_count(s, "user", 4), "4 user records in the fixture")
        self.assertTrue(has_count(s, "assistant", 2), "2 assistant records in the fixture")

    def test_f91_f5_a_new_record_type_is_printed_once(self):
        self.census()  # the baseline
        self.write(self.main, self.lines + [{"type": "x-new", "sessionId": self.SID, "timestamp": iso(-60)}])
        out = self.census()
        self.assertIn("new record type: x-new", out)
        self.assertEqual(self.new_lines(self.census()), [], "a second run with no change prints no new line")

    def test_f91_c_a_new_top_level_key_is_printed_by_name(self):
        self.census()
        self.write(self.main, self.lines + [dict(self.rec("user", "k"), xnewkey91=self.tok + "VALUE")])
        out = self.census()
        self.assertIn("new key: xnewkey91", out)
        self.assertNotIn(self.tok, out)

    def test_f91_c_a_subagent_transcript_is_scanned(self):
        self.census()
        self.write(self.sub, [{"type": "x-sub", "sessionId": self.SID, "isSidechain": True, "timestamp": iso(-60)}])
        self.assertIn("new record type: x-sub", self.census())

    def test_f91_c_days_limits_the_scan(self):
        old = os.path.join(self.dir, "f91c4444-0000-4000-8000-000000000002.jsonl")
        self.write(old, [{"type": "x-old", "sessionId": "f91c4444", "timestamp": "2026-01-01T00:00:00Z"}])
        t = time.time() - 90 * 86400
        os.utime(old, (t, t))
        out = self.census("--days", "30")
        self.assertNotIn("x-old", out)
        self.assertNotIn("x-old", list(walk_json(self.shapes())))
        out = self.census("--days", "400")
        self.assertIn("x-old", list(walk_json(self.shapes())))

    def test_f91_f6_output_and_state_files_hold_no_fixture_text(self):
        self.census()
        self.write(self.main, self.lines + [dict({"type": "x-new", "sessionId": self.SID, "cwd": self.proj,
                                                  "xnewkey91": self.tok + "VAL"},
                                                 message={"role": "user", "content": self.tok + " more text"})])
        outs = [self.census(), self.census()]
        for n in ("shapes.json", "shapes-baseline.json"):
            outs.append(open(os.path.join(self.state, n)).read())
        for o in outs:
            for bad in (self.tok, self.proj, self.SID, "user text one", "block a"):
                self.assertNotIn(bad, o)

    def test_f91_c_state_files_are_0600(self):
        self.census()
        for n in ("shapes.json", "shapes-baseline.json"):
            self.assertEqual(mode(os.path.join(self.state, n)), 0o600, n)
        self.assertEqual(mode(self.state), 0o700)

    def test_f91_c_no_model_call(self):
        self.install_shim(out="SHOULD-NOT-BE-CALLED")
        self.census()
        self.assertFalse(self.shim_invoked(), "the census called the model")


class CensusVerbose(Fix):
    def test_f91_c_check_verbose_prints_the_shapes_line_only_when_shapes_json_exists(self):
        self.assertNotIn("transcript shapes", self.run_check("--verbose"))
        d = os.path.join(self.home, ".claude", "projects", "-f91v")
        os.makedirs(d)
        with open(os.path.join(d, "f91d5555-0000-4000-8000-000000000003.jsonl"), "w") as f:
            f.write(json.dumps({"type": "user", "sessionId": "f91d5555", "timestamp": iso(-60),
                                "message": {"role": "user", "content": "F91VERBOSE text"}}) + "\n")
        env = self.env(None)
        r = subprocess.run([sys.executable, PRE, "--shape-census"], input="", capture_output=True, text=True, env=env,
                           timeout=TIMEOUT, cwd=self.home)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(os.path.isfile(os.path.join(self.hd, "shapes.json")))
        out = self.run_check("--verbose")
        m = re.search(r"(?m)^info: transcript shapes: (\d+) new since \S+", out)
        self.assertTrue(m, out)
        self.assertEqual(m.group(1), "0", "the first run made the baseline: no shape in shapes.json is outside it")
        self.assertNotIn("F91VERBOSE", out)
        with open(os.path.join(d, "f91d5555-0000-4000-8000-000000000003.jsonl"), "a") as f:
            f.write(json.dumps({"type": "x-new", "sessionId": "f91d5555", "timestamp": iso(-30)}) + "\n")
        r = subprocess.run([sys.executable, PRE, "--shape-census"], input="", capture_output=True, text=True, env=env,
                           timeout=TIMEOUT, cwd=self.home)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        m = re.search(r"(?m)^info: transcript shapes: (\d+) new since \S+", self.run_check("--verbose"))
        self.assertTrue(m)
        self.assertGreaterEqual(int(m.group(1)), 1, "x-new is in shapes.json and not in the baseline")


class NightlyCensus(unittest.TestCase):
    def test_f91_c_the_nightly_job_runs_the_census_after_the_prove_run(self):
        if not helpers.IS_MACOS:
            self.skipTest("LaunchAgent plists exist on macOS only; the spec gives no exact Linux crontab format")
        import plistlib
        home, _ = installed_home("--canary", "--nightly")
        ad = os.path.join(home, "Library", "LaunchAgents")
        found = []
        for n in sorted(os.listdir(ad)):
            if n.startswith(helpers.LABEL_PREFIX) and n.endswith(".plist"):
                with open(os.path.join(ad, n), "rb") as f:
                    args = plistlib.load(f).get("ProgramArguments", [])
                s = " ".join(args)
                if "--shape-census" in s:
                    found.append((n, s))
        self.assertTrue(found, "no nightly job runs --shape-census")
        for n, s in found:
            if "--prove" in s:
                self.assertLess(s.index("--prove"), s.index("--shape-census"), n)


# ============================================================ F91.e / F91.f item 9 and F90.j item 7
def vt(s):
    return tuple(int(x) for x in s.split("."))


class Versions(unittest.TestCase):
    def test_f91_e_the_versions_are_at_least_the_f91_release(self):
        # a floor read from VERSION, not a pinned number: a later release must not break this test
        self.assertGreaterEqual(vt(PRODUCT_VERSION), (0, 23, 0), "product version in VERSION")
        self.assertGreaterEqual(vt(HOOKS_VERSION), (1, 25, 0), "hooks version in VERSION")

    def test_f91_f9_hook_version_and_install_sh_match_the_version_file(self):
        found = 0
        for root in (HOOKS_DIR, os.path.join(HOOKS_DIR, "lossless_handoff")):
            for n in sorted(os.listdir(root)) if os.path.isdir(root) else []:
                if n.endswith(".py"):
                    for m in re.finditer(r"""(?m)^\s*HOOK_VERSION\s*=\s*["']([0-9.]+)["']""", open(os.path.join(root, n)).read()):
                        found += 1
                        self.assertEqual(m.group(1), HOOKS_VERSION, n)
        self.assertGreaterEqual(found, 3)
        home = os.path.realpath(tempfile.mkdtemp(prefix="f91v-"))
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        r = run_install(home, "--version")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(PRODUCT_VERSION, r.stdout + r.stderr)

    def test_f90_j7_a_changed_hooks_line_of_version_makes_the_smoke_check_fail(self):
        smoke = os.path.join(REPO, "tests", "smoke.sh")
        if not os.path.isfile(smoke):
            self.skipTest("no tests/smoke.sh in this tree")
        tmp = os.path.realpath(tempfile.mkdtemp(prefix="f90j7-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        copy = os.path.join(tmp, "repo")
        shutil.copytree(REPO, copy, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", "bench"))
        lines = open(VERSION_FILE).read().split("\n")
        lines = [("hooks=99.99.99" if l.startswith("hooks=") else l) for l in lines]  # only the hooks= line changes
        with open(os.path.join(copy, "VERSION"), "w") as f:
            f.write("\n".join(lines))
        home = os.path.join(tmp, "home")
        os.makedirs(home)
        env = {"HOME": home, "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8",
               "LOSSLESS_HANDOFF_NO_LAUNCHCTL": "1", "RECALL_EMBED_URL": "http://127.0.0.1:9"}
        p = subprocess.Popen(["bash", os.path.join(copy, "tests", "smoke.sh")], cwd=copy, env=env,
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                             start_new_session=True)
        end, out, rc = time.time() + TIMEOUT, "", None
        try:
            import selectors
            sel = selectors.DefaultSelector()
            sel.register(p.stdout, selectors.EVENT_READ)
            while time.time() < end:
                if sel.select(0.5):
                    chunk = os.read(p.stdout.fileno(), 65536).decode("utf-8", "replace")
                    if not chunk:
                        break
                    out += chunk
                bad = [l for l in out.split("\n") if l.strip() and not l.startswith("ok:") and "version" in l.lower()]
                if bad:
                    break
            rc = p.poll()
        finally:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            p.wait()
        failed_line = [l for l in out.split("\n") if l.strip() and not l.startswith("ok:") and "version" in l.lower()]
        self.assertTrue(failed_line or (rc not in (None, 0)),
                        "the smoke check did not fail on a changed hooks= line (rc %s, %d s): %s" % (rc, TIMEOUT, out[-400:]))


if __name__ == "__main__":
    unittest.main()
