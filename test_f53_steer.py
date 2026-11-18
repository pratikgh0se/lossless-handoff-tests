"""F53 Steer Claude Code's own summary: ACs 229-234 of docs/spec.md. Code-blind: written from the spec only.
The PreCompact hook prints guidance on stdout; Claude Code uses it as instructions for the compaction summary.
Temp HOME, no `claude` on PATH (summary and ledger off by the helpers)."""
import json, os, subprocess, sys, unittest

from helpers import HookCase, PRE, POST, user, asst

BLOCK = """Lossless Handoff guidance for this summary:
- Quote the user's own words for every decision, rule and correction, with the date if known.
- Keep exact commands, file paths, numbers, ids and error text. Do not paraphrase them.
- List work that is still running (agents, jobs, background commands) with its ids and state.
- End with the exact next step.
- A structured handoff and the project decisions list are injected after this compaction, and the full transcript stays searchable with recall, so keep old history short and keep the current state complete.
"""
HEAD = "Lossless Handoff guidance for this summary:"


class Steer(HookCase):
    def setUp(self):
        super().setUp()
        self.write_transcript([user("Please remember that we decided to use the blue palette for the site."),
                               asst("Understood. I will use the blue palette.")])

    def run_event(self, payload, extra=None):
        r = self.run_pre(payload, extra=extra)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotEqual(r.returncode, 2)
        return r

    def assert_block(self, r):
        self.assertEqual(r.stdout.rstrip("\n"), BLOCK.rstrip("\n"), repr(r.stdout))

    def test_ac229_auto_prints_block(self):
        r = self.run_event(self.payload("S"))
        self.assert_block(r)
        self.assertTrue(os.path.getsize(os.path.join(self.hd, "S-latest.md")) > 0)

    def test_ac229_block_printed_once(self):
        r = self.run_event(self.payload("S"))
        self.assertEqual(r.stdout.count(HEAD), 1)

    def test_ac230_custom_instructions_win(self):
        p = self.payload("S", trigger="manual")
        p["custom_instructions"] = "keep the API notes"
        r = self.run_event(p)
        self.assertEqual(r.stdout, "")
        self.assertTrue(os.path.getsize(os.path.join(self.hd, "S-latest.md")) > 0)

    def test_ac230_partner_auto_run_prints_block_in_same_setup(self):
        p = self.payload("S", trigger="manual")
        p["custom_instructions"] = "keep the API notes"
        self.assertEqual(self.run_event(p).stdout, "")
        self.assert_block(self.run_event(self.payload("S")))

    def test_ac231_empty_custom_instructions(self):
        p = self.payload("S", trigger="manual")
        p["custom_instructions"] = ""
        r = self.run_event(p)
        self.assert_block(r)
        self.assertTrue(os.path.getsize(os.path.join(self.hd, "S-latest.md")) > 0)

    def test_ac232_off_switch(self):
        r = self.run_event(self.payload("S"), extra={"HANDOFF_COMPACT_STEER": "0"})
        self.assertEqual(r.stdout, "")
        self.assertTrue(os.path.getsize(os.path.join(self.hd, "S-latest.md")) > 0)

    def test_ac232_partner_default_prints_block_in_same_setup(self):
        self.assertEqual(self.run_event(self.payload("S"), extra={"HANDOFF_COMPACT_STEER": "0"}).stdout, "")
        self.assert_block(self.run_event(self.payload("S")))

    def test_ac233_partner_precompact_prints_block_in_same_home(self):
        r = subprocess.run([sys.executable, POST, "--check"], input="{}", capture_output=True, text=True,
                           env=self.env(None), timeout=30)
        self.assertNotIn(HEAD, r.stdout + r.stderr)
        self.assert_block(self.run_event(self.payload("S")))

    def test_ac233_cli_modes_print_no_guidance(self):
        r = subprocess.run([sys.executable, POST, "--check"], input="{}", capture_output=True, text=True,
                           env=self.env(None), timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn(HEAD, r.stdout + r.stderr)
        for args in (("--reconcile", "--days", "1"), ("--prove", "--days", "1")):
            r = subprocess.run([sys.executable, PRE, *args], stdin=subprocess.DEVNULL, capture_output=True,
                               text=True, env=self.env(None), timeout=120)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertNotIn(HEAD, r.stdout + r.stderr, args)

    def test_ac234_subagent_prints_block(self):
        p = self.payload("S")
        p["agent_id"] = "a1"
        r = self.run_event(p)
        self.assert_block(r)
        self.assertTrue(os.path.getsize(os.path.join(self.hd, "S-a-a1-latest.md")) > 0)

    def test_ac235_health_row_printed(self):
        self.run_event(self.payload("S"))
        self.assertEqual(self.health()["steer"], "printed")

    def test_ac235_health_row_custom(self):
        p = self.payload("S", trigger="manual")
        p["custom_instructions"] = "keep the API notes"
        self.run_event(p)
        self.assertEqual(self.health()["steer"], "custom")

    def test_ac235_health_row_off(self):
        self.run_event(self.payload("S"), extra={"HANDOFF_COMPACT_STEER": "0"})
        self.assertEqual(self.health()["steer"], "off")

    def test_ac235_subagent_row_printed(self):
        p = self.payload("S")
        p["agent_id"] = "a1"
        self.run_event(p)
        self.assertEqual(self.health()["steer"], "printed")


if __name__ == "__main__":
    unittest.main()
