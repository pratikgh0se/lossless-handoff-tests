"""F72 Hooks-folder override `HANDOFF_HOOKS_HOME`. Code-blind: written from contract-0.16.md and the branch spec F72.
When the variable names an existing folder, every hook reads its helper files (`recall.py`, the marker `.recall-rules`,
`recall-mcp.py`, `postcompact-inject.py` for `reanchor.py`, the `lossless_handoff` parts) only from that folder: no
fallback to `~/.claude/hooks`, and no copy next to the hook file. Unset, empty or not a folder: `~/.claude/hooks`.
Setup: the fake HOME has a "live" hooks folder with decoy files that leave a trace, and a private folder P."""
import json, os, shutil, subprocess, sys, unittest

from helpers import copy_hook_scripts
from levers_common import Lab, OPTIONAL, RULE_SENTENCE, MCP_SUFFIX, RULE_A, DEC_B, Mcp, additional_context, usage_entry, write_transcript
from test_f67_auto_recall import HookBase, HEADER, HIT_RE

DECOY_RECALL = ('import os\nopen(os.path.join(os.environ["HOME"], "decoy-trace"), "a").write("recall\\n")\n')
DECOY_POST = ('import os\nopen(os.path.join(os.environ["HOME"], "decoy-trace"), "a").write("postcompact\\n")\n')
EMPTY_FALLBACKS = ("unset", "empty", "missing")


class Base(Lab):
    keep = ("recall-mcp.py", "reanchor.py")

    def setUp(self):
        super().setUp()
        self.trace = os.path.join(self.home, "decoy-trace")
        self.n = 0
        self.ledger([RULE_A, DEC_B])

    def private(self, with_marker=False, with_mcp=False, drop=()):
        self.n += 1
        d = os.path.join(self.tmp, "priv%d" % self.n)
        os.makedirs(d)
        copy_hook_scripts(d)
        for n in OPTIONAL:
            if not (n == "recall-mcp.py" and with_mcp) and n != "reanchor.py":
                p = os.path.join(d, n)
                if os.path.exists(p):
                    os.remove(p)
        for n in drop:
            os.remove(os.path.join(d, n))
        if with_marker:
            open(os.path.join(d, ".recall-rules"), "w").close()
        return d

    def decoys(self, recall=True, post=False, marker=True):
        """Make the live ~/.claude/hooks folder hold decoys that leave a trace when used."""
        if recall:
            open(os.path.join(self.hooks, "recall.py"), "w").write(DECOY_RECALL)
        if post:
            open(os.path.join(self.hooks, "postcompact-inject.py"), "w").write(DECOY_POST)
        self.marker(marker)

    def traced(self):
        return os.path.exists(self.trace)

    def run_in(self, folder, name, args=(), payload=None, raw=None, override=None):
        """Run `folder/name`. `override`: a folder path, or "unset" / "empty" / "missing"."""
        extra = {}
        if override == "empty":
            extra["HANDOFF_HOOKS_HOME"] = ""
        elif override == "missing":
            extra["HANDOFF_HOOKS_HOME"] = os.path.join(self.tmp, "no-such-folder")
        elif override not in (None, "unset"):
            extra["HANDOFF_HOOKS_HOME"] = override
        data = raw if raw is not None else json.dumps(payload)
        return subprocess.run([sys.executable, os.path.join(folder, name), *args], input=data, capture_output=True,
                              text=True, env=self.env(extra), cwd=self.proj, timeout=60)


class PostcompactInject(Base):
    def part1(self, folder, override, source="compact"):
        payload = {"cwd": self.proj, "session_id": "N", "hook_event_name": "SessionStart", "source": source}
        r = self.run_in(folder, "postcompact-inject.py", ("--ledger", "--part", "1"), payload, override=override)
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout)
        return additional_context(r.stdout).split("\n")

    def sub(self, folder, override):
        payload = {"session_id": "58585858-0000-4000-8000-000000000058", "cwd": self.proj, "prompt_id": "p-1",
                   "agent_id": "a1b2c3d4e5f6a7b8", "agent_type": "general-purpose", "hook_event_name": "SubagentStart",
                   "transcript_path": os.path.join(self.home, ".claude", "projects", "x", "s.jsonl")}
        r = self.run_in(folder, "postcompact-inject.py", ("--subagent-start",), payload, override=override)
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout)
        return additional_context(r.stdout).split("\n")

    @staticmethod
    def rec(lines):
        return [l for l in lines if l.startswith("- recall:")]

    def test_f72_override_reads_only_the_private_folder_no_marker_no_mcp_no_decoy(self):
        self.decoys(marker=True)  # live: marker, recall-mcp.py, decoy recall.py
        p = self.private()
        for source in ("startup", "compact", "resume"):
            with self.subTest(source):
                lines = self.part1(p, p, source)
                self.assertEqual(len(self.rec(lines)), 1, "the recall line comes from the private recall.py")
                self.assertNotIn(RULE_SENTENCE, lines)
                self.assertFalse(self.rec(lines)[0].endswith(MCP_SUFFIX))
        lines = self.sub(p, p)
        self.assertEqual(len(self.rec(lines)), 1)
        self.assertNotIn(RULE_SENTENCE, lines)
        self.assertFalse(self.rec(lines)[0].endswith(MCP_SUFFIX))
        self.assertFalse(self.traced(), "the decoy recall.py of ~/.claude/hooks was used")

    def test_f72_override_reads_the_private_marker_and_mcp_file(self):
        self.decoys(marker=False)
        os.remove(os.path.join(self.hooks, "recall-mcp.py"))
        p = self.private(with_marker=True, with_mcp=True)
        for lines in (self.part1(p, p), self.sub(p, p)):
            i = [k for k, l in enumerate(lines) if l.startswith("- recall:")][0]
            self.assertTrue(lines[i].endswith(MCP_SUFFIX))
            self.assertEqual(lines[i + 1], RULE_SENTENCE)
        self.assertFalse(self.traced())

    def test_f72_a_copy_next_to_the_hook_file_is_not_used(self):
        # the script sits in a folder with marker, mcp and recall.py; the override names another folder without them
        self.decoys(recall=False, marker=False)
        os.remove(os.path.join(self.hooks, "recall-mcp.py"))
        script_dir = self.private(with_marker=True, with_mcp=True)
        other = self.private()
        for lines in (self.part1(script_dir, other), self.sub(script_dir, other)):
            self.assertNotIn(RULE_SENTENCE, lines)
            self.assertFalse(any(l.endswith(MCP_SUFFIX) for l in self.rec(lines)))

    def test_f72_a_missing_file_in_the_override_folder_means_the_part_is_absent(self):
        self.decoys(marker=True)  # live has recall.py (decoy), marker and recall-mcp.py
        p = self.private(drop=("recall.py",))
        for lines in (self.part1(p, p), self.sub(p, p)):
            self.assertEqual(self.rec(lines), [], "no recall line when the private folder has no recall.py")
            self.assertNotIn(RULE_SENTENCE, lines)
        self.assertFalse(self.traced())

    def test_f72_unset_empty_or_missing_falls_back_to_the_home_folder(self):
        self.decoys(recall=False, marker=True)  # live: marker + recall-mcp.py + the real recall.py
        script_dir = self.private()  # a bare copy: no marker, no mcp file
        for ov in EMPTY_FALLBACKS:
            with self.subTest(ov):
                for lines in (self.part1(script_dir, ov), self.sub(script_dir, ov)):
                    i = [k for k, l in enumerate(lines) if l.startswith("- recall:")][0]
                    self.assertTrue(lines[i].endswith(MCP_SUFFIX), "recall-mcp.py of ~/.claude/hooks")
                    self.assertEqual(lines[i + 1], RULE_SENTENCE, "marker of ~/.claude/hooks")

    def test_f72_a_regular_file_is_not_a_folder_and_falls_back(self):
        self.decoys(recall=False, marker=True)
        script_dir = self.private()
        f = os.path.join(self.tmp, "afile")
        open(f, "w").close()
        lines = self.part1(script_dir, f)
        self.assertIn(RULE_SENTENCE, lines)


class AutoRecallHook(HookBase):
    def setUp(self):
        super().setUp()
        self.hooks = os.path.join(self.home, ".claude", "hooks")
        os.makedirs(self.hooks)
        copy_hook_scripts(self.hooks)
        self.trace = os.path.join(self.home, "decoy-trace")
        self.seed([("user", "We decided to use the postgres database for the billing service BILLINGMARK")])
        self.n = 0

    def private(self, drop=()):
        self.n += 1
        d = os.path.join(self.tmp, "priv%d" % self.n)
        os.makedirs(d)
        copy_hook_scripts(d)
        for n in drop:
            os.remove(os.path.join(d, n))
        return d

    def run_ar(self, folder, override):
        extra = {}
        if override == "empty":
            extra["HANDOFF_HOOKS_HOME"] = ""
        elif override == "missing":
            extra["HANDOFF_HOOKS_HOME"] = os.path.join(self.tmp, "no-such-folder")
        elif override not in (None, "unset"):
            extra["HANDOFF_HOOKS_HOME"] = override
        payload = {"session_id": self.sid, "transcript_path": self.session, "cwd": self.proj,
                   "prompt": "what did i say about the postgres billing database", "hook_event_name": "UserPromptSubmit"}
        r = subprocess.run([sys.executable, os.path.join(folder, "auto-recall.py")], input=json.dumps(payload),
                           capture_output=True, text=True, env=self.env2(extra), timeout=30, cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def decoy(self):
        open(os.path.join(self.hooks, "recall.py"), "w").write(DECOY_RECALL)

    def test_f72_auto_recall_uses_the_private_recall_py(self):
        self.decoy()
        p = self.private()
        out = self.context(self.run_ar(p, p))
        self.assertTrue(out.startswith(HEADER), out[:200])
        self.assertIn("BILLINGMARK", out)
        self.assertFalse(os.path.exists(self.trace))

    def test_f72_auto_recall_never_uses_a_copy_next_to_the_hook_or_the_home_folder(self):
        self.decoy()
        script_dir = self.private()  # has the real recall.py next to the hook
        empty = self.private(drop=("recall.py",))
        out = self.run_ar(script_dir, empty)
        self.assertEqual(out.strip(), "")
        self.assertFalse(os.path.exists(self.trace))

    def test_f72_auto_recall_falls_back_to_the_home_folder(self):
        for ov in EMPTY_FALLBACKS:
            with self.subTest(ov):
                if os.path.exists(self.trace):
                    os.remove(self.trace)
                self.decoy()
                script_dir = self.private(drop=("recall.py",))
                out = self.run_ar(script_dir, ov)
                self.assertEqual(out.strip(), "")
                self.assertTrue(os.path.exists(self.trace), "the recall.py of ~/.claude/hooks was not used")


class McpServer(HookBase):
    def setUp(self):
        super().setUp()
        self.hooks = os.path.join(self.home, ".claude", "hooks")
        os.makedirs(self.hooks)
        copy_hook_scripts(self.hooks)
        open(os.path.join(self.hooks, "recall.py"), "w").write(DECOY_RECALL)
        self.trace = os.path.join(self.home, "decoy-trace")
        self.seed([("user", "We decided to use the postgres database for the billing service BILLINGMARK")])
        self.clients = []
        self.n = 0

    def tearDown(self):
        for c in self.clients:
            c.close()

    def private(self, drop=()):
        self.n += 1
        d = os.path.join(self.tmp, "priv%d" % self.n)
        os.makedirs(d)
        copy_hook_scripts(d)
        for n in drop:
            os.remove(os.path.join(d, n))
        return d

    def server(self, folder, override):
        extra = {}
        if override == "empty":
            extra["HANDOFF_HOOKS_HOME"] = ""
        elif override == "missing":
            extra["HANDOFF_HOOKS_HOME"] = os.path.join(self.tmp, "no-such-folder")
        elif override not in (None, "unset"):
            extra["HANDOFF_HOOKS_HOME"] = override
        c = Mcp([sys.executable, os.path.join(folder, "recall-mcp.py")], self.env2(extra), self.proj)
        self.clients.append(c)
        c.init()
        return c

    def test_f72_mcp_server_uses_the_private_recall_py(self):
        p = self.private()
        c = self.server(p, p)
        out = c.tool("search_earlier_chat", {"query": "BILLINGMARK"})["result"]["content"][0]["text"]
        self.assertIn("BILLINGMARK", out)
        self.assertFalse(os.path.exists(self.trace))

    def test_f72_mcp_server_never_uses_the_home_folder_or_its_own_folder_when_overridden(self):
        script_dir = self.private()
        empty = self.private(drop=("recall.py",))
        c = self.server(script_dir, empty)
        r = c.tool("search_earlier_chat", {"query": "BILLINGMARK"})
        text = r["result"]["content"][0]["text"] if "result" in r else ""
        self.assertNotIn("BILLINGMARK", text)
        self.assertFalse(os.path.exists(self.trace))
        self.assertEqual(c.call("ping").get("result"), {}, "the server keeps running")

    def test_f72_mcp_server_falls_back_to_the_home_folder(self):
        for ov in EMPTY_FALLBACKS:
            with self.subTest(ov):
                if os.path.exists(self.trace):
                    os.remove(self.trace)
                script_dir = self.private(drop=("recall.py",))
                c = self.server(script_dir, ov)
                c.tool("search_earlier_chat", {"query": "BILLINGMARK"})
                self.assertTrue(os.path.exists(self.trace), "the recall.py of ~/.claude/hooks was not used")


class Reanchor(Base):
    def run_re(self, folder, override, tokens=60000, k=0):
        sid = "72727272-0000-4000-8000-0000000000%02d" % k
        tp = os.path.join(self.home, ".claude", "projects", "x", sid + ".jsonl")
        write_transcript(tp, [{"type": "user", "message": {"role": "user", "content": "Please keep going"}},
                              usage_entry(tokens)])
        payload = {"session_id": sid, "transcript_path": tp, "cwd": self.proj, "hook_event_name": "PostToolUse",
                   "tool_name": "Bash", "tool_input": {"command": "ls"}, "tool_response": {"stdout": "x"}}
        r = self.run_in(folder, "reanchor.py", (), payload, override=override)
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout)
        return r.stdout

    def test_f72_reanchor_uses_postcompact_inject_of_the_private_folder(self):
        self.decoys(post=True, marker=False)
        p = self.private()
        out = self.run_re(p, p)
        self.assertIn("RULEAAA", json.loads(out)["hookSpecificOutput"]["additionalContext"])
        self.assertFalse(self.traced())

    def test_f72_reanchor_does_not_use_the_home_folder_or_its_own_folder_when_overridden(self):
        self.decoys(post=True, marker=False)
        script_dir = self.private()
        no_post = self.private(drop=("postcompact-inject.py",))
        self.assertEqual(self.run_re(script_dir, no_post).strip(), "")
        self.assertFalse(self.traced())

    def test_f72_reanchor_falls_back_to_the_home_folder(self):
        for k, ov in enumerate(EMPTY_FALLBACKS):
            with self.subTest(ov):
                if self.traced():
                    os.remove(self.trace)
                self.decoys(post=True, marker=False)
                script_dir = self.private(drop=("postcompact-inject.py",))
                self.run_re(script_dir, ov, k=k)
                self.assertTrue(self.traced(), "postcompact-inject.py of ~/.claude/hooks was not used")


class Precompact(Base):
    def payload(self, tp):
        return {"session_id": "S", "cwd": self.proj, "trigger": "auto", "transcript_path": tp}

    def test_f72_precompact_with_the_override_does_not_use_the_package_next_to_the_hook(self):
        tp = os.path.join(self.home, ".claude", "projects", "x", "S.jsonl")
        write_transcript(tp, [{"type": "user", "message": {"role": "user", "content": "Please fix the billing exporter now"}},
                              {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "ok"}]}}])
        script_dir = self.private()
        good = self.private()
        pkg = os.path.join(script_dir, "lossless_handoff")
        if not os.path.isdir(pkg):
            self.skipTest("this tree has no lossless_handoff package")
        for n in os.listdir(pkg):
            if n in ("summary.py", "prove.py"):  # F72.a: only these two parts follow the override
                with open(os.path.join(pkg, n), "a") as f:
                    f.write('\nimport os as _o\nopen(_o.path.join(_o.environ["HOME"], "decoy-trace"), "a").write("%s\\n")\n' % n)
        env_extra = {"HANDOFF_HAIKU_FALLBACK": "0"}
        r = subprocess.run([sys.executable, os.path.join(script_dir, "precompact-handoff.py")], input=json.dumps(self.payload(tp)),
                           capture_output=True, text=True, env=self.env(dict(env_extra, HANDOFF_HOOKS_HOME=good)),
                           cwd=self.proj, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(self.traced(), open(self.trace).read() if self.traced() else "")
        self.assertTrue(os.path.exists(os.path.join(self.hd, "S-latest.md")), "the handoff is still written")


if __name__ == "__main__":
    unittest.main()
