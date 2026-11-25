"""F87 Safety fixes (0.20.2, hooks 1.22.2). Code-blind: written from the F87 text only.
F87.a / e.1-e.4: recall stays in the project of the session (CLAUDE_CODE_SESSION_ID). F87.b / e.5-e.8: more secret shapes.
F87.c / e.9-e.10: private state folders. F87.d / e.11-e.14: a handoff serves one compaction. F87.e.15: the version checks are in
test_f90_version.py.
Every child process gets a built environment: CLAUDE_CODE_SESSION_ID is set only where a test sets it, so the suite can run
inside a Claude session."""
import json, os, re, shutil, stat, subprocess, sys, tempfile, time, unittest

from helpers import HOOKS_DIR, HookCase, PLAIN, run_install, strip_node_tail
from test_content import git
from test_f44_recall import RECALL, slug
from test_f45_no_silent_miss import iso
from test_f47_proof_receipts import ProofBase, SID, jl
from test_f86_check_advice import Fix

SESSION_VAR = "CLAUDE_CODE_SESSION_ID"
SA = "87a00000-0000-4000-8000-00000000000a"
SB = "87b00000-0000-4000-8000-00000000000b"
TOK_A = "ZEBRAALPHATOKEN87"
TOK_B = "ZEBRABRAVOTOKEN87"


def mode(p):
    return stat.S_IMODE(os.lstat(p).st_mode)


# ------------------------------------------------------------------ F87.a: recall stays in its project
class Home(HookCase):
    def setUp(self):
        super().setUp()
        self.rt = os.path.realpath(self.tmp)
        self.home = os.path.join(self.rt, "home")
        os.makedirs(self.home, exist_ok=True)
        self.hd = os.path.join(self.home, ".local", "state", "claude-handoffs")
        self.A = os.path.join(self.rt, "projA")
        self.B = os.path.join(self.rt, "projB")
        for d in (self.A, self.B):
            os.makedirs(d)
            git(d, "init", "-q")
        self.put(self.A, SA, TOK_A)
        self.put(self.B, SB, TOK_B)

    def put(self, proj, sid, token):
        d = os.path.join(self.home, ".claude", "projects", slug(proj))
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, sid + ".jsonl"), "w") as f:
            for i, text in enumerate(("Notes about the topic %s and more words follow" % token,
                                      "A second line in this chat with other plain words here")):
                f.write(json.dumps({"type": "user", "sessionId": sid, "cwd": proj,
                                    "timestamp": "2026-03-01T12:%02d:00.000Z" % i,
                                    "message": {"role": "user", "content": text}}) + "\n")

    def rc(self, *args, cwd=None, sid=None, proc_cwd=None, stdin=None):
        a = list(args)
        if cwd:
            a += ["--cwd", cwd]
        env = {"HOME": self.home, "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8", "TZ": "UTC",
               "RECALL_EMBED_URL": "http://127.0.0.1:9"}
        if sid:
            env[SESSION_VAR] = sid
        return subprocess.run([sys.executable, RECALL, *a], capture_output=True, text=True, env=env, timeout=90,
                              cwd=proc_cwd or self.rt, input=stdin)


class RecallScope(Home):
    def test_f87_e1_search_of_another_project_with_cwd_exits_2_with_no_chat_text(self):
        r = self.rc("search", TOK_B, cwd=self.B, sid=SA)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual(r.stdout, "")
        self.assertIn("is another project", r.stderr)
        self.assertNotIn(TOK_B, r.stderr)

    def test_f87_a_the_stderr_message_names_the_other_root_and_the_home_root(self):
        r = self.rc("search", TOK_B, cwd=self.B, sid=SA)
        want = ("recall.py: %s is another project. A chat reads only its own project (%s). "
                "To read another project, run this command in a terminal." % (self.B, self.A))
        self.assertEqual(r.stderr.strip(), want)

    def test_f87_a_a_subfolder_of_another_project_is_that_project(self):
        sub = os.path.join(self.B, "sub")
        os.makedirs(sub)
        r = self.rc("search", TOK_B, cwd=sub, sid=SA)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual(r.stdout, "")
        self.assertIn("is another project", r.stderr)

    def test_f87_a_all_eight_commands_refuse_another_project(self):
        sub = {"search": ("search", TOK_B), "open": ("open", SB[:8] + ":1"), "user": ("user", "--last", "5"),
               "history": ("history", SB[:8]), "handoffs": ("handoffs",), "map": ("map",),
               "describe": ("describe", "n1"), "nodes": ("nodes",)}
        for name, args in sub.items():
            with self.subTest(command=name):
                r = self.rc(*args, cwd=self.B, sid=SA)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertEqual(r.stdout, "")
                self.assertIn("is another project", r.stderr)

    def test_f87_a_the_own_project_with_cwd_still_works(self):
        r = self.rc("search", TOK_A, cwd=self.A, sid=SA)
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertIn(TOK_A, r.stdout)

    def test_f87_e2_no_cwd_in_another_folder_uses_the_home_root(self):
        r = self.rc("search", TOK_A, sid=SA, proc_cwd=self.B)
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout)
        self.assertIn(TOK_A, r.stdout)
        r = self.rc("search", TOK_B, sid=SA, proc_cwd=self.B)
        self.assertNotIn(TOK_B, r.stdout, "the project of the current folder must not be read")

    def test_f87_a_user_without_cwd_in_another_folder_reads_the_home_root(self):
        r = self.rc("user", "--last", "5", sid=SA, proc_cwd=self.B)
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout)
        self.assertIn(TOK_A, r.stdout)
        self.assertNotIn(TOK_B, r.stdout)

    def test_f87_e3_without_the_variable_cwd_of_another_project_works(self):
        r = self.rc("search", TOK_B, cwd=self.B)
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertIn(TOK_B, r.stdout)

    def test_f87_e3_without_the_variable_no_cwd_uses_the_current_folder(self):
        r = self.rc("search", TOK_B, proc_cwd=self.B)
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertIn(TOK_B, r.stdout)

    def test_f87_a_a_variable_with_no_transcript_works_as_before(self):
        r = self.rc("search", TOK_B, cwd=self.B, sid="87c00000-0000-4000-8000-00000000000c")
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertIn(TOK_B, r.stdout)

    def test_f87_e4_index_of_another_project_works_with_the_variable(self):
        r = self.rc("index", cwd=self.B, sid=SA)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("is another project", r.stderr)

    def test_f87_e4_session_end_works_with_the_variable(self):
        payload = json.dumps({"session_id": "x", "cwd": self.B, "hook_event_name": "SessionEnd"})
        r = self.rc("session-end", sid=SA, stdin=payload)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))


# ------------------------------------------------------------------ F87.b: more secret shapes
def build_samples():
    """(text, [parts that must go], kind). The fake secrets are built here so no scanner sees one whole in the file."""
    stripe = "sk_" + "live_" + "A1b2C3d4E5f6G7h8i9"
    gitlab = "glpat" + "-" + "abcDEF123_-xyz456789ab"
    hf = "hf" + "_" + "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"
    tg = "123456789" + ":AA" + "abcdefghijklmnopqrstuvwxyzABCDEFG"[:33]
    hook = "T0123ABCD/B0123ABCD/" + "xyzXYZ0123456789abcd1234"
    return [
        ("my key is " + stripe + " end", [stripe], "stripe"),
        ("token " + gitlab + " end", [gitlab], "gitlab"),
        ("login " + hf + " end", [hf], "huggingface"),
        ("bot " + tg + " end", [tg], "telegram"),
        ("post to https://hooks.slack.com/services/" + hook + " now", [hook], "slack"),
        ("Cookie: sessionid=abc123def456; theme=dark99aa", ["abc123def456", "dark99aa"], "cookie"),
        ("mysql -u root -pS3cr3tPw99 db", ["S3cr3tPw99"], "cli"),
        ("curl -u admin:S3cr3tPw99 https://x.test", ["S3cr3tPw99"], "cli"),
        ("the password is S3cr3tPw99", ["S3cr3tPw99"], "secret"),
    ]


SAME = ["mkdir -p/tmp/abc123", "docker run -p8080:80 x", "ssh -p2222 host", "the password is required",
        "commit 3f786850e387550fdab836ed7e6dc881de23001b"]

PROBE = r'''
import importlib.util, json, sys
mode, hooks, recall = sys.argv[1], sys.argv[2], sys.argv[3]
if mode == "recall":
    spec = importlib.util.spec_from_file_location("recall", recall)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
else:
    # the copy is a code fragment of the hooks package: it is run with the standard modules in its namespace
    import os, re
    ns = {"re": re, "os": os, "sys": sys, "json": json, "__name__": "redaction_copy"}
    with open(os.path.join(hooks, "lossless_handoff", "redaction.py")) as f:
        exec(compile(f.read(), "redaction.py", "exec"), ns)
    class m:
        redact = staticmethod(ns["redact"])
texts = json.load(sys.stdin)
once = [m.redact(t) for t in texts]
twice = [m.redact(o) for o in once]
print(json.dumps({"once": once, "twice": twice}))
'''

SPEED = r'''
import importlib.util, sys, time
spec = importlib.util.spec_from_file_location("recall", sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
alpha = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
cases = {"prose": ("The quick brown fox jumps over the lazy dog 12345. " * 30000)[:1000000],
         "b64": (alpha * 20000)[:1000000]}
for name, text in cases.items():
    t0 = time.perf_counter()
    out = m.redact(text)
    print(name, "%.3f" % (time.perf_counter() - t0), isinstance(out, str))
'''


def child_env():
    e = {"HOME": tempfile.gettempdir(), "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8"}
    return e


def probe(mode, texts):
    r = subprocess.run([sys.executable, "-c", PROBE, mode, HOOKS_DIR, RECALL], input=json.dumps(texts),
                       capture_output=True, text=True, env=child_env(), timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout)


class Redact(unittest.TestCase):
    def test_f87_e5_each_sample_loses_its_secret_and_gets_its_kind(self):
        samples = build_samples()
        outs = probe("recall", [s[0] for s in samples])["once"]
        for (text, parts, kind), out in zip(samples, outs):
            with self.subTest(kind=kind, text=text[:30]):
                for part in parts:
                    self.assertNotIn(part, out)
                self.assertIn("[REDACTED:%s]" % kind, out)

    def test_f87_e5_the_slack_host_stays(self):
        text = build_samples()[4][0]
        out = probe("recall", [text])["once"][0]
        self.assertIn("https://hooks.slack.com/services/", out)

    def test_f87_b_slack_workflows_and_triggers_paths_are_masked(self):
        tail = "T0123ABCD/B0123ABCD/xyzXYZ0123456789abcd1234"
        texts = ["x https://hooks.slack.com/workflows/" + tail + " y", "x https://hooks.slack.com/triggers/" + tail + " y"]
        for out in probe("recall", texts)["once"]:
            self.assertNotIn(tail, out)
            self.assertIn("[REDACTED:slack]", out)
            self.assertIn("https://hooks.slack.com/", out)

    def test_f87_b_the_other_stripe_and_gitlab_prefixes_and_the_cli_forms_are_masked(self):
        body = "A1b2C3d4E5f6G7h8"
        stripe = [p + body for p in ("sk_test_", "rk_live_", "rk_test_", "pk_live_", "pk_test_")]
        stripe.append("whsec_" + "A1b2C3d4E5f6G7h8i9J0k1L2")
        gl = [p + "abcDEF123xyz456789ab" for p in ("gldt-", "glrt-", "glcbt-", "glptt-")]
        texts = ["k " + s + " e" for s in stripe] + ["k " + g + " e" for g in gl]
        texts += ["mysqldump -u root -pS3cr3tPw99 db", "mysqladmin -u root -pS3cr3tPw99 ping",
                  "mariadb -u root -pS3cr3tPw99", "curl --user admin:S3cr3tPw99 https://x.test",
                  "the password was S3cr3tPw99", "the passphrase is S3cr3tPw99", "the passwd is S3cr3tPw99",
                  "the passcode is S3cr3tPw99", "Set-Cookie: sid=abc123def456; Path=/"]
        outs = probe("recall", texts)["once"]
        for text, out in zip(texts, outs):
            with self.subTest(text=text):
                self.assertIn("[REDACTED:", out)
                self.assertNotIn("S3cr3tPw99", out)
                self.assertNotIn("abc123def456", out)
                self.assertNotIn(text.split()[1], out) if text.startswith("k ") else None

    def test_f87_b_short_keys_stay(self):
        texts = ["key sk_live_short1 end", "id hf_short1 end", "token glpat-short end", "wh whsec_short end"]
        self.assertEqual(probe("recall", texts)["once"], texts)

    def test_f87_e6_false_positives_come_back_unchanged(self):
        self.assertEqual(probe("recall", SAME)["once"], SAME)

    def test_f87_e7_redact_is_idempotent_for_each_sample(self):
        d = probe("recall", [s[0] for s in build_samples()])
        self.assertEqual(d["once"], d["twice"])

    def test_f87_e7_the_fallback_copy_gives_the_same_output_as_recall(self):
        texts = [s[0] for s in build_samples()] + SAME
        self.assertEqual(probe("fallback", texts)["once"], probe("recall", texts)["once"])

    def test_f87_e7_the_fallback_copy_is_idempotent_and_masks_each_sample(self):
        samples = build_samples()
        d = probe("fallback", [s[0] for s in samples])
        self.assertEqual(d["once"], d["twice"])
        for (text, parts, kind), out in zip(samples, d["once"]):
            for part in parts:
                self.assertNotIn(part, out)
            self.assertIn("[REDACTED:%s]" % kind, out)

    def test_f87_e8_a_million_characters_without_a_secret_take_under_2_seconds(self):
        r = subprocess.run([sys.executable, "-c", SPEED, RECALL], capture_output=True, text=True, env=child_env(),
                           timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = [l.split() for l in r.stdout.strip().split("\n")]
        self.assertEqual({x[0] for x in rows}, {"prose", "b64"}, r.stdout)
        for name, secs, ok in rows:
            self.assertEqual(ok, "True")
            self.assertLess(float(secs), 2.0, name)


# ------------------------------------------------------------------ F87.c: private folders
class Umask:
    def __init__(self, m):
        self.m = m

    def __enter__(self):
        self.old = os.umask(self.m)

    def __exit__(self, *a):
        os.umask(self.old)


class Install(unittest.TestCase):
    def test_f87_e9_the_installer_sets_0700_on_folders_and_0600_on_files(self):
        home = os.path.realpath(tempfile.mkdtemp(prefix="f87i-"))
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        sd = os.path.join(home, ".local", "state", "claude-handoffs")
        dirs = [sd, os.path.join(sd, "projects"), os.path.join(sd, "projects", "x"), os.path.join(sd, "projects", "x", "deep"),
                os.path.join(sd, "recall")]
        files = []
        for d in dirs:
            os.makedirs(d, exist_ok=True)
        for d in dirs:
            f = os.path.join(d, "f.txt")
            with open(f, "w") as fh:
                fh.write("x\n")
            os.chmod(f, 0o644)
            files.append(f)
        for d in dirs:
            os.chmod(d, 0o755)
        r = run_install(home, "--no-nightly")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for d in dirs:
            self.assertEqual(mode(d), 0o700, d)
        for f in files:
            self.assertEqual(mode(f), 0o600, f)

    def test_f87_c_a_hook_that_creates_the_state_folder_creates_it_with_0700(self):
        t = HookCase("run")
        t.setUp()
        self.addCleanup(t.tearDown) if hasattr(t, "tearDown") else None
        self.addCleanup(shutil.rmtree, t.tmp, ignore_errors=True)
        t.write_transcript([{"type": "user", "timestamp": "2026-11-19T10:00:00.000Z",
                             "message": {"role": "user", "content": "Please do the thing with the planner module now"}}])
        self.assertFalse(os.path.exists(t.hd))
        with Umask(0o000):
            r = t.run_pre(t.payload("S", cwd=t.tmp))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.isdir(t.hd))
        self.assertEqual(mode(t.hd), 0o700)
        for d, dirs, _ in os.walk(t.hd):
            for n in dirs:
                self.assertEqual(mode(os.path.join(d, n)), 0o700, n)

    def test_f87_c_recall_creates_its_state_folders_with_0700(self):
        h = Home("run")
        h.setUp()
        self.addCleanup(shutil.rmtree, h.tmp, ignore_errors=True)
        self.assertFalse(os.path.exists(h.hd))
        with Umask(0o000):
            r = h.rc("index", cwd=h.A)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        if not os.path.isdir(h.hd):
            self.skipTest("recall wrote no state folder")
        self.assertEqual(mode(h.hd), 0o700)
        for d, dirs, _ in os.walk(h.hd):
            for n in dirs:
                self.assertEqual(mode(os.path.join(d, n)), 0o700, n)


class CheckModes(Fix):
    OPEN = "state folder is open to other users"

    def test_f87_e10_a_state_folder_with_mode_0755_is_reported(self):
        os.makedirs(os.path.join(self.hd, "projects"), exist_ok=True)
        os.chmod(self.hd, 0o755)
        os.chmod(os.path.join(self.hd, "projects"), 0o700)
        out = self.run_check()
        self.assertIn(self.OPEN, out)
        self.assertIn(self.hd, out)

    def test_f87_e10_a_state_folder_with_mode_0700_is_not_reported(self):
        os.makedirs(os.path.join(self.hd, "projects"), exist_ok=True)
        os.chmod(self.hd, 0o700)
        os.chmod(os.path.join(self.hd, "projects"), 0o700)
        out = self.run_check()
        self.assertNotIn(self.OPEN, out)

    def test_f87_c_an_open_projects_folder_is_reported(self):
        proj = os.path.join(self.hd, "projects")
        os.makedirs(proj, exist_ok=True)
        os.chmod(self.hd, 0o700)
        os.chmod(proj, 0o755)
        out = self.run_check()
        self.assertIn(self.OPEN, out)
        self.assertIn(proj, out)

    def test_f87_c_a_group_bit_alone_is_reported_and_file_modes_do_not_matter(self):
        os.makedirs(os.path.join(self.hd, "projects"), exist_ok=True)
        os.chmod(self.hd, 0o710)
        os.chmod(os.path.join(self.hd, "projects"), 0o700)
        self.assertIn(self.OPEN, self.run_check())

    def test_f87_c_open_file_modes_alone_are_not_reported(self):
        os.makedirs(os.path.join(self.hd, "projects"), exist_ok=True)
        os.chmod(self.hd, 0o700)
        os.chmod(os.path.join(self.hd, "projects"), 0o700)
        f = os.path.join(self.hd, "health.jsonl")
        open(f, "w").write("")
        os.chmod(f, 0o644)
        self.assertNotIn(self.OPEN, self.run_check())


# ------------------------------------------------------------------ F87.d: a handoff serves one compaction
T1 = "HANDOFF-TOKEN-T1-87"
STALE_LINE = "handoff not refreshed for this compaction"


class OneCompaction(ProofBase):
    def setUp(self):
        super().setUp()
        self.install_shim(out="SHOULD-NOT-BE-CALLED")
        self.rpath = os.path.join(self.hd, "receipts.jsonl")

    def fixture(self, body=None):
        self.put_latest(body or (T1 + "\n"), sid=SID)
        path = self.put_sidecar(sid=SID, status="ok", age_s=30)
        self.add_health_row(SID, ts=iso(-30))
        self.hts = json.load(open(path))["ts"]
        return self.hts

    def missing(self):
        return self.compact_payload(transcript=os.path.join(self.tmp, "nope.jsonl"))

    def long_body(self):
        lines = [T1]
        for s in range(3):
            lines.append("## Section %d" % s)
            lines += ["line %d of section %d with some plain words about the work" % (i, s) + " x" * 20 for i in range(75)]
        body = "\n".join(lines) + "\n"
        self.assertGreater(len(body), 17000)
        return body

    def test_f87_e11_a_handoff_used_by_an_earlier_compaction_is_degraded(self):
        hts = self.fixture()
        self.receipt(self.tpath, ts=iso(-65), health_ts=hts)
        ctx = self.part_ctx(1, self.missing())
        self.assertTrue(ctx.startswith("HANDOFF DEGRADED:"), ctx[:300])
        self.assertIn(STALE_LINE, ctx.split("\n")[0])

    def test_f87_d_a_used_handoff_runs_the_recovery_first(self):
        hts = self.fixture()
        self.boundary_transcript()
        self.receipt(self.tpath, ts=iso(-65), health_ts=hts)
        pl = self.compact_payload()
        ctx = self.part_ctx(1, pl)
        self.assertTrue(ctx.startswith("HANDOFF RECOVERED:"), ctx[:300])
        self.assertNotIn(STALE_LINE, ctx.split("\n")[0])
        self.assertIsNone(self.part_ctx(2, pl))
        self.assertIsNone(self.part_ctx(3, pl))

    def test_f87_d_the_receipt_must_have_the_same_key(self):
        hts = self.fixture()
        self.receipt(self.tpath, key="other-key-87", ts=iso(-65), health_ts=hts)
        ctx = self.part_ctx(1, self.missing())
        self.assertNotIn("DEGRADED", ctx)
        self.assertIn(T1, ctx)

    def test_f87_d_the_receipt_must_have_the_same_health_ts(self):
        self.fixture()
        self.receipt(self.tpath, ts=iso(-65), health_ts=iso(-4000))
        ctx = self.part_ctx(1, self.missing())
        self.assertNotIn("DEGRADED", ctx)
        self.assertIn(T1, ctx)

    def test_f87_d_a_receipt_row_beyond_the_last_256_kib_is_not_read(self):
        hts = self.fixture()
        self.receipt(self.tpath, ts=iso(-65), health_ts=hts)
        filler = json.dumps({"ts": iso(-200), "sid": "f", "agent_id": None, "key": "filler-87", "health_ts": iso(-9999),
                             "pad": "p" * 900}) + "\n"
        with open(self.rpath, "a") as f:
            f.write(filler * 400)
        self.assertGreater(os.path.getsize(self.rpath), 300 * 1024)
        ctx = self.part_ctx(1, self.missing())
        self.assertNotIn("DEGRADED", ctx)
        self.assertIn(T1, ctx)

    def test_f87_d_an_unreadable_receipts_file_changes_nothing(self):
        self.fixture()
        os.makedirs(self.rpath)  # a folder where the file should be
        r = self.run_post(self.missing(), args=("--part", "1"))
        self.assertEqual(r.returncode, 0, r.stderr)
        ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(strip_node_tail(ctx), PLAIN + T1)

    def test_f87_e12_a_receipt_10_seconds_old_gives_the_handoff_and_all_parts(self):
        hts = self.fixture(self.long_body())
        self.receipt(self.tpath, ts=iso(-10), health_ts=hts)
        pl = self.missing()
        p1, p2, p3 = (self.part_ctx(k, pl) for k in (1, 2, 3))
        self.assertTrue(p1.startswith(PLAIN), p1[:200])
        self.assertIn(T1, p1)
        self.assertNotIn("DEGRADED", p1)
        self.assertNotIn(STALE_LINE, p1)
        self.assertIsNotNone(p2)
        self.assertIsNotNone(p3)
        self.assertIn("part 2", p2.split("\n")[0])
        self.assertIn("part 3", p3.split("\n")[0])

    def test_f87_e12_a_short_handoff_with_a_receipt_10_seconds_old_has_no_warning(self):
        hts = self.fixture()
        self.receipt(self.tpath, ts=iso(-10), health_ts=hts)
        ctx = self.part_ctx(1, self.missing())
        self.assertEqual(strip_node_tail(ctx), PLAIN + T1)

    def test_f87_e13_a_receipt_row_with_no_health_ts_never_makes_a_handoff_used(self):
        self.fixture()
        self.receipt(self.tpath, ts=iso(-65))
        ctx = self.part_ctx(1, self.missing())
        self.assertEqual(strip_node_tail(ctx), PLAIN + T1)

    def test_f87_e14_a_normal_part_1_run_writes_health_ts_equal_to_the_health_ts(self):
        hts = self.fixture()
        self.boundary_transcript()
        ctx = self.part_ctx(1, self.compact_payload())
        self.assertEqual(strip_node_tail(ctx), PLAIN + T1)
        rows = jl(self.rpath)
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(rows[0]["health_ts"], hts)
        self.assertEqual(rows[0]["key"], SID)

    def test_f87_d_the_same_handoff_is_not_served_twice_as_current(self):
        self.fixture()
        self.boundary_transcript()
        first = self.part_ctx(1, self.compact_payload())
        self.assertEqual(strip_node_tail(first), PLAIN + T1)
        rows = jl(self.rpath)
        rows[0]["ts"] = iso(-65)  # the first compaction was more than 60 seconds ago
        with open(self.rpath, "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        second = self.part_ctx(1, self.compact_payload())
        self.assertTrue(second.startswith(("HANDOFF RECOVERED:", "HANDOFF DEGRADED:")), second[:200])
        self.assertFalse(second.startswith(PLAIN), second[:200])


if __name__ == "__main__":
    unittest.main()
