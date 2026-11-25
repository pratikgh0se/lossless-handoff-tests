"""F90.h One version source: every version in the product equals the `VERSION` file. The tests read `VERSION` and never
write a version number. Code-blind: written from the F90 text only."""
import glob, json, os, re, shutil, tempfile, unittest

from helpers import HOOKS_DIR, REPO, VERSION_FILE, PRODUCT_VERSION, HOOKS_VERSION, installed_home, run_install

SEMVER = r"[0-9]+\.[0-9]+\.[0-9]+"


class OneVersionSource(unittest.TestCase):
    def test_version_file_has_two_lines_product_and_hooks(self):
        self.assertTrue(os.path.isfile(VERSION_FILE), "no VERSION file in the repo root")
        with open(VERSION_FILE) as f:
            lines = [l for l in f.read().split("\n") if l != ""]
        self.assertEqual(len(lines), 2, lines)
        self.assertRegex(lines[0], r"^product=%s$" % SEMVER)
        self.assertRegex(lines[1], r"^hooks=%s$" % SEMVER)

    def test_install_sh_reports_the_product_version(self):
        home = os.path.realpath(tempfile.mkdtemp(prefix="f90v-"))
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        r = run_install(home, "--version")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(PRODUCT_VERSION, r.stdout + r.stderr)

    def test_every_hook_version_constant_equals_the_hooks_version(self):
        files = sorted(glob.glob(os.path.join(HOOKS_DIR, "*.py")) + glob.glob(os.path.join(HOOKS_DIR, "lossless_handoff", "*.py")))
        found = 0
        for p in files:
            with open(p) as f:
                for m in re.finditer(r"""(?m)^\s*HOOK_VERSION\s*=\s*["'](%s)["']""" % SEMVER, f.read()):
                    found += 1
                    self.assertEqual(m.group(1), HOOKS_VERSION, "HOOK_VERSION in %s" % os.path.basename(p))
        self.assertGreaterEqual(found, 3, "fewer than 3 HOOK_VERSION constants found")

    def test_installed_manifest_version_equals_the_hooks_version(self):
        home, _ = installed_home()
        with open(os.path.join(home, ".claude", "hooks", ".handoff-manifest.json")) as f:
            self.assertEqual(json.load(f)["version"], HOOKS_VERSION)

    def test_top_changelog_entry_equals_the_product_version(self):
        with open(os.path.join(REPO, "CHANGELOG.md")) as f:
            heads = re.findall(r"(?m)^## \[(%s)\]" % SEMVER, f.read())
        self.assertEqual(heads[0], PRODUCT_VERSION)

    def test_readme_version_line_names_both_versions(self):
        with open(os.path.join(REPO, "README.md")) as f:
            lines = f.read().split("\n")
        self.assertTrue([l for l in lines if PRODUCT_VERSION in l and HOOKS_VERSION in l],
                        "no README line names %s and %s" % (PRODUCT_VERSION, HOOKS_VERSION))


if __name__ == "__main__":
    unittest.main()
