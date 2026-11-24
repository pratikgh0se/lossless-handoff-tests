"""F47 (b) amendment (a), 2026-11-25 (hooks 1.21.2, 0.19.2). Code-blind: written from the amendment text only.
The lossless check matches recall hits in both label forms, `<session8>:<line>` and `<parent8>/<agent8>:<line>`, and
opens the hit with the same label. A recall call that times out gives the verdict `skip` with the reason `timeout`,
not `fail`. Fixtures: a temp HOME, keyword-only recall, a real transcript on disk, and a receipt for it. The timeout
case uses a fake `recall.py` in a temp COPY of the hooks folder (the spec route of AC 190)."""
import os, shutil, subprocess, sys, unittest

from helpers import HOOKS_DIR
from test_f47_proof_receipts import ProofBase, BTS, jl
from test_f45_no_silent_miss import BOUNDARY
from test_f44_recall import RecallBase

PARENT = "f47a1111-0000-4000-8000-000000000001"
AGENT = "a1b2c3d4e5f6a7b8"


class Base(RecallBase, ProofBase):
    LEDGER_ENV = "0"

    def setUp(self):
        super().setUp()
        self.msgs = ["Message number %d about the quarterly invoice reconciliation SUBL%d-unique words and details here" % (i, i)
                     for i in range(1, 8)]

    def penv(self):
        return self.renv(embed=self.down)

    def records(self, sid, msgs=None):
        recs = [self.rec("user" if i % 2 else "assistant", m, sid=sid, cwd=self.proj, day=8, minute=i)
                for i, m in enumerate(msgs or self.msgs)]
        recs.append(dict(BOUNDARY, timestamp=BTS, sessionId=sid, cwd=self.proj))
        recs.append(self.rec("user", "A later message after the boundary exists here ok", sid=sid, cwd=self.proj,
                             day=10, minute=1))
        return recs

    def main_transcript(self):
        p = os.path.join(self.tdir(self.proj), PARENT + ".jsonl")
        self.write_jsonl(p, self.records(PARENT))
        return p

    def sub_transcript(self):
        # the parent session exists too, with other text, as in a real project (no duplicate copy of the subagent text)
        pp = os.path.join(self.tdir(self.proj), PARENT + ".jsonl")
        self.write_jsonl(pp, self.records(PARENT, ["Parent note number %d about the office plants and the watering PARN%d-unique" % (i, i)
                                                   for i in range(1, 8)]))
        p = os.path.join(self.tdir(self.proj), PARENT, "subagents", "agent-%s.jsonl" % AGENT)
        self.write_jsonl(p, self.records(PARENT))
        return p

    def fake_hooks(self, recall_source):
        hooks = os.path.join(self.tmp, "hooks-fake")
        shutil.copytree(HOOKS_DIR, hooks, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        with open(os.path.join(hooks, "recall.py"), "w") as f:
            f.write(recall_source)
        return os.path.join(hooks, "precompact-handoff.py")


class Labels(Base):
    def test_f47a_a_subagent_receipt_whose_message_recall_finds_gets_lossless_pass(self):
        t = self.sub_transcript()
        self.ok("index")
        rc = self.receipt(t, sid=PARENT, agent_id=AGENT, key=PARENT + "-a-" + AGENT)
        self.prove(env=self.penv())
        v = self.verdict(rc)
        self.assertEqual(v["checks"]["lossless"], "pass", v)

    def test_f47a_a_main_receipt_still_gets_lossless_pass(self):
        t = self.main_transcript()
        self.ok("index")
        rc = self.receipt(t, sid=PARENT)
        self.prove(env=self.penv())
        v = self.verdict(rc)
        self.assertEqual(v["checks"]["lossless"], "pass", v)

    def test_f47a_the_check_opens_a_hit_with_the_label_it_matched(self):
        """A fake recall prints only `<parent8>/<agent8>:<line>` hits and opens only that label."""
        t = self.sub_transcript()
        src = """#!/usr/bin/env python3
import json, sys
T = %r
LABEL = %r
args = sys.argv[1:]
rows = [json.loads(l) for l in open(T) if l.strip()]
def text(r):
    c = r.get("message", {}).get("content")
    return c if isinstance(c, str) else ""
if args and args[0] == "search":
    hits = [(i + 1, r) for i, r in enumerate(rows) if args[1] in text(r)]
    for i, r in hits:
        print("%%s:%%d 2026-03-08 12:00 %%s: %%s" %% (LABEL, i, r.get("type", "user"), text(r)[:150]))
    print("%%d hits shown of %%d (1 sessions searched)" %% (len(hits), len(hits)))
elif args and args[0] == "open":
    label, line = args[1].rsplit(":", 1)
    if label != LABEL:
        print("no such message"); sys.exit(1)
    r = rows[int(line) - 1]
    print("--- %%s:%%s 2026-03-08 12:00 %%s" %% (label, line, r.get("type", "user")))
    print(text(r))
""" % (t, "%s/%s" % (PARENT[:8], AGENT[:8]))
        pre = self.fake_hooks(src)
        rc = self.receipt(t, sid=PARENT, agent_id=AGENT, key=PARENT + "-a-" + AGENT)
        self.prove(env=self.penv(), pre=pre)
        v = self.verdict(rc)
        self.assertEqual(v["checks"]["lossless"], "pass", v)

    def test_f47a_the_session_label_form_still_works_with_a_fake_recall(self):
        t = self.main_transcript()
        src = """#!/usr/bin/env python3
import json, sys
T = %r
LABEL = %r
args = sys.argv[1:]
rows = [json.loads(l) for l in open(T) if l.strip()]
def text(r):
    c = r.get("message", {}).get("content")
    return c if isinstance(c, str) else ""
if args and args[0] == "search":
    hits = [(i + 1, r) for i, r in enumerate(rows) if args[1] in text(r)]
    for i, r in hits:
        print("%%s:%%d 2026-03-08 12:00 %%s: %%s" %% (LABEL, i, r.get("type", "user"), text(r)[:150]))
    print("%%d hits shown of %%d (1 sessions searched)" %% (len(hits), len(hits)))
elif args and args[0] == "open":
    label, line = args[1].rsplit(":", 1)
    if label != LABEL:
        print("no such message"); sys.exit(1)
    r = rows[int(line) - 1]
    print("--- %%s:%%s 2026-03-08 12:00 %%s" %% (label, line, r.get("type", "user")))
    print(text(r))
""" % (t, PARENT[:8])
        pre = self.fake_hooks(src)
        rc = self.receipt(t, sid=PARENT)
        self.prove(env=self.penv(), pre=pre)
        self.assertEqual(self.verdict(rc)["checks"]["lossless"], "pass")


# The amendment also says: a recall call that times out gives the verdict `skip` with the reason `timeout`. The spec gives
# no time limit and no setting for it. A fake recall.py that hangs kept `--prove` busy for more than 10 minutes on the
# product head, so no test of this rule is possible through the public interface in a reasonable time. It is not tested.


if __name__ == "__main__":
    unittest.main()
