"""Shared helpers for the 0.16.0 lever tests (F68-F71). Code-blind: built from contract-0.16.md only.
No tests live here. Each test file builds a temp HOME, copies the hook scripts into `HOME/.claude/hooks` and runs them
from there, so that the marker file `.recall-rules` and the optional hook files can be added or left out per test."""
import json, os, re, select, shutil, subprocess, sys, tempfile, time, unittest

import helpers
from helpers import copy_hook_scripts, HOOKS_DIR
from test_content import git
from test_f44_recall import key_for

RULE_SENTENCE = ("- recall rule: before you state an earlier number, path, name, command or decision, search for it. "
                 "Do not answer from memory. If the search finds nothing, say so.")
MCP_SUFFIX = " Or call the search_earlier_chat tool."
OPTIONAL = ("recall-mcp.py", "reanchor.py", "claim-guard.py")
RULE_A = "- D1 [2026-10-01] [rule] RULEAAA never put tool names in commit messages | why: user said so"
DEC_B = "- D2 [2026-10-02] [decision] DECBBB use sqlite for storage | why: simple"
TASK_C = "- D4 [2026-10-04] [task] TASKDDD approve the release draft | why: one off"
BOUNDARY = {"type": "system", "subtype": "compact_boundary", "content": "Conversation compacted",
            "timestamp": "2026-03-09T12:00:00.000Z", "compactMetadata": {"trigger": "auto", "preTokens": 100000}}


class Lab(unittest.TestCase):
    """A temp HOME with a git project, a hooks folder (optional hook files left out unless `keep`) and a state folder."""
    keep = ()

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="lev-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = os.path.join(self.tmp, "home")
        self.proj = os.path.join(self.tmp, "proj")
        os.makedirs(self.home)
        os.makedirs(self.proj)
        git(self.proj, "init", "-q")
        self.hooks = os.path.join(self.home, ".claude", "hooks")
        os.makedirs(self.hooks)
        copy_hook_scripts(self.hooks)
        for n in OPTIONAL:
            if n not in self.keep and os.path.exists(os.path.join(self.hooks, n)):
                os.remove(os.path.join(self.hooks, n))
        self.hd = os.path.join(self.home, ".local", "state", "claude-handoffs")
        self.pdir = os.path.join(self.hd, "projects", key_for(self.proj))

    def env(self, extra=None):
        e = {"HOME": self.home, "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8", "TZ": "UTC",
             "RECALL_EMBED_URL": "http://127.0.0.1:9"}
        e.update(extra or {})
        return e

    def ledger(self, lines):
        os.makedirs(self.pdir, exist_ok=True)
        with open(os.path.join(self.pdir, "decisions.md"), "w") as f:
            f.write("# Project decisions: %s\n%s\n" % (self.proj, "\n".join(lines)))

    def marker(self, on=True):
        p = os.path.join(self.hooks, ".recall-rules")
        if on:
            open(p, "w").close()
        elif os.path.exists(p):
            os.remove(p)

    def script(self, name, args=(), payload=None, raw=None, extra=None, cwd=None, timeout=30):
        data = raw if raw is not None else json.dumps(payload)
        return subprocess.run([sys.executable, os.path.join(self.hooks, name), *args], input=data, capture_output=True,
                              text=True, env=self.env(extra), cwd=cwd or self.proj, timeout=timeout)

    def jl(self, path):
        if not os.path.exists(path):
            return []
        with open(path) as f:
            return [json.loads(l) for l in f if l.strip()]

    def state_rows(self, name):
        return self.jl(os.path.join(self.hd, name))


def additional_context(stdout):
    s = stdout.strip()
    return json.loads(s)["hookSpecificOutput"]["additionalContext"]


def write_transcript(path, recs):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")


def usage_entry(total, split=False, ts=None):
    u = {"input_tokens": total, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "output_tokens": 0}
    if split:
        u.update(input_tokens=1000, cache_creation_input_tokens=20000, cache_read_input_tokens=total - 21000)
    return {"type": "assistant", "timestamp": ts or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "message": {"role": "assistant", "content": [{"type": "text", "text": "working"}], "usage": u}}


class Mcp:
    """A tiny newline-delimited JSON-RPC client over the stdio of a server process."""

    def __init__(self, argv, env, cwd):
        self.p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                                  cwd=cwd)
        self.buf = b""
        self.n = 0

    def send_raw(self, text):
        self.p.stdin.write(text.encode() + b"\n")
        self.p.stdin.flush()

    def send(self, obj):
        self.send_raw(json.dumps(obj))

    def recv(self, timeout=15):
        end = time.time() + timeout
        while b"\n" not in self.buf:
            left = end - time.time()
            if left <= 0:
                raise TimeoutError("no response line; got %r" % self.buf[:200])
            r, _, _ = select.select([self.p.stdout], [], [], left)
            if r:
                chunk = os.read(self.p.stdout.fileno(), 65536)
                if not chunk:
                    raise EOFError("server closed stdout; stderr=%r" % self.p.stderr.read()[:300])
                self.buf += chunk
        line, self.buf = self.buf.split(b"\n", 1)
        return json.loads(line)

    def call(self, method, params=None, timeout=15):
        self.n += 1
        msg = {"jsonrpc": "2.0", "id": self.n, "method": method}
        if params is not None:
            msg["params"] = params
        self.send(msg)
        r = self.recv(timeout)
        return r

    def tool(self, name, args, timeout=30):
        return self.call("tools/call", {"name": name, "arguments": args}, timeout)

    def init(self):
        r = self.call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                     "clientInfo": {"name": "lever-test", "version": "0"}})
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return r

    def close(self):
        try:
            self.p.stdin.close()
        except Exception:
            pass
        try:
            self.p.wait(timeout=10)
        except Exception:
            self.p.kill()
        for f in (self.p.stdout, self.p.stderr):
            try:
                f.close()
            except Exception:
                pass
        return self.p.returncode
