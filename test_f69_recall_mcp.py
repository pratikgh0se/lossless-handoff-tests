"""F69 Recall MCP tool (opt-in, `--recall-mcp`): the stdio server `hooks/recall-mcp.py`. Code-blind: written from
contract-0.16.md. The tests drive the server with newline-delimited JSON-RPC 2.0 over stdio. Fixtures are fake
transcripts in a temp HOME; the meaning index is off (closed port), so the search is word only.
Hit lines must equal the lines `recall.py search` prints for the same words (same scope and ranking)."""
import json, os, re, subprocess, sys, unittest

from helpers import copy_hook_scripts
from levers_common import Lab, Mcp, RULE_SENTENCE, write_transcript
from test_f67_auto_recall import HookBase, HIT_RE

SERVER = "recall-mcp.py"
CAP = 12000
CUT = "[cut at 12000 characters]"
HIT = re.compile(r"^\S+:\d+ \d{4}-\d\d-\d\d \d\d:\d\d (user|assistant)\b")  # the recall.py search hit line


def hits_of(text):
    return [l for l in text.split("\n") if HIT.match(l)]


class Server(HookBase):
    """HookBase gives the project, the transcript folder and `seed()` (see test_f67_auto_recall)."""

    def seed(self, messages, current=None):
        # 0.19.0 (F73/F74): the MCP tools leave out the current prompt (the last user prompt and what follows), so every
        # fixture ends with a closing user prompt that has no query words.
        super().seed(list(messages) + [("user", "an unrelated closing prompt")], current)

    def setUp(self):
        super().setUp()
        self.hooks = os.path.join(self.home, ".claude", "hooks")
        os.makedirs(self.hooks)
        copy_hook_scripts(self.hooks)
        self.assertTrue(os.path.isfile(os.path.join(self.hooks, SERVER)), "hooks/recall-mcp.py is missing")
        self.clients = []
        self.seed([("user", "We decided to use the postgres database for the billing service BILLINGMARK"),
                   ("assistant", "Understood: postgres for the billing service, with nightly backups"),
                   ("user", "The kubernetes cluster needs three nodes for the staging deployment")])

    def tearDown(self):
        for c in self.clients:
            c.close()

    def start(self, extra=None, init=True):
        c = Mcp([sys.executable, os.path.join(self.hooks, SERVER)], self.env2(extra), self.proj)
        self.clients.append(c)
        if init:
            self.assertIn("result", c.init())
        return c

    def cli(self, *args):
        r = subprocess.run([sys.executable, os.path.join(self.hooks, "recall.py"), *args], capture_output=True, text=True,
                           env=self.env2(), cwd=self.proj, timeout=60)
        return r.stdout

    @staticmethod
    def text(resp):
        assert "result" in resp, resp
        return resp["result"]["content"][0]["text"]


class Handshake(Server):
    def test_f69_initialize_result(self):
        c = self.start(init=False)
        r = c.call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                  "clientInfo": {"name": "t", "version": "0"}})
        self.assertEqual(r["jsonrpc"], "2.0")
        self.assertEqual(r["id"], 1)
        res = r["result"]
        self.assertEqual(res["serverInfo"]["name"], "lossless-recall")
        self.assertEqual(res["serverInfo"]["version"], "1.23.1")
        self.assertIn("tools", res["capabilities"])
        self.assertIsInstance(res["protocolVersion"], str)

    def test_f69_instructions_hold_the_recall_rule_and_stay_short(self):
        r = self.start(init=False).call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                                       "clientInfo": {"name": "t", "version": "0"}})
        ins = r["result"]["instructions"]
        self.assertIsInstance(ins, str)
        self.assertLess(len(ins), 4096)
        self.assertIn(RULE_SENTENCE.lstrip("- ").replace("recall rule: ", ""), ins)
        self.assertGreater(len(ins.split("\n")), 1, "one more line on when to use the tools")

    def test_f84_d_instructions_use_the_new_recall_text(self):
        r = self.start(init=False).call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                                       "clientInfo": {"name": "t", "version": "0"}})
        ins = r["result"]["instructions"]
        self.assertIn("One call takes several patterns or several ids. Do not use cd, a loop or a shell variable", ins)
        self.assertNotIn("(same full path for: open <id>; user --last 20; do not cd)", ins)

    def test_f69_ping_and_initialized_notification(self):
        c = self.start()
        r = c.call("ping")
        self.assertEqual((r["id"], r.get("result")), (c.n, {}))

    def test_f69_tools_list_has_both_tools_with_always_load_meta(self):
        c = self.start()
        tools = c.call("tools/list")["result"]["tools"]
        by = {t["name"]: t for t in tools}
        self.assertEqual(sorted(by), ["key_history", "open_message", "search_earlier_chat"])
        for t in tools:
            self.assertEqual(t["_meta"], {"anthropic/alwaysLoad": True}, t["name"])
            self.assertEqual(t["inputSchema"]["type"], "object")
            self.assertTrue(t["description"])
        s = by["search_earlier_chat"]["inputSchema"]
        self.assertEqual(s["required"], ["query"])
        self.assertTrue({"query", "role", "limit"} <= set(s["properties"]))
        o = by["open_message"]["inputSchema"]
        self.assertEqual(o["required"], ["id"])
        self.assertTrue({"id", "full"} <= set(o["properties"]))


class Protocol(Server):
    def test_f69_protocol_version_is_echoed_when_known_else_the_default(self):
        for v, want in (("2025-11-25", "2025-11-25"), ("2025-06-18", "2025-06-18"), ("2025-03-26", "2025-03-26"),
                        ("2024-11-05", "2024-11-05"), ("1999-01-01", "2025-11-25")):
            with self.subTest(v):
                c = self.start(init=False)
                r = c.call("initialize", {"protocolVersion": v, "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}})
                self.assertEqual(r["result"]["protocolVersion"], want)

    def test_f69_unknown_method_is_32601_and_unknown_tool_is_32602(self):
        c = self.start()
        self.assertEqual(c.call("no/such/method")["error"]["code"], -32601)
        self.assertEqual(c.tool("no_such_tool", {})["error"]["code"], -32602)
        self.assertEqual(c.call("ping").get("result"), {})

    def test_f69_a_notification_gets_no_reply(self):
        c = self.start()
        c.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        c.send({"jsonrpc": "2.0", "method": "notifications/something_else"})
        self.assertEqual(c.call("ping").get("result"), {})


class Search(Server):
    def test_f69_search_hit_lines_are_the_recall_py_hit_lines(self):
        c = self.start()
        out = self.text(c.tool("search_earlier_chat", {"query": "postgres"}))
        lines = [l for l in out.split("\n") if l.strip()]
        self.assertTrue(lines, out)
        cli = self.cli("search", "postgres").split("\n")
        for l in lines:
            self.assertIn(l, cli, l)
        self.assertTrue(any("BILLINGMARK" in l for l in lines), lines)
        self.assertNotIn("kubernetes", out)

    def test_f69_hit_line_has_id_and_role(self):
        c = self.start()
        out = self.text(c.tool("search_earlier_chat", {"query": "postgres"}))
        hit = hits_of(out)
        self.assertTrue(hit, out)
        self.assertRegex(hit[0], HIT.pattern)

    def test_f69_role_filter(self):
        c = self.start()
        out = self.text(c.tool("search_earlier_chat", {"query": "postgres", "role": "assistant"}))
        self.assertIn("nightly backups", out)
        self.assertNotIn("BILLINGMARK", out)
        out = self.text(c.tool("search_earlier_chat", {"query": "postgres", "role": "user"}))
        self.assertIn("BILLINGMARK", out)
        self.assertNotIn("nightly backups", out)
        both = self.text(c.tool("search_earlier_chat", {"query": "postgres", "role": "any"}))
        self.assertIn("BILLINGMARK", both)
        self.assertIn("nightly backups", both)

    def test_f69_limit_and_default_limit(self):
        self.seed([("user", "Note %d about the postgres billing database design" % i) for i in range(12)])
        c = self.start()
        count = lambda t: len(hits_of(t))
        self.assertEqual(count(self.text(c.tool("search_earlier_chat", {"query": "postgres", "limit": 1}))), 1)
        self.assertEqual(count(self.text(c.tool("search_earlier_chat", {"query": "postgres", "limit": 10}))), 10)
        self.assertEqual(count(self.text(c.tool("search_earlier_chat", {"query": "postgres"}))), 5)

    def test_f69_no_matches(self):
        c = self.start()
        r = c.tool("search_earlier_chat", {"query": "zebra giraffe antelope"})
        self.assertEqual(self.text(r), "no matches")
        self.assertFalse(r["result"].get("isError", False))

    def test_f69_search_text_is_redacted(self):
        key = "sk-" + "FAKEmcprecall" * 3 + "0001"
        self.seed([("user", "gateway deployment password=zqmcp0042x and key %s end" % key)])
        c = self.start()
        out = self.text(c.tool("search_earlier_chat", {"query": "gateway deployment"}))
        self.assertIn("[REDACTED:", out)
        self.assertNotIn("zqmcp0042x", out)
        self.assertNotIn(key, out)


class Open(Server):
    def first_id(self, c, query="BILLINGMARK"):
        out = self.text(c.tool("search_earlier_chat", {"query": query, "role": "user"}))
        return hits_of(out)[0].split()[0]

    def test_f69_open_message_equals_recall_py_open(self):
        c = self.start()
        mid = self.first_id(c)
        self.assertEqual(self.text(c.tool("open_message", {"id": mid})).strip(), self.cli("open", mid).strip())
        self.assertIn("BILLINGMARK", self.text(c.tool("open_message", {"id": mid})))

    def test_f69_full_flag_matches_open_full(self):
        self.seed([("user", "postgres billing database " + "filler " * 400 + "TAILMARK")])
        c = self.start()
        mid = self.first_id(c, "postgres billing database")
        short = self.text(c.tool("open_message", {"id": mid, "full": False}))
        full = self.text(c.tool("open_message", {"id": mid, "full": True}))
        self.assertEqual(full.strip(), self.cli("open", mid, "--full").strip())
        self.assertEqual(short.strip(), self.cli("open", mid).strip())
        self.assertIn("TAILMARK", full)

    def test_f69_every_result_is_capped_at_12000_characters(self):
        self.seed([("user", "postgres billing database " + "filler " * 6000 + "TAILMARK")])
        c = self.start()
        mid = self.first_id(c, "postgres billing database")
        self.assertGreater(len(self.cli("open", mid, "--full")), CAP, "fixture must exceed the cap")
        out = self.text(c.tool("open_message", {"id": mid, "full": True}))
        self.assertLessEqual(len(out), CAP)
        self.assertEqual(out.split("\n")[-1], CUT)
        self.assertNotIn("TAILMARK", out)

    def test_f69_a_short_result_is_not_cut(self):
        c = self.start()
        out = self.text(c.tool("search_earlier_chat", {"query": "postgres"}))
        self.assertNotIn(CUT, out)

    def test_f69_open_text_is_redacted(self):
        key = "sk-" + "FAKEmcpopen" * 3 + "0002"
        self.seed([("user", "gateway deployment password=zqmcpopen77 and key %s end" % key)])
        c = self.start()
        out = self.text(c.tool("open_message", {"id": self.first_id(c, "gateway deployment")}))
        self.assertIn("[REDACTED:", out)
        self.assertNotIn("zqmcpopen77", out)
        self.assertNotIn(key, out)


class Errors(Server):
    def assert_tool_error(self, r):
        self.assertIn("result", r, r)
        self.assertIs(r["result"].get("isError"), True, r)
        t = r["result"]["content"][0]["text"]
        self.assertTrue(t.strip())
        self.assertNotIn("\n", t.strip(), "one line of text")

    def test_f69_bad_input_gives_is_error_and_the_server_goes_on(self):
        c = self.start()
        cases = [("search_earlier_chat", {}), ("search_earlier_chat", {"query": 5}),
                 ("search_earlier_chat", {"query": "postgres", "limit": 0}),
                 ("search_earlier_chat", {"query": "postgres", "limit": 11}),
                 ("search_earlier_chat", {"query": "postgres", "role": "bogus"}),
                 ("open_message", {}), ("open_message", {"id": "no-such-id-0000:99"}),
                 ("open_message", {"id": 7})]
        for name, args in cases:
            with self.subTest(name, args=args):
                self.assert_tool_error(c.tool(name, args))
        self.assertEqual(c.call("ping").get("result"), {})

    def test_f69_unknown_tool_is_an_error_not_a_crash(self):
        c = self.start()
        r = c.tool("no_such_tool", {})
        self.assertTrue("error" in r or r.get("result", {}).get("isError") is True, r)
        self.assertEqual(c.call("ping").get("result"), {})

    def test_f69_malformed_json_line_gets_a_parse_error_and_the_server_keeps_running(self):
        c = self.start()
        c.send_raw("{this is not json")
        r = c.recv()
        self.assertEqual(r["error"]["code"], -32700)
        self.assertIsNone(r.get("id"))
        self.assertEqual(c.call("ping").get("result"), {})
        self.assertIsNone(c.p.poll())

    def test_f69_several_bad_lines_in_a_row(self):
        c = self.start()
        for bad in ("[", "}", "\"x"):
            c.send_raw(bad)
            self.assertEqual(c.recv()["error"]["code"], -32700)
        self.assertIn("tools", c.call("tools/list")["result"])

    def test_f69_server_exits_clean_when_stdin_closes(self):
        c = self.start()
        self.assertEqual(c.close(), 0)


class Health(Server):
    def rows(self, d=None):
        p = os.path.join(d or self.hd, "recall-mcp.jsonl")
        if not os.path.exists(p):
            return []
        return [json.loads(l) for l in open(p) if l.strip()]

    def test_f69_each_tool_call_appends_one_row(self):
        c = self.start()
        out = self.text(c.tool("search_earlier_chat", {"query": "postgres"}))
        hits = len(hits_of(out))
        mid = hits_of(out)[0].split()[0]
        c.tool("open_message", {"id": mid})
        rows = self.rows()
        self.assertEqual(len(rows), 2, rows)
        for r in rows:
            self.assertEqual(set(r), {"ts", "tool", "hits", "ms"}, r)
            self.assertIs(type(r["hits"]), int)
            self.assertIs(type(r["ms"]), int)
            self.assertIsInstance(r["ts"], str)
        self.assertEqual((rows[0]["tool"], rows[0]["hits"]), ("search_earlier_chat", hits))
        self.assertEqual(rows[1]["tool"], "open_message")

    def test_f69_the_log_holds_no_query_text_and_no_snippets(self):
        c = self.start()
        c.tool("search_earlier_chat", {"query": "BILLINGMARK"})
        text = open(os.path.join(self.hd, "recall-mcp.jsonl")).read()
        for w in ("postgres", "billing", "BILLINGMARK", "nightly"):
            self.assertNotIn(w, text)

    def test_f69_no_matches_logs_zero_hits(self):
        c = self.start()
        c.tool("search_earlier_chat", {"query": "zebra giraffe antelope"})
        self.assertEqual(self.rows()[-1]["hits"], 0)

    def test_f69_the_log_honours_the_state_dir_variable(self):
        st = os.path.join(self.tmp, "otherstate")
        c = self.start(extra={"HANDOFF_STATE_DIR": st})
        c.tool("search_earlier_chat", {"query": "postgres"})
        self.assertEqual(len(self.rows(st)), 1)
        self.assertEqual(self.rows(), [])


if __name__ == "__main__":
    unittest.main()
