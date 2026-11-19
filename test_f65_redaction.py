"""F65 Redaction (code-blind: written from the F65 behaviour contract; no hook source was read).

Contract: secrets are masked before text is written to the PreCompact handoff files, the latest/agent handoff copies
that the hooks write, the decisions list and recall output. Each match becomes `[REDACTED:<kind>]`:
AWS access key ids (AKIA/ASIA + 16 chars), GitHub tokens (ghp_, gho_, ghu_, ghs_, ghr_, github_pat_), Slack tokens
(xox[abprs]-), Anthropic/OpenAI style keys (sk-ant-..., sk-...), Google API keys (AIza + 35 chars), JWTs (eyJ... with
three base64url parts), PEM private key blocks, and `key=value` / `key: value` where the key name contains password,
passwd, secret, token, api_key, apikey or access_key (value masked, key kept). Text without secrets stays
byte-identical. The hooks never write the unmasked value to any state file.

Labels F65.a ... F65.k are provisional AC ids. Every secret below is an obviously fake value built to match a pattern.
The contract does not list the `<kind>` names, so the tests accept any kind name and check only the shape
`[REDACTED:<kind>]` (and that the kinds are not all the same). The value of a `key=value` match is replaced; the test
accepts any separator text between the key and the marker."""
import glob, json, os, re, shutil, subprocess, sys, unittest

from helpers import HOOKS_DIR, HookCase, user, asst
from test_content import git

RECALL = os.path.join(HOOKS_DIR, "recall.py")
MARK = r"\[REDACTED:[A-Za-z0-9_.-]+\]"
MARK_RE = re.compile(MARK)

# ---- fake secrets (each one matches its pattern and nothing real)
A36 = "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
assert len(A36) == 36
PEM = ("-----BEGIN RSA PRIVATE KEY-----\nMIIFAKEFAKEFAKEPEMBODYLINEONE0001\nFAKEPEMBODYLINETWO0002FAKE\n"
       "-----END RSA PRIVATE KEY-----")
PEM_BODY = ("MIIFAKEFAKEFAKEPEMBODYLINEONE0001", "FAKEPEMBODYLINETWO0002FAKE")
GOOGLE = "AIza" + "FAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKE" + "abc"
assert len(GOOGLE) == 39
JWT = "eyJhbGciOiJIUzI1NiJ9" + "." + "eyJzdWIiOiJmYWtlLXVzZXIifQ" + "." + "FAKESIGNATUREFAKESIGNATURE0001"

# label -> (raw secret text in the message, strings that must never survive)
SECRETS = {
    "AWSAKIA": ("AKIA" + "FAKEFAKEFAKE0001", ["AKIAFAKEFAKEFAKE0001"]),
    "AWSASIA": ("ASIA" + "FAKEFAKEFAKE0002", ["ASIAFAKEFAKEFAKE0002"]),
    "GHP": ("ghp_" + A36, [A36]),
    "GHO": ("gho_" + A36[::-1], [A36[::-1]]),
    "GHU": ("ghu_" + A36.swapcase(), [A36.swapcase()]),
    "GHS": ("ghs_" + "Z" + A36[1:], ["Z" + A36[1:]]),
    "GHR": ("ghr_" + "Y" + A36[1:], ["Y" + A36[1:]]),
    "GHPAT": ("github_pat_" + "FAKE0000000000_" + "abcdEFGH" * 5, ["FAKE0000000000_" + "abcdEFGH" * 5]),
    "SLACKB": ("xoxb-" + "123456789012-FAKEFAKEFAKE", ["123456789012-FAKEFAKEFAKE"]),
    "SLACKA": ("xoxa-" + "223456789012-FAKEFAKEFAKE", ["223456789012-FAKEFAKEFAKE"]),
    "SLACKP": ("xoxp-" + "323456789012-FAKEFAKEFAKE", ["323456789012-FAKEFAKEFAKE"]),
    "SLACKR": ("xoxr-" + "423456789012-FAKEFAKEFAKE", ["423456789012-FAKEFAKEFAKE"]),
    "SLACKS": ("xoxs-" + "523456789012-FAKEFAKEFAKE", ["523456789012-FAKEFAKEFAKE"]),
    "ANTHROPIC": ("sk-ant-" + "api03-" + "FAKE" * 10, ["api03-" + "FAKE" * 10]),
    "OPENAI": ("sk-" + "FAKEopenai" * 4 + "0001", ["FAKEopenai" * 4 + "0001"]),
    "GOOGLE": (GOOGLE, [GOOGLE]),
    "JWT": (JWT, [JWT, "FAKESIGNATUREFAKESIGNATURE0001", "eyJzdWIiOiJmYWtlLXVzZXIifQ"]),
    "PEM": (PEM, list(PEM_BODY)),
}
KV = {  # label -> (message text, value that must not survive, key that must survive)
    "KVPASSWORD": ("password=zqpassword0001", "zqpassword0001", "password"),
    "KVPASSWD": ("db_passwd: zqpasswd0002", "zqpasswd0002", "db_passwd"),
    "KVSECRET": ("client_secret=zqsecret0003", "zqsecret0003", "client_secret"),
    "KVTOKEN": ("auth_token: zqtoken0004", "zqtoken0004", "auth_token"),
    "KVAPIKEY": ("my_api_key=zqapikey0005", "zqapikey0005", "my_api_key"),
    "KVAPIKEY2": ("apikey: zqapikey0006", "zqapikey0006", "apikey"),
    "KVACCESS": ("aws_access_key=zqaccess0007", "zqaccess0007", "aws_access_key"),
}
ALL_RAW = [s for _, forms in SECRETS.values() for s in forms] + [v for _, v, _ in KV.values()]
CLEAN = [  # near misses and plain prose: must stay byte-identical
    "CLEAN1 the AKIA prefix alone and AKIASHORT are not keys",
    "CLEAN2 sk-short and ghp_short and xoxb-1 and AIzaShort stay as written",
    "CLEAN3 a password policy and a token budget are words, not secrets",
    "CLEAN4 eyJ alone, and eyJhbGci.only.two? stay as written",
    "CLEAN5 path /usr/local/bin and url https://example.com/a?b=c stay as written",
]


def message(label, text):
    return "SECRETFIXTURE-%s [[ %s ]] END-%s" % (label, text, label)


def fixture_messages(clean=True):
    out = [message(l, s) for l, (s, _) in SECRETS.items()] + [message(l, t) for l, (t, _, _) in KV.items()]
    return out + (CLEAN if clean else [])


def files_under(root):
    out = []
    for d, _, names in os.walk(root):
        for n in names:
            out.append(os.path.join(d, n))
    return sorted(out)


def leaks(root, needles=ALL_RAW):
    """(path, needle) pairs where a raw secret appears in any file under root (binary-safe)."""
    found = []
    for p in files_under(root):
        try:
            with open(p, "rb") as f:
                data = f.read()
        except OSError:
            continue
        for n in needles:
            if n.encode() in data:
                found.append((os.path.relpath(p, root), n[:24]))
    return found


class Base(HookCase):
    LEDGER_ENV = None  # decisions list enabled (merge calls go to the claude shim)

    def setUp(self):
        super().setUp()
        self.rt = os.path.realpath(self.tmp)
        self.root = os.path.join(self.rt, "repo")
        os.makedirs(self.root)
        git(self.root, "init", "-q")
        self.install_shim(out="## Goal\nplain summary text\n")
        self.set_shim("merge", out="NO CHANGES")

    def go(self, sid="S"):
        r = self.run_pre(self.payload(sid, cwd=self.root))
        self.assertEqual((r.returncode, r.stdout), (0, ""), r.stderr)

    def convo(self, msgs):
        out = []
        for i, m in enumerate(msgs):
            out.append(user(m, timestamp="2026-11-19T10:%02d:00.000Z" % i))
            out.append(asst("ack %d" % i))
        return out

    def decisions_files(self):
        return glob.glob(os.path.join(self.hd, "projects", "*", "decisions*"))


# ------------------------------------------------------------------ F65.a-F65.c: PreCompact handoff files
class Handoff(Base):
    def setUp(self):
        super().setUp()
        self.write_transcript(self.convo(fixture_messages()))
        self.go()
        self.text = self.latest()

    def test_f65_a_no_raw_secret_in_any_state_file(self):
        self.assertTrue(files_under(self.hd))
        self.assertEqual(leaks(self.hd), [])

    def test_f65_a_no_raw_secret_in_the_latest_handoff(self):
        for needle in ALL_RAW:
            self.assertNotIn(needle, self.text, needle[:24])

    def test_f65_b_every_kind_has_a_marker_in_place(self):
        for label in SECRETS:
            self.assertRegex(self.text, r"SECRETFIXTURE-%s\W*\[\[\s*%s\s*\]\]\s*END-%s" % (label, MARK, label), label)

    def test_f65_b_key_value_keeps_the_key_and_masks_the_value(self):
        for label, (_, value, key) in KV.items():
            self.assertRegex(self.text, r"SECRETFIXTURE-%s\W*\[\[\s*%s\W{0,4}%s" % (label, re.escape(key), MARK), label)
            self.assertNotIn(value, self.text)

    def test_f65_b_pem_block_is_one_marker_without_body_lines(self):
        self.assertNotIn("BEGIN RSA PRIVATE KEY", self.text.replace("[REDACTED", ""), "the PEM header survived")
        for line in PEM_BODY:
            self.assertNotIn(line, self.text)
        self.assertRegex(self.text, r"SECRETFIXTURE-PEM\W*\[\[\s*" + MARK + r"\s*\]\]\s*END-PEM")

    def test_f65_b_markers_have_the_kind_shape_and_the_kinds_differ(self):
        found = MARK_RE.findall(self.text)
        self.assertGreaterEqual(len(found), len(SECRETS) + len(KV) - 2, found)
        self.assertGreaterEqual(len(set(found)), 6, sorted(set(found)))

    def test_f65_c_text_without_secrets_stays_byte_identical(self):
        for line in CLEAN:
            self.assertIn(line, self.text, line)
        self.assertEqual(len(MARK_RE.findall("\n".join(CLEAN))), 0)


class HandoffNoSecret(Base):
    def test_f65_c_no_secret_fixture_has_no_marker_and_keeps_text(self):
        self.write_transcript(self.convo(CLEAN))
        self.go()
        t = self.latest()
        self.assertNotIn("[REDACTED", t)
        for line in CLEAN:
            self.assertIn(line, t, line)

    def test_f65_c_masking_changes_only_the_secret_lines(self):
        # same fixture with and without a secret: the clean lines are identical in both handoffs
        self.write_transcript(self.convo(CLEAN))
        self.go("A")
        self.write_transcript(self.convo(CLEAN + [message("GHP", SECRETS["GHP"][0])]))
        self.go("B")
        a, b = self.latest("A"), self.latest("B")
        for line in CLEAN:
            self.assertEqual(a.count(line), b.count(line), line)


# ------------------------------------------------------------------ F65.d: the agent handoff and the summary
class AgentAndSummary(Base):
    def test_f65_d_secret_in_the_agent_handoff_is_masked_in_latest(self):
        body = "## Goal\nSECRETFIXTURE-AGENT [[ %s ]] END-AGENT\n## Exact next step\ngo\n" % SECRETS["GHP"][0]
        self.agent_file(body, age_min=1)
        self.write_transcript(self.convo(["plain request"]))
        self.go()
        t = self.latest()
        self.assertNotIn(A36, t)
        self.assertRegex(t, r"SECRETFIXTURE-AGENT\W*\[\[\s*" + MARK + r"\s*\]\]")
        # the agent file was written by the test itself, so every OTHER file must be clean
        seeded = os.path.join(self.hd, "S-agent.md")
        self.assertEqual([x for x in leaks(self.hd, [A36]) if x[0] != os.path.relpath(seeded, self.hd)], [])

    def test_f65_d_secret_in_the_fresh_summary_is_masked(self):
        self.install_shim(out="## Goal\nSUMMARYFIX [[ %s ]] and [[ password=zqsummary0099 ]]\n" % SECRETS["GHS"][0])
        self.write_transcript(self.convo(["plain request about the summary"]))
        self.go()
        t = self.latest()
        self.assertTrue(self.shim_invoked(), "fixture: the summary model was not called")
        self.assertNotIn("Z" + A36[1:], t)
        self.assertNotIn("zqsummary0099", t)
        self.assertRegex(t, r"SUMMARYFIX")
        self.assertEqual(leaks(self.hd, ["Z" + A36[1:], "zqsummary0099"]), [])

    def test_f65_d_secret_in_a_tool_command_is_masked(self):
        from helpers import tool
        cmd = "curl -H 'X-Fix: %s' https://example.invalid/ZQTOOLFIX" % SECRETS["OPENAI"][0]
        self.write_transcript([user("run it", timestamp="2026-11-19T10:00:00.000Z"), tool("Bash", command=cmd)])
        self.go()
        self.assertEqual(leaks(self.hd, SECRETS["OPENAI"][1]), [])
        self.assertNotIn(SECRETS["OPENAI"][0], self.latest())


# ------------------------------------------------------------------ F65.e-F65.f: the decisions list
class Decisions(Base):
    DECISION = ("- D1 [2026-11-19] [rule] Use the staging key %s for all calls | why: the user said "
                "client_secret=zqdecision0042 is rotated weekly")

    def run_merge(self):
        self.set_shim("merge", out=self.DECISION % SECRETS["ANTHROPIC"][0])
        self.write_transcript(self.convo(["DECISION-FIX: use the staging key for all calls"]))
        self.go()

    def test_f65_e_decision_with_a_secret_is_masked_in_the_list(self):
        self.run_merge()
        files = [f for f in self.decisions_files() if f.endswith("decisions.md")]
        self.assertEqual(len(files), 1, self.decisions_files())
        text = open(files[0]).read()
        self.assertIn("- D1 [2026-11-19] [rule] Use the staging key ", text)
        self.assertRegex(text, r"Use the staging key " + MARK + r" for all calls")
        self.assertNotIn(SECRETS["ANTHROPIC"][1][0], text)
        self.assertNotIn("zqdecision0042", text)
        self.assertRegex(text, r"client_secret\W{0,4}" + MARK)

    def test_f65_e_no_raw_secret_in_any_decisions_file_or_backup(self):
        self.run_merge()
        self.assertEqual(leaks(self.hd, SECRETS["ANTHROPIC"][1] + ["zqdecision0042"]), [])

    def test_f65_e_decision_text_around_the_secret_is_kept(self):
        self.run_merge()
        t = self.latest()
        self.assertNotIn("zqdecision0042", t)
        self.assertNotIn(SECRETS["ANTHROPIC"][1][0], t)
        if "Project decisions" in t:
            self.assertIn("for all calls", t)

    def test_f65_f_decision_without_a_secret_is_written_as_is(self):
        line = "- D1 [2026-11-19] [rule] Keep the password policy and the token budget as they are | why: plain words"
        self.set_shim("merge", out=line)
        self.write_transcript(self.convo(["DECISION-FIX: keep the policy"]))
        self.go()
        files = [f for f in self.decisions_files() if f.endswith("decisions.md")]
        self.assertEqual(len(files), 1)
        self.assertIn(line + "\n", open(files[0]).read())
        self.assertNotIn("[REDACTED", open(files[0]).read())


# ------------------------------------------------------------------ F65.g-F65.k: recall output
class RecallMasks(Base):
    def setUp(self):
        super().setUp()
        self.proj = os.path.join(self.rt, "proj")
        os.makedirs(self.proj)
        git(self.proj, "init", "-q")
        slug = re.sub(r"[^A-Za-z0-9]", "-", self.proj)
        tdir = os.path.join(self.home, ".claude", "projects", slug)
        os.makedirs(tdir)
        sid = "f6f6f6f6-0000-4000-8000-000000000065"
        self.sid8 = sid[:8]
        lines = []
        for i, m in enumerate(fixture_messages()):
            lines.append({"type": "user", "sessionId": sid, "cwd": self.proj,
                          "timestamp": "2026-03-01T12:%02d:00.000Z" % i,
                          "message": {"role": "user", "content": m}})
        with open(os.path.join(tdir, sid + ".jsonl"), "w") as f:
            for l in lines:
                f.write(json.dumps(l) + "\n")

    def rc(self, *args, embed="http://127.0.0.1:9"):
        env = {"HOME": self.home, "PATH": self.bin, "LANG": "C.UTF-8", "TZ": "UTC",
               "RECALL_EMBED_URL": embed}
        r = subprocess.run([sys.executable, RECALL, *args, "--cwd", self.proj], capture_output=True, text=True,
                           env=env, timeout=90, cwd=self.tmp)
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout)
        return r.stdout

    def test_f65_g_search_by_a_nearby_word_masks_every_secret(self):
        out = self.rc("search", "SECRETFIXTURE", "--limit", "50")
        self.assertIn("SECRETFIXTURE-GHP", out)
        for needle in ALL_RAW:
            self.assertNotIn(needle, out, needle[:24])
        self.assertGreaterEqual(len(set(MARK_RE.findall(out))), 6, out[:500])

    def test_f65_g_search_marker_is_in_place_for_each_kind(self):
        out = self.rc("search", "SECRETFIXTURE", "--limit", "50")
        for label in ("AWSAKIA", "GHPAT", "SLACKB", "ANTHROPIC", "OPENAI", "GOOGLE", "JWT"):
            self.assertRegex(out, r"SECRETFIXTURE-%s\W*\[\[\s*%s" % (label, MARK), label)
        for label, (_, value, key) in KV.items():
            self.assertRegex(out, r"SECRETFIXTURE-%s\W*\[\[\s*%s\W{0,4}%s" % (label, re.escape(key), MARK), label)

    def test_f65_h_searching_the_secret_itself_prints_it_masked(self):
        out = self.rc("search", "FAKEFAKEFAKE0001")
        self.assertNotIn("AKIAFAKEFAKEFAKE0001", out)
        self.assertRegex(out, MARK)

    def test_f65_i_user_and_open_mask_every_secret(self):
        out = self.rc("user", "--last", "50")
        self.assertRegex(out, MARK)
        for needle in ALL_RAW:
            self.assertNotIn(needle, out, needle[:24])
        first = self.rc("search", "SECRETFIXTURE-GHP")
        m = re.search(r"^([0-9A-Za-z_-]{2,}:\d+) ", first, re.M)
        self.assertTrue(m, first)
        opened = self.rc("open", m.group(1))
        self.assertRegex(opened, MARK)
        self.assertNotIn(A36, opened)

    def test_f65_j_clean_messages_come_back_unchanged_from_recall(self):
        out = self.rc("user", "--last", "50")
        for line in CLEAN:
            self.assertIn(line, out, line)

    def test_f65_k_index_files_and_embedded_text_hold_no_raw_secret(self):
        from test_f44_recall import FakeEmbed
        fake = FakeEmbed()
        self.addCleanup(fake.stop)
        self.rc("index", embed=fake.url)
        self.rc("search", "SECRETFIXTURE", embed=fake.url)
        self.assertTrue(fake.all_texts(), "fixture: nothing was sent to the embedding server")
        sent = "\n".join(fake.all_texts())
        for needle in ALL_RAW:
            self.assertNotIn(needle, sent, needle[:24])
        self.assertRegex(sent, MARK)
        self.assertTrue(files_under(self.hd), "fixture: recall wrote no state")
        self.assertEqual(leaks(self.hd), [])


if __name__ == "__main__":
    unittest.main()
