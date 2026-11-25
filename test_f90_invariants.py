"""F90.e invariants I1-I10 on generated input (F90.f shape matrix, seeds 1-20). Code-blind: written from the F90 text only.
Every failure message names the seed and the shape. Each test asserts a relation to the generated input."""
import json, os, re, stat, subprocess, sys, unittest

import gen_common as g
from gen_common import MATRIX, SEEDS, tag, GenHome, redact_all, parse_open, CUT, CAP_CHARS
import helpers
from helpers import HookCase, PRE, POST, CAP

CTRL = re.compile(r"[\x00-\x09\x0b-\x1f\x7f]")


class RecallInvariants(GenHome):
    def test_i1_recall_round_trip_is_byte_identical_on_the_whole_matrix(self):
        for shape in MATRIX:
            for seed in SEEDS:
                with self.subTest(seed=seed, shape=shape):
                    self.round_trip(seed, shape)

    def round_trip(self, seed, shape):
        t = tag(seed, shape)
        proj = self.project("p-%s-%s" % (seed, shape))
        tr = g.Transcript(seed, shape).build(proj)
        _, prefix = self.put(tr, proj)
        ids, got, raw = self.open_msgs(tr, prefix, proj)
        plain = [m for m in tr.msgs if m.kind in ("user", "assistant")]
        want = redact_all([m.texts[0] for m in plain])
        for m, expected in zip(plain, want):
            body = got.get(prefix + str(m.line))
            self.assertIsNotNone(body, "%s no output for %s%d" % (t, prefix, m.line))
            body = body[1]
            cut = re.search(r"\n\[cut: (\d+) more chars[^\]\n]*\]$", body)
            if len(expected) <= CAP_CHARS:
                self.assertNotIn("[cut:", body[-200:], "%s message %d cut although it fits" % (t, m.line))
                self.assertEqual(body, expected, "%s message %d is not byte-identical (len %d vs %d)"
                                 % (t, m.line, len(body), len(expected)))
            else:
                self.assertIsNotNone(cut, "%s message %d is cut without a marker" % (t, m.line))
                kept = body[:cut.start()]
                self.assertTrue(expected.startswith(kept), "%s kept part of message %d is not a prefix" % (t, m.line))
                self.assertEqual(len(kept) + int(cut.group(1)), len(expected), "%s cut count of message %d" % (t, m.line))

    def test_i2_every_block_of_a_tool_result_is_in_the_output_in_order(self):
        for shape in MATRIX:
            if "tool_blocks" not in MATRIX[shape] and "tool_str" not in MATRIX[shape]:
                continue
            for seed in SEEDS:
                with self.subTest(seed=seed, shape=shape):
                    t = tag(seed, shape)
                    proj = self.project("p-%s-%s" % (seed, shape))
                    tr = g.Transcript(seed, shape).build(proj, secrets=g.secret_samples())
                    _, prefix = self.put(tr, proj)
                    ids, got, raw = self.open_msgs(tr, prefix, proj)
                    tools = [m for m in tr.msgs if m.kind.startswith("tool")]
                    self.assertTrue(tools, t + " the generator made no tool result")
                    for m in tools:
                        body = got[prefix + str(m.line)][1]
                        pos = 0
                        cut = re.search(r"\n\[cut: (\d+) more chars[^\]\n]*\]$", body)
                        if cut:  # a stated cap cut this message: only the blocks before the cut must be there
                            body = body[:cut.start()]
                        for want in redact_all(m.texts):
                            want = want.rstrip()  # trailing white space of a block is I1's concern, not I2's
                            if cut and pos >= len(body) - 1:
                                break
                            if cut and pos + len(want) > len(body):
                                want = want[:max(0, len(body) - pos - 1)]
                                if not want:
                                    break
                            i = body.find(want, pos)
                            self.assertGreaterEqual(i, 0, "%s block missing or out of order in message %d: %r"
                                                    % (t, m.line, want[:60]))
                            pos = i + len(want)

    def test_i8_no_recall_command_prints_text_of_another_project(self):
        for seed in SEEDS:
            shape = "main-plain" if seed % 2 else "all-in-one"
            with self.subTest(seed=seed, shape=shape):
                t = tag(seed, shape)
                a, b = self.project("projA%s" % seed), self.project("projB%s" % seed)
                ta = g.Transcript(seed, shape).build(a)
                tb = g.Transcript(seed + 1000, shape).build(b)
                tb.sid = g.sid_for(seed, 1)
                _, pa = self.put(ta, a)
                _, pb = self.put(tb, b)
                # the unique token of each message of B: its first word
                toks = [m.texts[0].split()[0] for m in tb.msgs if m.kind == "user"]
                cmds = [("search", toks[0]), ("search", toks[0], "--role", "user"), ("open", pb + str(tb.msgs[0].line)),
                        ("user", "--last", "100"), ("history", tb.sid[:8]), ("handoffs",), ("map",), ("nodes",)]
                for c in cmds:
                    for cwd in (a, None):
                        args = list(c) + (["--cwd", cwd] if cwd else [])
                        r = self.rc(*args, sid=ta.sid, cwd=a)
                        for tok in toks:
                            self.assertNotIn(tok, r.stdout + r.stderr, "%s %s printed text of project B" % (t, c))
                r = self.rc("user", "--last", "100", sid=ta.sid, cwd=a)
                self.assertEqual(r.returncode, 0, t + r.stderr)
                self.assertIn(ta.msgs[0].texts[0].split()[0], r.stdout, t + " own project must stay readable")

    def test_i10_no_planted_secret_in_recall_output(self):
        for seed in SEEDS:
            shape = "main-secrets" if seed % 2 else "all-in-one"
            with self.subTest(seed=seed, shape=shape):
                t = tag(seed, shape)
                proj = self.project("p-%s" % seed)
                tr = g.Transcript(seed, shape).build(proj, secrets=g.secret_samples())
                _, prefix = self.put(tr, proj)
                self.assertTrue(tr.planted, t + " nothing planted")
                ids, got, raw = self.open_msgs(tr, prefix, proj)
                outs = [raw]
                for args in (("search", "planted", "--cwd", proj), ("user", "--last", "100", "--cwd", proj),
                             ("search", "TOK%s" % seed, "--cwd", proj)):
                    outs.append(self.rc(*args).stdout)
                for out in outs:
                    for needle in tr.planted:
                        self.assertNotIn(needle, out, "%s secret part %r in recall output" % (t, needle[:20]))

    def test_i10_redact_is_idempotent_on_generated_text(self):
        for seed in SEEDS:
            shape = "all-in-one"
            with self.subTest(seed=seed, shape=shape):
                tr = g.Transcript(seed, shape).build("/x", secrets=g.secret_samples())
                texts = [m.texts[0] for m in tr.msgs] + [raw for raw, _ in g.secret_samples()]
                once = redact_all(texts)
                twice = redact_all(once)
                for a, b, src in zip(once, twice, texts):
                    self.assertEqual(a, b, "%s redact is not idempotent for %r" % (tag(seed, shape), src[:50]))


class HookInvariants(HookCase):
    """PreCompact and PostCompact on generated transcripts (the summary call is off: no claude shim)."""
    LEDGER_ENV = "0"

    def pre(self, sid="S", cwd=None, fallback="0"):
        r = subprocess.run([sys.executable, PRE], input=json.dumps(self.payload(sid, cwd=cwd)), capture_output=True,
                           text=True, env=self.env(fallback), timeout=g.TIMEOUT)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def post_parts(self, sid="S"):
        out = []
        for k in (1, 2, 3):
            r = subprocess.run([sys.executable, POST, "--part", str(k)], input=json.dumps({"session_id": sid}),
                               capture_output=True, text=True, env=self.env(None), timeout=g.TIMEOUT)
            self.assertEqual((r.returncode, r.stderr), (0, ""))
            out.append(json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"] if r.stdout.strip() else "")
        return out

    def write_gen(self, tr):
        self.write_transcript([json.loads(l) for l in tr.lines])

    def test_i3_handoff_and_every_injected_part_stay_under_their_limits(self):
        import random
        for seed in SEEDS:
            shape = "all-in-one"
            with self.subTest(seed=seed, shape=shape):
                t = tag(seed, shape)
                r = random.Random("i3-%s" % seed)
                tr = g.Transcript(seed, shape).build(self.tmp)
                self.write_gen(tr)
                size = r.choice([500, 6000, 15000, 30000, 80000])
                body = " ".join("L%d-%d%s" % (seed, i, r.choice(g.WORDS)) for i in range(size // 8))
                self.agent_file(body, meta={"agentWrittenAt": 4102444800000})
                self.pre()
                self.assertLessEqual(len(self.latest()), CAP, "%s handoff file over its cap (input %d chars)" % (t, size))
                for k, c in enumerate(self.post_parts(), 1):
                    self.assertLess(len(c), 10000, "%s injected part %d is %d chars (input %d)" % (t, k, len(c), size))

    def test_i7_state_folders_are_0700_and_state_files_0600(self):
        for seed in SEEDS:
            shape = "main-plain" if seed % 2 else "all-in-one"
            with self.subTest(seed=seed, shape=shape):
                tr = g.Transcript(seed, shape).build(self.tmp)
                self.write_gen(tr)
                self.pre()
                self.post_parts()
                self.assertTrue(os.path.isdir(self.hd), tag(seed, shape) + " the hooks made no state folder")
                for root, dirs, files in os.walk(self.hd):
                    for d in dirs:
                        m = stat.S_IMODE(os.lstat(os.path.join(root, d)).st_mode)
                        self.assertEqual(m, 0o700, "%s folder %s has mode %o" % (tag(seed, shape), os.path.join(root, d), m))
                    for f in files:
                        m = stat.S_IMODE(os.lstat(os.path.join(root, f)).st_mode)
                        self.assertEqual(m, 0o600, "%s file %s has mode %o" % (tag(seed, shape), os.path.join(root, f), m))
                m = stat.S_IMODE(os.lstat(self.hd).st_mode)
                self.assertEqual(m, 0o700, "%s state folder has mode %o" % (tag(seed, shape), m))

    def test_i10_no_planted_secret_in_the_handoff_or_the_injected_parts(self):
        for seed in SEEDS:
            shape = "all-in-one" if seed % 2 else "main-secrets"
            with self.subTest(seed=seed, shape=shape):
                tr = g.Transcript(seed, shape).build(self.tmp, secrets=g.secret_samples())
                self.assertTrue(tr.planted)
                self.write_gen(tr)
                self.pre()
                outs = [self.latest()] + self.post_parts()
                for out in outs:
                    for needle in tr.planted:
                        self.assertNotIn(needle, out, "%s planted secret part %r in a hook output"
                                         % (tag(seed, shape), needle[:20]))


class PromptInvariants(HookCase):
    LEDGER_ENV = None  # the ledger merge call runs too, so that both model prompts are captured

    def test_i9_prompts_hold_no_backslash_quote_and_no_control_char(self):
        from test_f39_ledger import ts
        for seed in SEEDS:
            shape = "all-in-one"
            with self.subTest(seed=seed, shape=shape):
                t = tag(seed, shape)
                root = os.path.join(self.tmp, "repo%s" % seed)
                os.makedirs(root)
                subprocess.run(["git", "init", "-q", root], check=True, capture_output=True, timeout=g.TIMEOUT)
                tr = g.Transcript(seed, shape).build(root)
                self.install_shim(out="NO CHANGES")
                self.set_shim("merge", out="NO CHANGES")
                entries = []
                for i, l in enumerate(tr.lines):
                    d = json.loads(l)
                    d["timestamp"] = ts(i)
                    entries.append(d)
                entries.append(helpers.user('He said "stop" and it\'s done %s' % seed, timestamp=ts(len(entries))))
                self.write_transcript(entries)
                r = subprocess.run([sys.executable, PRE], input=json.dumps(self.payload("S", cwd=root)),
                                   capture_output=True, text=True, env=self.env("1"), timeout=g.TIMEOUT)
                self.assertEqual(r.returncode, 0, t + r.stderr)
                prompts = []
                for role in ("summary", "merge"):
                    pre = "merge." if role == "merge" else ""
                    p = os.path.join(self.shimdir, pre + "argv0")
                    if os.path.exists(p):
                        prompts.append(("argv " + role, open(p, "rb").read().decode().replace("\0", "\n\n")))
                    q = os.path.join(self.shimdir, pre + "stdin")
                    if os.path.exists(q):
                        prompts.append(("stdin " + role, open(q).read()))
                self.assertTrue(any(n.startswith("argv") for n, _ in prompts), t + " no model call was made")
                for name, text in prompts:
                    self.assertIsNone(re.search(r"\\[\"']", text), "%s %s holds a backslash before a quote" % (t, name))
                    if name.startswith("argv"):
                        self.assertIsNone(CTRL.search(text), "%s %s holds a control char" % (t, name))


if __name__ == "__main__":
    unittest.main()
