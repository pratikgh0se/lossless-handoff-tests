"""Fixtures for the 0.18.0 tests (F77 history guard, F78 size trigger, F80 action guard). Code-blind: built from
contract-0.18.md and sections 2 and 3 of litm-trigger-design.md. Synthetic Claude Code transcripts in the real jsonl shape."""
import json, os, re, stat, subprocess, sys, time

from history_common import (Lab as HLab, SID1, HIST_LINE1, ENTRY_RE, OMIT_RE, ts, entry, bash_call, mcp_call, tool_result,
                            injection)
from levers_common import usage_entry

GUARD_LINE1 = ("Lossless Handoff history check: your reply uses values that changed in this chat. The full history is below, "
               "oldest first. A later mention can be a rejected proposal, a dry run or an undo. Read every mention in order. "
               "If your reply is correct, send the same reply again. If it is not, send the corrected reply. Do not mention "
               "this check.")
ACTION_LINE1 = ("Lossless Handoff history check: your last tool call used names whose values changed in this chat. The full "
                "history is below, oldest first. A later mention can be a rejected proposal, a dry run or an undo. If the call "
                "used an old, rejected or undone value, fix it now. If it is correct, go on. Do not mention this check.")
BLOCK_RE = re.compile(r"^history of (?P<ident>\S+?):")
HEALTH_KEYS = {"ts", "session_id", "mode", "fired", "subjects", "anchors", "tokens", "chars", "ms"}
KEY = "queue-depth"
ACTION_EVENT = "PostToolBatch"


def guard_text(stdout, event="Stop"):
    """The text that a guard hands to Claude. Pinned form (product spec F77/F80): one JSON object
    {"hookSpecificOutput": {"hookEventName": <event>, "additionalContext": text}}. Returns "" for no output.
    A different form raises an assertion error."""
    s = stdout.strip()
    if not s:
        return ""
    o = json.loads(s)
    h = o["hookSpecificOutput"]
    assert h["hookEventName"] == event, s[:200]
    assert set(o) == {"hookSpecificOutput"}, s[:200]
    return h["additionalContext"].strip("\n")


def chain(key=KEY, users=2, assistants=1, start=0, tag="", day=1):
    """Text messages that mention `key`: users and assistants interleaved, oldest first."""
    recs = []
    u, a = users, assistants
    roles = []
    while u or a:
        if u:
            roles.append("user"); u -= 1
        if a:
            roles.append("assistant"); a -= 1
    for i, r in enumerate(roles):
        recs.append(entry(r, "%s step %s%d is the value %d" % (key, tag, i, i * 10), "%s%s-%d" % (key, tag, i),
                          ts((start + i) % 60, day=day, hour=10 + (start + i) // 60)))
    return recs


class G(HLab):
    """A guard lab: hooks copy, transcript, state dir, and runners for the three guards."""
    sid = SID1

    def setUp(self):
        super().setUp()
        self.session = os.path.join(self.tdir, self.sid + ".jsonl")
        self.state = os.path.join(self.tmp, "state")
        self.row_n = 0

    # ---- transcript
    def tx(self, recs, tokens=150000, prompt="please go on with the task", tail=()):
        """Write: the chat, a usage entry, the current user prompt, then `tail` (this turn's tool entries)."""
        out = list(recs)
        if tokens is not None:
            out.append(usage_entry(tokens, ts="2026-03-01T13:00:00Z"))
        out.append(entry("user", prompt, "cur-" + re.sub(r"\W", "", prompt)[:40], ts(0, day=2)))  # one uuid for each prompt
        out += list(tail)
        self.put(self.sid, out)
        return out

    def sdir(self):
        return self.state if os.path.isdir(self.state) else self.hd

    def genv(self, extra=None):
        e = {"HANDOFF_STATE_DIR": self.state}
        e.update(extra or {})
        return self.env(e)

    # ---- runners
    def run_stop(self, reply, extra=None, stop_hook_active=False, raw=None, payload=None, name="history-guard.py"):
        p = {"session_id": self.sid, "transcript_path": self.session, "cwd": self.proj, "hook_event_name": "Stop",
             "stop_hook_active": stop_hook_active, "last_assistant_message": reply}
        p.update(payload or {})
        t0 = time.time()
        r = subprocess.run([sys.executable, os.path.join(self.hooks, name)], input=json.dumps(p) if raw is None else raw,
                           capture_output=True, text=True, env=self.genv(extra), cwd=self.tmp, timeout=30)
        self.elapsed = time.time() - t0
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def stop(self, reply, mode="block", **kw):
        extra = dict(kw.pop("extra", None) or {})
        if mode is not None:
            extra["HANDOFF_HISTORY_GUARD"] = mode
        return guard_text(self.run_stop(reply, extra=extra, **kw))

    def run_action(self, tool, tool_input, extra=None, raw=None, payload=None):
        p = {"session_id": self.sid, "transcript_path": self.session, "cwd": self.proj, "hook_event_name": ACTION_EVENT}
        p["tool_calls"] = [{"tool_name": tool, "tool_input": tool_input, "tool_response": {"ok": True},
                            "tool_use_id": "toolu_act"}]
        p.update(payload or {})
        t0 = time.time()
        r = subprocess.run([sys.executable, os.path.join(self.hooks, "action-guard.py")],
                           input=json.dumps(p) if raw is None else raw, capture_output=True, text=True,
                           env=self.genv(extra), cwd=self.tmp, timeout=30)
        self.elapsed = time.time() - t0
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def act(self, tool, tool_input, mode="inject", **kw):
        extra = dict(kw.pop("extra", None) or {})
        if mode is not None:
            extra["HANDOFF_ACTION_GUARD"] = mode
        return guard_text(self.run_action(tool, tool_input, extra=extra, **kw), ACTION_EVENT)

    def rows(self, name="history-guard.jsonl"):
        p = os.path.join(self.state, name)
        return [json.loads(l) for l in open(p) if l.strip()] if os.path.exists(p) else []

    def blocks(self, text):
        return [m.group("ident") for m in (BLOCK_RE.match(l) for l in text.split("\n")) if m]

    def mode_of(self, path):
        return stat.S_IMODE(os.stat(path).st_mode)
