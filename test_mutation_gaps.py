"""Gaps that the planted-bug gate (F91.d) found: F87 file modes under a permissive umask on every writer, F65 idempotent
redaction on every listed shape, F37 injected parts near the size limits. Code-blind: written from docs/spec.md and the
tests repo only. Every fixture holds unique text; every failure message names the umask, the shape or the size."""
import json, os, random, re, shutil, stat, subprocess, sys, time, unittest

import helpers
from gen_common import redact_all, tag
from helpers import HookCase, PRE, POST, HOOKS_DIR, user, private_state
from test_f45_no_silent_miss import iso, BOUNDARY
from test_f47_proof_receipts import ProofBase, BTS
from test_f65_redaction import SECRETS, KV
from test_f91_canary import fake_recall

TIMEOUT = 55
RECALL = os.path.join(HOOKS_DIR, "recall.py")


# ============================================================ F87 modes under a permissive umask on every writer
class Umask:
    def __init__(self, m):
        self.m = m

    def __enter__(self):
        self.old = os.umask(self.m)

    def __exit__(self, *a):
        os.umask(self.old)


def walk_all(root):
    out = {}
    for d, dirs, files in os.walk(root):
        for n in dirs + files:
            p = os.path.join(d, n)
            out[p] = os.lstat(p)
    return out


class ModeBattery(ProofBase):
    """Runs every hook that writes state: handoff and ledger (PreCompact), inject and receipts, an error row, reconcile,
    prove (proofs, report, claims, samples), check, shape census, and the recall index. Then every new file is 0600
    and every new folder is 0700, whatever the umask was."""
    LEDGER_ENV = None
    SID = "f87aaaaa-0000-4000-8000-000000000001"

    def setUp(self):
        super().setUp()
        self.repo = os.path.join(os.path.realpath(self.tmp), "repo87")
        os.makedirs(self.repo)
        subprocess.run(["git", "init", "-q", self.repo], check=True, capture_output=True, timeout=TIMEOUT)
        slug = re.sub(r"[^A-Za-z0-9]", "-", self.repo)
        self.tp = os.path.join(self.home, ".claude", "projects", slug, self.SID + ".jsonl")
        self.tpath = self.tp
        self.msgs = ["F87MODE-%d message about the invoice reconciliation detail %s" % (i, "pad" * (2 * i + 1))
                     for i in range(1, 8)]
        recs = [{"type": "user", "sessionId": self.SID, "cwd": self.repo, "timestamp": "2026-03-08T12:%02d:00.000Z" % i,
                 "message": {"role": "user", "content": m}} for i, m in enumerate(self.msgs)]
        recs.append(dict(BOUNDARY, timestamp=BTS, sessionId=self.SID, cwd=self.repo))
        recs.append(self.attach("HEAD-F87", "2026-03-09T12:05:00.000Z"))
        self.write_jsonl(self.tp, recs)
        self.install_shim(out="SUMMARY-F87 text of the summary")
        self.set_shim("merge", out="- D1 [2026-11-20] [rule] F87MODE rule text | why: test\n")
        self.agent_file("F87AGENT note one\nF87AGENT note two\n", sid="S", age_min=1)
        private_state(self.hd)
        self.hooks_fake = os.path.join(self.tmp, "hooks-fake")

    def sub(self, args, script=None, stdin="", cwd=None, extra=None, ok=True):
        env = self.env(None, extra=dict({"RECALL_EMBED_URL": "http://127.0.0.1:9"}, **(extra or {})))
        r = subprocess.run([sys.executable, script or PRE, *args], input=stdin, capture_output=True, text=True,
                           env=env, timeout=TIMEOUT, cwd=cwd or self.repo)
        if ok:
            self.assertEqual(r.returncode, 0, "%s %s: %s" % (script or PRE, args, r.stderr[-300:]))
        return r

    def battery(self, um):
        before = walk_all(self.home)
        with Umask(um):
            pay = self.payload("S", cwd=self.repo)
            self.assertEqual(self.run_pre(pay, fallback="0").returncode, 0)
            self.run_pre(raw="not json at all", fallback="0")  # an error row, if the hook writes one
            for k in (1, 2, 3):
                self.part_ctx(k, self.compact_payload(sid="S", transcript=self.tp))
            self.receipt(self.tp, key=self.SID, sid=self.SID, head="HEAD-F87")
            shutil.copytree(HOOKS_DIR, self.hooks_fake, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            with open(os.path.join(self.hooks_fake, "recall.py"), "w") as f:
                f.write(fake_recall(self.tp, self.SID[:8], "alter"))  # the lossless check fails: a sample is written
            self.sub(["--reconcile", "--prove"], script=os.path.join(self.hooks_fake, "precompact-handoff.py"))
            self.sub(["--check"], script=POST, stdin="")
            self.sub(["--shape-census"])
            for a in (["index"], ["map"], ["search", "F87MODE"]):
                self.sub(a, script=RECALL, ok=False)
        after = walk_all(self.home)
        skip = os.path.join(self.home, ".claude", "projects")
        new = {p: st for p, st in after.items() if p not in before and not p.startswith(skip + os.sep) and p != skip}
        self.assertTrue(new, "the hooks wrote nothing")
        names = {os.path.relpath(p, self.hd) for p in new if p.startswith(self.hd + os.sep)}
        for need in ("S-latest.md", "health.jsonl", "receipts.jsonl", "proofs.jsonl", "proof-report.md", "shapes.json"):
            self.assertIn(need, names, "umask %o: the run did not write %s" % (um, need))
        self.assertTrue([n for n in names if n.startswith("samples" + os.sep)], "umask %o: no sample file" % um)
        self.assertTrue([n for n in names if n.startswith("projects" + os.sep)], "umask %o: no ledger file" % um)
        for p, st in sorted(new.items()):
            m = stat.S_IMODE(st.st_mode)
            if stat.S_ISDIR(st.st_mode):
                self.assertEqual(m, 0o700, "umask %o: folder %s has mode %o" % (um, p, m))
            elif stat.S_ISREG(st.st_mode):
                self.assertEqual(m, 0o600, "umask %o: file %s has mode %o" % (um, p, m))

    def test_f87_every_state_writer_gives_0600_and_0700_under_umask_022(self):
        self.battery(0o022)

    def test_f87_every_state_writer_gives_0600_and_0700_under_umask_000(self):
        self.battery(0o000)


# ============================================================ F65 idempotent redaction on every listed shape
A = "abcdefghijklmnopqrstuvwxyz0123456789"
F87B = {  # the F87.b shapes that SECRETS and KV do not hold
    "STRIPE": "sk_live_" + "A1b2C3d4E5f6G7h8I9j0K1l2",
    "GITLAB": "glpat-" + "A1b2C3d4E5f6G7h8I9j0",
    "HF": "hf_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7",
    "TELEGRAM": "123456789:" + "AAFakeFakeFakeFakeFakeFakeFake1234567"[:35],
    "WEBHOOK": "https://hooks.slack.com/services/T0FAKE000/B0FAKE000/" + "FakeFakeFakeFakeFake0001",
    "COOKIE": "Cookie: sessionid=abc123def456; theme=dark99aa",
    "MYSQL": "mysql -u root -pS3cr3tPw99 db",
    "CURL": "curl -u admin:S3cr3tPw99 https://x.test",
    "PHRASE": "the password is S3cr3tPw99",
    "URLPW": "postgres://dbuser:Zq9xPassw0rd77@db.internal:5432/app",
    "BEARER": "Authorization: Bearer zqbearertoken0001abcd",
    "QUOTED": 'client_secret="zqquoted00secret9"',
    "KEYSK": "key=sk-" + "proj" * 6,
    "AUTHSK": '"sk-proj-' + "AbCd" * 8 + '"',
}


def shapes():
    out = {k: v[0] for k, v in SECRETS.items()}
    out.update({k: v[0] for k, v in KV.items()})
    out.update(F87B)
    return out


MARKERS = ["[REDACTED:aws]", "[REDACTED:github]", "[REDACTED:slack]", "[REDACTED:anthropic]", "[REDACTED:openai]",
           "[REDACTED:google]", "[REDACTED:jwt]", "[REDACTED:pem]", "[REDACTED:url]", "[REDACTED:secret]"]


class RedactIdempotent(unittest.TestCase):
    def check(self, cases, what):
        texts = [t for _, t in cases]
        once = redact_all(texts)
        twice = redact_all(once)
        for (label, src), a, b in zip(cases, once, twice):
            self.assertEqual(a, b, "%s %s: redact is not idempotent\n  input %r\n  once  %r\n  twice %r"
                             % (what, label, src[:120], a[:120], b[:120]))

    def test_f65_redact_twice_equals_redact_once_for_every_listed_shape(self):
        cases = []
        for label, raw in sorted(shapes().items()):
            cases.append((label, "IDEM1 before %s after" % raw))
            cases.append((label + "-line", "line one\n%s\nline three IDEM1" % raw))
        self.check(cases, "shape")

    def test_f65_every_listed_shape_is_masked_so_the_idempotence_test_is_not_vacuous(self):
        for label, raw in sorted(shapes().items()):
            out = redact_all(["IDEM2 %s end" % raw])[0]
            self.assertIn("[REDACTED:", out, "shape %s was not masked: %r" % (label, out))

    def test_f65_redact_twice_equals_redact_once_with_a_mask_marker_beside_a_new_secret(self):
        cases = []
        for i, (label, raw) in enumerate(sorted(shapes().items())):
            m = MARKERS[i % len(MARKERS)]
            cases.append((label + "-marker-before", "IDEM3 %s then %s" % (m, raw)))
            cases.append((label + "-marker-after", "IDEM3 %s then %s" % (raw, m)))
            cases.append((label + "-marker-both", "%s IDEM3 %s %s" % (m, raw, MARKERS[(i + 3) % len(MARKERS)])))
        self.check(cases, "marker and secret")

    def test_f65_redact_twice_equals_redact_once_for_text_with_only_a_mask_marker(self):
        cases = [("marker-%s" % m, "IDEM4 text with %s inside" % m) for m in MARKERS]
        cases += [("marker-alone-%s" % m, m) for m in MARKERS]
        cases += [("marker-twice", "IDEM4 " + " ".join(MARKERS)),
                  ("key-marker", "password=[REDACTED:secret] IDEM4"),
                  ("key-marker-quoted", 'api_key: "[REDACTED:secret]" IDEM4'),
                  ("bearer-marker", "Authorization: Bearer [REDACTED:secret] IDEM4"),
                  ("url-marker", "https://user:[REDACTED:url]@host.test/x IDEM4")]
        self.check(cases, "marker only")
        for label, t in cases:
            if label.startswith(("marker-", "marker-alone", "marker-twice")):  # no secret in it: byte-identical
                self.assertEqual(redact_all([t])[0], t, "%s: a text with only a mask marker changed" % label)

    def test_f65_redact_twice_equals_redact_once_for_all_shapes_in_one_text(self):
        text = "IDEM5 " + "\n".join(raw for _, raw in sorted(shapes().items()))
        self.check([("all", text), ("all-with-markers", " ".join(MARKERS) + "\n" + text)], "one text")


# ============================================================ F37 injected parts near the limits
HEAD1 = "Pre-compaction handoff (auto-saved):\n"
CONT = "[Handoff continues in"
WORDS = ("alpha", "bravo", "delta", "echo", "fox", "gamma", "hotel", "india", "kilo", "lima", "mike", "nova")


def build_body(length, seed):
    """Sections of 400 to 4,500 chars, whole lines, `## ` headings, exact total length. Returns (text, headings, lines)."""
    r = random.Random("f37-%s-%s" % (length, seed))
    names = ["Agent handoff", "Last user messages (oldest first)", "Summary", "Git", "Task state", "Background agents",
             "Open tasks", "Last assistant message", "Files touched", "Last Bash commands"]
    secs, total, i = [], 0, 0
    while total < length - 120:
        want = min(r.randint(400, 4500), length - total - 120 if length - total - 120 > 400 else length - total)
        lines = ["## %s %d" % (names[i % len(names)], i)]
        size = len(lines[0]) + 1
        n = 0
        while size < want:
            l = "P37L%d-%d-%d %s" % (length, i, n, " ".join(r.choice(WORDS) for _ in range(r.randint(8, 16))))
            lines.append(l)
            size += len(l) + 1
            n += 1
        secs.append(lines)
        total = sum(len("\n".join(s)) for s in secs) + (len(secs) - 1)
        i += 1
    body = "\n".join("\n".join(s) for s in secs)
    gap = length - len(body)
    if gap > 0:  # pad the last line with spaces-free filler to the exact length
        secs[-1][-1] += "x" * gap
        body = "\n".join("\n".join(s) for s in secs)
    elif gap < 0:
        secs[-1][-1] = secs[-1][-1][:gap]
        body = "\n".join("\n".join(s) for s in secs)
    assert len(body) == length, (len(body), length)
    return body


class Parts(ProofBase):
    LEDGER_ENV = "0"
    # content lengths around the content target (9,700 total, header 38 chars), the 10,000 trigger, and two to three parts
    SIZES = (9658, 9660, 9661, 9662, 9663, 9664, 9666, 9958, 9960, 9961, 9962, 9963, 9964, 9966, 9998, 9999, 10000,
             10001, 14000, 19000, 19300, 19340, 19600, 19961, 20000)

    def setUp(self):
        super().setUp()
        self.write_transcript([user("F37 an earlier message long enough to count here ok"), user("another one for the test")])

    def parts_for(self, body):
        self.put_latest(body + "\n", sid="S")
        self.put_sidecar(sid="S", status="ok", age_s=30)
        self.add_health_row("S", ts=iso(-30))
        pl = self.compact_payload(sid="S", transcript=self.tpath)
        return [self.part_ctx(k, pl) for k in (1, 2, 3)]

    def test_f37_every_part_is_under_the_hard_max_and_no_line_or_section_is_lost(self):
        for size in self.SIZES:
            for seed in (1, 2):
                with self.subTest(size=size, seed=seed):
                    t = "[size=%d seed=%d]" % (size, seed)
                    body = build_body(size, seed)
                    parts = self.parts_for(body)
                    self.assertIsNotNone(parts[0], t + " no part 1")
                    got_lines, got_heads = [], []
                    for k, ctx in enumerate(parts, 1):
                        if ctx is None:
                            self.assertTrue(all(p is None for p in parts[k:]), t + " a part after an empty part")
                            break
                        self.assertLess(len(ctx), 10000, "%s part %d is %d chars" % (t, k, len(ctx)))
                        want = HEAD1 if k == 1 else "Pre-compaction handoff (auto-saved, part %d):\n" % k
                        self.assertTrue(ctx.startswith(want), "%s part %d header: %r" % (t, k, ctx[:80]))
                        lines = ctx[len(want):].split("\n")
                        while lines and lines[-1].strip() == "":
                            lines.pop()
                        if lines and lines[-1].startswith(CONT):
                            lines.pop()
                        got_lines += [l.rstrip() for l in lines if l.strip()]
                        got_heads += [l for l in lines if l.startswith("## ")]
                    want_lines = [l.rstrip() for l in body.split("\n") if l.strip()]
                    self.assertEqual(got_heads, [l for l in want_lines if l.startswith("## ")],
                                     t + " the sections across the parts differ from the handoff, or are out of order")
                    self.assertEqual(got_lines, want_lines, t + " a content line was lost, changed or reordered")

    def test_f37_a_continuation_line_appears_only_when_content_remains(self):
        for size in self.SIZES:
            with self.subTest(size=size):
                t = "[size=%d]" % size
                parts = self.parts_for(build_body(size, 3))
                shown = [p for p in parts if p is not None]
                for k, p in enumerate(shown):
                    has = any(l.startswith(CONT) for l in p.split("\n"))
                    if k < len(shown) - 1:
                        self.assertTrue(has, "%s part %d has more content after it but no continuation line" % (t, k + 1))
                    else:
                        self.assertFalse(has, "%s the last part has a continuation line" % t)
                if len(HEAD1) + size < 10000:
                    self.assertEqual(len(shown), 1, t + " under 10,000 chars: one part only")


if __name__ == "__main__":
    unittest.main()
