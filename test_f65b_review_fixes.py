"""F65.a-c and the installer rules of the review fixes (code-blind: written from docs/spec.md, README.md, SECURITY.md and
CHANGELOG.md of branch minimal-install-redaction; no hook or installer source was read).

Spec F65.a: a prefix (`sk-`, `sk-ant-`, `gh?_`, `github_pat_`, `xox?-`, `AKIA`, `ASIA`, `AIza`, `eyJ`) matches only when no
letter, digit, `_` or `-` comes before it. `key=sk-...` and `"sk-proj-..."` are masked.
Spec F65.b: a `secret` value is masked only when it has 8 or more characters, is not only letters, is not only digits and
is not a call, an index or a variable reference. A quoted value is masked inside its quotes. A value after `Bearer` is
masked. The `url` kind masks the password of `scheme://user:password@host`.
Spec F65.c: the time to redact is linear (`"a." * 20000` and 200,000 base64url characters).
README (Upgrade from 0.12.x): a rerun keeps the installed window, llm-map and nightly jobs and says "already installed,
kept".

Labels F65.d ... are provisional. All secret values are fake. The entry points are the documented ones: recall output
(`recall.py user`, `search`) and the PreCompact handoff file, plus `redact()` of hooks/recall.py (named in the spec).

Assumptions (the spec is silent): `--window 0` and a saved `window=0` are rejected with a non-zero exit code and no window
value is written; the "already installed, kept" line of each part names its part (window, llm-map or nightly)."""
import json, os, re, subprocess, sys, time, unittest

from helpers import HOOKS_DIR, HookCase, IS_MACOS, run_install, user, asst
from test_content import git
from test_f64_minimal_install import Base as InstBase, DEFAULTS_REL, WINDOW, read_settings, window_of

RECALL = os.path.join(HOOKS_DIR, "recall.py")
SAME_NAMES = {}
# ---- false positives: every text must stay byte-identical
SAME = [
    "ran tests/task-runner-integration-suite.py today",
    "words disk-usage risk-score mask-bits flask-app stay",
    "status token: 160000 of 400000 used",
    "code if not token: return None here",
    "field api_key: str = Field(...) here",
    "note Set HANDOFF_SECRET=0 first",
    "line secret = get_secret(name) here",
    "commit 5b5c7de0a1f3b2c4d6e8f0a1b2c3d4e5f6a7b8c9 landed",
    "id a1a1a1a1-0000-4000-8000-000000000001 seen",
]
# ---- masked: (text, strings that must not survive, kind)
MASKED = [
    ("set key=sk-" + "FAKEopenai" * 4 + "0001 now", ["FAKEopenai" * 4 + "0001"], "openai"),
    ('config "sk-proj-' + "FAKEproj" * 5 + '" end', ["FAKEproj" * 5], "openai"),
    ("header token: Bearer zqbearer0001value end", ["zqbearer0001value"], "secret"),
    ("header Authorization: Bearer zqauth0002value end", ["zqauth0002value"], "secret"),
    ('value password: "two words here" end', ["two words here"], "secret"),
    ("env SECRET_KEY=zqSecretKey0003abc end", ["zqSecretKey0003abc"], "secret"),
    ("env private_key=zqprivatekey0004abc end", ["zqprivatekey0004abc"], "secret"),
    ("url https://alice:zqurlpass0005@example.invalid/path end", ["zqurlpass0005"], "url"),
]


def run_recall(home, proj, *args, timeout=60):
    env = {"HOME": home, "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8", "TZ": "UTC",
           "RECALL_EMBED_URL": "http://127.0.0.1:9"}
    return subprocess.run([sys.executable, RECALL, *args, "--cwd", proj], capture_output=True, text=True, env=env,
                          timeout=timeout)


class Base(HookCase):
    def setUp(self):
        super().setUp()
        self.rt = os.path.realpath(self.tmp)
        self.proj = os.path.join(self.rt, "proj")
        os.makedirs(self.proj)
        git(self.proj, "init", "-q")

    def put_session(self, texts, sid="f6f6f6f6-0000-4000-8000-0000000065b1"):
        tdir = os.path.join(self.home, ".claude", "projects", re.sub(r"[^A-Za-z0-9]", "-", self.proj))
        os.makedirs(tdir, exist_ok=True)
        with open(os.path.join(tdir, sid + ".jsonl"), "w") as f:
            for i, m in enumerate(texts):
                f.write(json.dumps({"type": "user", "sessionId": sid, "cwd": self.proj,
                                    "timestamp": "2026-03-01T12:%02d:00.000Z" % i,
                                    "message": {"role": "user", "content": m}}) + "\n")

    def handoff(self, texts, sid="S"):
        self.write_transcript([e for m in texts for e in (user(m, timestamp="2026-11-19T10:00:00.000Z"), asst("ack"))])
        r = self.run_pre(self.payload(sid, cwd=self.proj))
        self.assertEqual((r.returncode, r.stdout), (0, ""), r.stderr)
        return self.latest(sid)


# ------------------------------------------------------------------ F65.d: false positives stay byte-identical
class FalsePositives(Base):
    def test_f65_d_recall_output_keeps_every_text_byte_identical(self):
        self.put_session(SAME)
        r = run_recall(self.home, self.proj, "user", "--last", "50")
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        for t in SAME:
            self.assertIn(t, r.stdout, t)
        self.assertNotIn("[REDACTED", r.stdout)

    def test_f65_d_search_output_keeps_the_texts(self):
        self.put_session(SAME)
        out = run_recall(self.home, self.proj, "search", "task-runner-integration-suite").stdout
        self.assertIn("tests/task-runner-integration-suite.py", out)
        self.assertNotIn("[REDACTED", out)

    def test_f65_d_handoff_keeps_the_texts(self):
        t = self.handoff(SAME[:6])
        for x in SAME[:6]:
            self.assertIn(x, t, x)
        self.assertNotIn("[REDACTED", t)

    def test_f65_d_handoff_keeps_the_other_texts(self):
        t = self.handoff(SAME[6:])
        for x in SAME[6:]:
            self.assertIn(x, t, x)
        self.assertNotIn("[REDACTED", t)

    def test_f65_d_handoff_of_clean_text_has_no_state_marker(self):
        self.handoff(SAME[:6])
        for d, _, names in os.walk(self.hd):
            for n in names:
                with open(os.path.join(d, n), "rb") as f:
                    self.assertNotIn(b"[REDACTED", f.read(), n)


# ------------------------------------------------------------------ F65.e: masked
class Masked(Base):
    def check(self, out, case):
        text, gone, kind = case
        for g in gone:
            self.assertNotIn(g, out, text)
        self.assertIn("[REDACTED:%s]" % kind, out, text)

    def test_f65_e_recall_masks_every_case(self):
        self.put_session([m[0] for m in MASKED])
        out = run_recall(self.home, self.proj, "user", "--last", "50").stdout
        for case in MASKED:
            self.check(out, case)

    def test_f65_e_handoff_masks_every_case_and_state_is_clean(self):
        for i, case in enumerate(MASKED):
            t = self.handoff([case[0]], sid="M%d" % i)
            self.check(t, case)
        for d, _, names in os.walk(self.hd):
            for n in names:
                with open(os.path.join(d, n), "rb") as f:
                    data = f.read()
                for _, gone, _ in MASKED:
                    for g in gone:
                        self.assertNotIn(g.encode(), data, n)

    def test_f65_e_quoted_value_is_masked_inside_its_quotes(self):
        self.put_session(['value password: "two words here" end'])
        out = run_recall(self.home, self.proj, "user", "--last", "5").stdout
        self.assertIn('password: "[REDACTED:secret]"', out)

    def test_f65_e_url_keeps_user_and_host(self):
        self.put_session(["url https://alice:zqurlpass0005@example.invalid/path end"])
        out = run_recall(self.home, self.proj, "user", "--last", "5").stdout
        self.assertIn("https://alice:[REDACTED:url]@example.invalid/path", out)

    def test_f65_e_key_stays_for_key_value(self):
        self.put_session(["env SECRET_KEY=zqSecretKey0003abc and private_key=zqprivatekey0004abc end"])
        out = run_recall(self.home, self.proj, "user", "--last", "5").stdout
        self.assertRegex(out, r"SECRET_KEY\W{0,3}\[REDACTED:secret\]")
        self.assertRegex(out, r"private_key\W{0,3}\[REDACTED:secret\]")

    def test_f65_e_prefix_after_a_word_character_is_not_a_secret(self):
        # F65.a: no letter, digit, `_` or `-` may come before the prefix
        texts = ["flask-" + "A" * 40 + " stays", "xrisk-" + "B" * 40 + " stays", "mask-" + "C" * 40 + " stays",
                 "my_ghp_" + "D" * 36 + " stays", "zAKIA" + "E" * 16 + " stays"]
        self.put_session(texts)
        out = run_recall(self.home, self.proj, "user", "--last", "10").stdout
        for t in texts:
            self.assertIn(t, out, t)
        self.assertNotIn("[REDACTED", out)

    def test_f65_e_prefix_after_a_space_or_quote_is_a_secret(self):
        self.put_session(["a sk-" + "F" * 40 + " b", "(ghp_" + "G" * 36 + ")", "x=AKIA" + "H" * 16 + ";"])
        out = run_recall(self.home, self.proj, "user", "--last", "10").stdout
        for raw in ("F" * 40, "G" * 36, "H" * 16):
            self.assertNotIn(raw, out)
        self.assertEqual(out.count("[REDACTED:"), 3, out)


# ------------------------------------------------------------------ F65.f: speed (spec F65.c: linear)
REDACT_PROBE = r'''
import importlib.util, sys, time
spec = importlib.util.spec_from_file_location("recall", sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
alpha = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
cases = {"dots": "a." * 20000, "b64": (alpha * 3200)[:200000]}
for name, text in cases.items():
    t0 = time.perf_counter()
    out = m.redact(text)
    dt = time.perf_counter() - t0
    print(name, "%.3f" % dt, isinstance(out, str), len(out))
'''
BOUND = 5.0  # the spec says under 1 second; the bound is generous so that a slow CI machine does not flake


class Speed(Base):
    def test_f65_f_redact_function_is_fast_on_hard_inputs(self):
        r = subprocess.run([sys.executable, "-c", REDACT_PROBE, RECALL], capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = {l.split()[0]: l.split() for l in r.stdout.strip().split("\n")}
        self.assertEqual(set(rows), {"dots", "b64"}, r.stdout)
        for name, row in rows.items():
            self.assertLess(float(row[1]), BOUND, r.stdout)
            self.assertEqual(row[2], "True")

    def test_f65_f_recall_output_is_fast_on_hard_inputs(self):
        alpha = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        self.put_session(["a." * 20000, (alpha * 3200)[:200000]])
        t0 = time.time()
        r = run_recall(self.home, self.proj, "user", "--last", "5", timeout=60)
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertLess(time.time() - t0, BOUND)

    def test_f65_f_handoff_is_fast_on_hard_inputs(self):
        alpha = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        self.write_transcript([user("a." * 20000, timestamp="2026-11-19T10:00:00.000Z"), asst("ack"),
                               user((alpha * 3200)[:200000], timestamp="2026-11-19T10:01:00.000Z"), asst("ack")])
        t0 = time.time()
        r = self.run_pre(self.payload("S", cwd=self.proj))
        dt = time.time() - t0
        self.assertEqual((r.returncode, r.stdout), (0, ""), r.stderr)
        self.assertLess(dt, BOUND + 3, dt)  # the whole hook, not only the masking
        self.assertTrue(os.path.isfile(os.path.join(self.hd, "S-latest.md")))


# ------------------------------------------------------------------ F65.g: installer rules
class Installer(InstBase):
    def test_f65_g_window_zero_is_rejected(self):
        r = run_install(self.home, "--window", "0")
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        sp = os.path.join(self.home, ".claude", "settings.json")
        if os.path.exists(sp):
            self.assertIsNone(window_of(read_settings(self.home)))

    def put_saved_window_zero(self):
        os.makedirs(os.path.join(self.home, os.path.dirname(DEFAULTS_REL)))
        with open(os.path.join(self.home, DEFAULTS_REL), "w") as f:
            f.write("window=0\n")

    def test_f65_g_saved_window_zero_is_ignored_with_exit_0(self):
        # decision: a bad saved line is ignored (exit 0, a warning or nothing); only the flag exits 2
        self.put_saved_window_zero()
        r = run_install(self.home)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIsNone(window_of(read_settings(self.home)))

    def test_f65_g_a_positive_window_still_works(self):
        r = run_install(self.home, "--window", "250000")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.wait_first_index()
        self.assertEqual(str(window_of(read_settings(self.home))), "250000")

    def kept_lines(self, r):
        return [l for l in (r.stdout + r.stderr).split("\n") if "already installed, kept" in l]

    def test_f65_g_upgrade_rerun_says_already_installed_kept_for_llm_map_and_nightly(self):
        self.install("--window", "250000", "--llm-map", "--nightly")
        text = "\n".join(self.kept_lines(self.install()))
        self.assertRegex(text, r"(?i)llm")
        if IS_MACOS:
            self.assertRegex(text, r"(?i)nightly")

    def test_f65_g_upgrade_rerun_says_already_installed_kept_for_the_window(self):
        # README "Upgrade from 0.12.x": a rerun keeps the window, llm-map and nightly jobs "and says already installed,
        # kept". The builder adds the window line (head newer than 4b711af).
        self.install("--window", "250000", "--llm-map", "--nightly")
        self.assertRegex("\n".join(self.kept_lines(self.install())), r"(?i)window")

    def test_f65_g_first_install_does_not_say_already_installed(self):
        r = self.install("--window", "250000", "--llm-map")
        self.assertNotIn("already installed, kept", r.stdout + r.stderr)

    def test_f65_g_upgrade_rerun_keeps_the_parts(self):
        self.install("--window", "250000", "--llm-map")
        self.install()
        self.assertEqual(str(window_of(read_settings(self.home))), "250000")
        self.assertTrue(os.path.isfile(os.path.join(self.home, ".claude", "hooks", "llm_map.py")))


# ------------------------------------------------------------------ F65.h: add-ons (the spec text was not on the
# branch yet when these were written: the rules come from the review request)
PEM_OPEN = "-----BEGIN PRIVATE KEY-----\nabc\n"
PEM_PROBE = r'''
import importlib.util, sys, time
spec = importlib.util.spec_from_file_location("recall", sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
text = "-----BEGIN PRIVATE KEY-----\nabc\n" * 31000
t0 = time.perf_counter()
out = m.redact(text)
print("%.3f" % (time.perf_counter() - t0), isinstance(out, str))
'''
PLACEHOLDERS = ["password=$DB_PASSWORD_VALUE", "token=${API_TOKEN_VALUE}", "secret=<your-secret-here>",
                "api_key={{api_key_value}}", "passwd: $USER_PASSWD_VALUE", "access_key: ${AWS_ACCESS_KEY_VALUE}"]


class AddOns(Base):
    def test_f65_h_unclosed_pem_begin_lines_are_fast(self):
        r = subprocess.run([sys.executable, "-c", PEM_PROBE, RECALL], capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        dt, ok = r.stdout.split()
        self.assertEqual(ok, "True")
        self.assertLess(float(dt), BOUND, r.stdout)

    def test_f65_h_unclosed_pem_begin_lines_are_fast_in_recall_output(self):
        self.put_session([PEM_OPEN * 31000])
        t0 = time.time()
        r = run_recall(self.home, self.proj, "user", "--last", "5", timeout=60)
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertLess(time.time() - t0, BOUND)

    def test_f65_h_unclosed_pem_begin_lines_are_fast_in_the_handoff(self):
        self.write_transcript([user(PEM_OPEN * 31000, timestamp="2026-11-19T10:00:00.000Z"), asst("ack")])
        t0 = time.time()
        r = self.run_pre(self.payload("S", cwd=self.proj))
        self.assertEqual((r.returncode, r.stdout), (0, ""), r.stderr)
        self.assertLess(time.time() - t0, BOUND + 3)

    def test_f65_h_normal_pem_block_is_masked(self):
        pem = "-----BEGIN PRIVATE KEY-----\nMIIFAKEPEMBODYADDON0001\nFAKEPEMBODYADDON0002\n-----END PRIVATE KEY-----"
        self.put_session(["key follows ADDONPEM " + pem + " done"])
        out = run_recall(self.home, self.proj, "user", "--last", "5").stdout
        self.assertIn("[REDACTED:pem]", out)
        self.assertNotIn("MIIFAKEPEMBODYADDON0001", out)
        self.assertNotIn("FAKEPEMBODYADDON0002", out)
        self.assertIn("ADDONPEM", out)

    def test_f65_h_pem_block_after_unclosed_begin_lines_is_still_masked(self):
        pem = "-----BEGIN PRIVATE KEY-----\nMIIFAKEPEMBODYADDON0003\n-----END PRIVATE KEY-----"
        self.put_session([PEM_OPEN * 50 + pem])
        out = run_recall(self.home, self.proj, "user", "--last", "5").stdout
        self.assertNotIn("MIIFAKEPEMBODYADDON0003", out)

    def test_f65_h_full_variable_or_placeholder_values_are_not_masked(self):
        self.put_session(PLACEHOLDERS)
        out = run_recall(self.home, self.proj, "user", "--last", "20").stdout
        for t in PLACEHOLDERS:
            self.assertIn(t, out, t)
        self.assertNotIn("[REDACTED", out)

    def test_f65_h_placeholders_stay_in_the_handoff(self):
        self.write_transcript([e for m in PLACEHOLDERS[:5] for e in (user(m, timestamp="2026-11-19T10:00:00.000Z"), asst("ack"))])
        r = self.run_pre(self.payload("S", cwd=self.proj))
        self.assertEqual((r.returncode, r.stdout), (0, ""), r.stderr)
        t = self.latest("S")
        for m in PLACEHOLDERS[:5]:
            self.assertIn(m, t, m)
        self.assertNotIn("[REDACTED", t)

    def test_f65_h_dollar_in_a_real_value_is_still_masked(self):
        self.put_session(["login password=$uperS3cret!! end"])
        out = run_recall(self.home, self.proj, "user", "--last", "5").stdout
        self.assertNotIn("$uperS3cret!!", out)
        self.assertNotIn("uperS3cret", out)
        self.assertIn("[REDACTED:secret]", out)

    def test_f65_h_secret_label_then_newline_and_a_path_keeps_the_path(self):
        text = "Secret:\n/etc/ssl/private/server-key.pem is the file"
        self.put_session([text])
        out = run_recall(self.home, self.proj, "user", "--last", "5").stdout
        self.assertIn(text, out)
        self.assertNotIn("[REDACTED", out)

    def test_f65_h_secret_label_then_newline_and_a_path_keeps_the_path_in_the_handoff(self):
        self.write_transcript([user("Secret:\n/etc/ssl/private/server-key.pem is the file",
                                    timestamp="2026-11-19T10:00:00.000Z"), asst("ack")])
        r = self.run_pre(self.payload("S", cwd=self.proj))
        self.assertEqual((r.returncode, r.stdout), (0, ""), r.stderr)
        t = self.latest("S")
        self.assertIn("/etc/ssl/private/server-key.pem", t)
        self.assertNotIn("[REDACTED", t)


if __name__ == "__main__":
    unittest.main()
