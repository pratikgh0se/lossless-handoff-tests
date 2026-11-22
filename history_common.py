"""Fixtures for the 0.17.0 tests (F73-F75): synthetic Claude Code transcripts in the real jsonl shape (user and assistant
entries with uuid, parentUuid, sessionId, cwd and timestamp; tool_use and tool_result blocks; hook attachments).
Code-blind: built from contract-0.17.md only."""
import json, os, re, shutil, subprocess, sys, tempfile, unittest

from helpers import copy_hook_scripts
from test_content import git

SID1 = "73000001-0000-4000-8000-000000000001"
SID2 = "73000002-0000-4000-8000-000000000002"
HIST_LINE1 = ("history of %s: %d mention(s), oldest first. A later mention can be a rejected proposal, a dry run or an "
              "undo; read all of them.")
NO_MENTIONS = "history of %s: no mentions"
ENTRY_RE = re.compile(r"^- (?P<id>\S+) (?P<ts>\d{4}-\d\d-\d\d \d\d:\d\d) (?P<role>user|assistant): (?P<text>.*)$")
OMIT_RE = re.compile(r"^\[(?P<k>\d+) mention\(s\) omitted in the middle; run: python3 (?P<hooks>\S+)/recall\.py history "
                     r"(?P<ident>\S+) --all\]$")
CAP = 4000


def ts(minute, day=1, hour=12, sec=0):
    return "2026-03-%02dT%02d:%02d:%02d.000Z" % (day, hour, minute, sec)


def entry(role, text, uuid, when, sid=SID1, cwd=None, parent=None):
    content = text if role == "user" else [{"type": "text", "text": text}]
    return {"parentUuid": parent, "isSidechain": False, "userType": "external", "cwd": cwd, "sessionId": sid,
            "type": role, "uuid": uuid, "timestamp": when, "message": {"role": role, "content": content}}


def bash_call(command, uuid, when, sid=SID1, cwd=None, tid="toolu_1"):
    return {"type": "assistant", "uuid": uuid, "timestamp": when, "sessionId": sid, "cwd": cwd,
            "message": {"role": "assistant", "content": [{"type": "tool_use", "id": tid, "name": "Bash",
                                                          "input": {"command": command}}]}}


def mcp_call(name, args, uuid, when, sid=SID1, cwd=None, tid="toolu_2"):
    return {"type": "assistant", "uuid": uuid, "timestamp": when, "sessionId": sid, "cwd": cwd,
            "message": {"role": "assistant", "content": [{"type": "tool_use", "id": tid, "name": name, "input": args}]}}


def tool_result(text, uuid, when, sid=SID1, cwd=None, tid="toolu_1"):
    return {"type": "user", "uuid": uuid, "timestamp": when, "sessionId": sid, "cwd": cwd,
            "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tid, "content": text}]}}


def injection(text, uuid, when, sid=SID1, cwd=None):
    return {"type": "attachment", "uuid": uuid, "timestamp": when, "sessionId": sid, "cwd": cwd, "attachment": {
        "type": "hook_additional_context", "hookName": "UserPromptSubmit", "hookEvent": "UserPromptSubmit",
        "toolUseID": "UserPromptSubmit", "content": [text]}}


class Lab(unittest.TestCase):
    """A temp HOME with a git project, a hooks folder (a copy of the hooks under test) and transcript helpers."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="h73-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = os.path.join(self.tmp, "home")
        self.proj = os.path.join(self.tmp, "proj")
        os.makedirs(self.home)
        os.makedirs(self.proj)
        git(self.proj, "init", "-q")
        self.hooks = os.path.join(self.home, ".claude", "hooks")
        os.makedirs(self.hooks)
        copy_hook_scripts(self.hooks)
        self.hd = os.path.join(self.home, ".local", "state", "claude-handoffs")
        self.tdir = os.path.join(self.home, ".claude", "projects", re.sub(r"[^A-Za-z0-9]", "-", self.proj))
        os.makedirs(self.tdir)
        self.recall = os.path.join(self.hooks, "recall.py")

    def env(self, extra=None):
        e = {"HOME": self.home, "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8", "TZ": "UTC",
             "RECALL_EMBED_URL": "http://127.0.0.1:9"}
        e.update(extra or {})
        return e

    def put(self, sid, recs, sub=None):
        """Write a transcript. `sub`: an agent id, to write it as a subagent transcript of session `sid`."""
        if sub:
            d = os.path.join(self.tdir, sid, "subagents")
            os.makedirs(d, exist_ok=True)
            path = os.path.join(d, "agent-%s.jsonl" % sub)
        else:
            path = os.path.join(self.tdir, sid + ".jsonl")
        with open(path, "w") as f:
            for r in recs:
                r = dict(r)
                r["cwd"] = r.get("cwd") or self.proj
                f.write(json.dumps(r) + "\n")
        return path

    def run_recall(self, *args, extra=None):
        r = subprocess.run([sys.executable, self.recall, *args], capture_output=True, text=True, env=self.env(extra),
                           cwd=self.proj, timeout=60)
        return r

    def history(self, ident, *args, extra=None):
        r = self.run_recall("history", ident, *args, extra=extra)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout

    @staticmethod
    def lines(out):
        return [l for l in out.split("\n") if l != ""]

    @staticmethod
    def entries(out):
        return [ENTRY_RE.match(l) for l in out.split("\n") if ENTRY_RE.match(l)]
