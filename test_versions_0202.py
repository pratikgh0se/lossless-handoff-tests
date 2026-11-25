"""Versions of release 0.20.2 (hooks 1.22.2): product 0.20.2 (install.sh), HOOK_VERSION 1.22.2 in every hook that has it. The default
install does not change: auto-recall and recall-mcp stay opt-in. Code-blind: written from contract-0.17.md."""
import json, os, re, shutil, tempfile, unittest

from helpers import HOOKS_DIR, REPO, installed_home, run_install


class Versions(unittest.TestCase):
    def test_install_sh_version_is_0_20_2(self):
        home = os.path.realpath(tempfile.mkdtemp(prefix="v17-"))
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        r = run_install(home, "--version")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("0.20.2", r.stdout + r.stderr)

    def test_installed_manifest_version_is_1_22_2(self):
        home, _ = installed_home()
        with open(os.path.join(home, ".claude", "hooks", ".handoff-manifest.json")) as f:
            self.assertEqual(json.load(f)["version"], "1.22.2")

    def test_changelog_has_0_20_2_first(self):
        with open(os.path.join(REPO, "CHANGELOG.md")) as f:
            heads = re.findall(r"(?m)^## \[([0-9.]+)\]", f.read())
        self.assertEqual(heads[0], "0.20.2")

    def test_hook_version_constants_are_1_22_2_in_every_hook_that_has_one(self):
        for n in ("precompact-handoff.py", "postcompact-inject.py", "auto-recall.py", "recall-mcp.py", "reanchor.py",
                  "claim-guard.py", "history-guard.py", "action-guard.py", "guard_common.py"):
            p = os.path.join(HOOKS_DIR, n)
            self.assertTrue(os.path.isfile(p), n)
            with open(p) as f:
                self.assertRegex(f.read(), r"""HOOK_VERSION\s*=\s*["']1\.22\.1["']""", n)

    def test_default_install_does_not_add_auto_recall_or_recall_mcp(self):
        home, _ = installed_home()
        for n in ("auto-recall.py", "recall-mcp.py"):  # F81.a: .recall-rules is part of the default install
            self.assertFalse(os.path.exists(os.path.join(home, ".claude", "hooks", n)), n)


if __name__ == "__main__":
    unittest.main()
