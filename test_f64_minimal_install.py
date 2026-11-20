"""F64 Minimal default install (code-blind: written from the F64 behaviour contract, README.md, docs/spec.md and the
output of `install.sh --help` / `--dry-run`; the installer source was not read).

Contract:
- `./install.sh` with no option installs only the core: the hooks (nudge, PreCompact handoff, post-compaction inject,
  SessionStart check, SubagentStart rules, SessionEnd index), recall.py, the recall subagent and the decisions list.
- By default it does NOT set CLAUDE_CODE_AUTO_COMPACT_WINDOW, install nightly jobs, pull an embedding model, or install
  the llm_map hook and skill.
- Opt-in flags add them: `--window N`, `--nightly`, `--semantic`, `--llm-map`.
- `--semantic` offers `ollama pull bge-m3` if `ollama` is on PATH (`--yes` pulls without asking); without ollama the
  install goes on keyword-only and prints how to get it.
- `--save-defaults` saves the opt-in flags of the run to ~/.config/lossless-handoff/install-defaults. Later runs apply
  them as if given. A command-line flag wins; `--no-semantic`, `--no-nightly`, `--no-window`, `--no-llm-map` turn one
  saved default off for that run. `--dry-run` shows which parts come from saved defaults.
- `--no-window` and `--no-nightly` stay accepted and add nothing; the installer prints one note that the default is
  now off.
- `--dry-run` lists exactly what the chosen options install. `--help` lists the new flags.
- A re-run never removes or changes an existing window value, existing nightly jobs or an existing llm_map install.
- Uninstall removes all parts, including the opt-in parts.

Labels F64.a ... F64.l are provisional AC ids (the spec has no numbers for F64 yet).
A model is NEVER pulled for real: every run that can reach `ollama` puts a stub `ollama` first on PATH (it records its
arguments and exits 0), and the `--yes` runner below refuses `--yes` without that stub.
Every run uses a temp HOME, LOSSLESS_HANDOFF_NO_LAUNCHCTL=1 and a closed embedding port (see helpers.py)."""
import json, os, re, shutil, subprocess, tempfile, time, unittest

from helpers import (IS_MACOS, LABEL_PREFIX, INSTALL_SH, REPO, installed_home, run_install, run_uninstall,
                     safe_script_env)

CORE_EVENTS = {"PreCompact", "PostToolUse", "SessionStart", "SessionEnd", "SubagentStart"}
CORE_SCRIPTS = ("precompact-handoff.py", "postcompact-inject.py", "handoff-nudge.py", "recall.py")
CORE_FILES = (".claude/hooks/precompact-handoff.py", ".claude/hooks/postcompact-inject.py",
              ".claude/hooks/handoff-nudge.py", ".claude/hooks/recall.py", ".claude/agents/recall.md")
LLM_FILES = (".claude/hooks/llm_map.py", ".claude/skills/llm-map/SKILL.md")
LLM_MARK = "<!-- lossless-handoff:llm-map-skill -->"


def seed_llm_map(home, text="# old llm_map\n"):
    """Put an old llm-map install (from a 0.12.x/0.13.x installer) into `home`. Since 0.14.0 (F66.a) no installer
    writes these files, so a test that needs them seeds them. Returns {relative path: bytes}."""
    out = {}
    for rel, body in ((LLM_FILES[0], text), (LLM_FILES[1], LLM_MARK + "\nname: llm-map\n" + text)):
        path = os.path.join(home, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(body)
        out[rel] = body.encode()
    return out
PLISTS = ("Library/LaunchAgents/%s.recall-index.plist" % LABEL_PREFIX,
          "Library/LaunchAgents/%s.handoff-reconcile.plist" % LABEL_PREFIX)
WINDOW = "CLAUDE_CODE_AUTO_COMPACT_WINDOW"
NOTE_RE = re.compile(r"(?i)\bdefault\b.*\boff\b|\boff\b.*\bdefault\b")


def read_settings(home):
    with open(os.path.join(home, ".claude", "settings.json")) as f:
        return json.loads(f.read().replace(home, "<HOME>"))


def window_of(settings):
    return (settings.get("env") or {}).get(WINDOW)


def tree(home):
    """Relative paths of the files under ~/.claude and ~/Library, without dotfiles, caches and settings backups."""
    out = set()
    for top in (".claude", "Library"):
        for d, dirs, files in os.walk(os.path.join(home, top)):
            dirs[:] = [x for x in dirs if x != "__pycache__"]
            for n in files:
                if n.startswith(".") or n.startswith("settings.json."):
                    continue
                out.add(os.path.relpath(os.path.join(d, n), home))
    return out


def without_window(settings):
    s = json.loads(json.dumps(settings))
    env = s.get("env") or {}
    env.pop(WINDOW, None)
    if env:
        s["env"] = env
    else:
        s.pop("env", None)
    return s


def commands(settings):
    """Every hook command string in settings.json."""
    out = []
    for groups in (settings.get("hooks") or {}).values():
        for g in groups:
            for h in g.get("hooks", []):
                if "command" in h:
                    out.append(h["command"])
    return out


STUB = '#!/bin/sh\necho "$@" >> "%s"\nexit 0\n'
DEFAULTS_REL = ".config/lossless-handoff/install-defaults"


def make_stub_ollama(tmp):
    """(PATH with a stub `ollama` first, log file). The stub records its arguments and exits 0."""
    d = os.path.join(tmp, "stubbin")
    os.makedirs(d)
    log = os.path.join(tmp, "ollama.log")
    p = os.path.join(d, "ollama")
    with open(p, "w") as f:
        f.write(STUB % log)
    os.chmod(p, 0o755)
    return d + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"), log


def path_without_ollama(tmp):
    """A PATH with the same tools as the real one but no `ollama` (directories that hold it are mirrored)."""
    out = []
    for i, d in enumerate(os.environ.get("PATH", "/usr/bin:/bin").split(os.pathsep)):
        if not os.path.isdir(d):
            continue
        if not os.path.exists(os.path.join(d, "ollama")):
            out.append(d)
            continue
        m = os.path.join(tmp, "mirror%d" % i)
        os.makedirs(m)
        for n in os.listdir(d):
            if n != "ollama":
                try:
                    os.symlink(os.path.join(d, n), os.path.join(m, n))
                except OSError:
                    pass
        out.append(m)
    return os.pathsep.join(out)


def run_install_yes(home, *args, path):
    """Like run_install but allows --yes. SAFETY: only when `path` starts with a stub ollama that cannot pull."""
    first = path.split(os.pathsep)[0]
    stub = os.path.join(first, "ollama")
    assert os.path.isfile(stub) and "stubbin" in first, "refusing --yes without a stub ollama first on PATH"
    body = open(stub).read()
    assert "exit 0" in body and "pull" not in body
    return subprocess.run(["bash", INSTALL_SH, *args], env=safe_script_env(home, None, path), cwd=REPO,
                          stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=180)


def plan(out):
    """The dry-run text without the `not selected (opt-in: ...)` notes: what the chosen options install."""
    return "\n".join(l for l in out.split("\n") if "not selected" not in l)


def dry_run(*args, home=None, path=None):
    own = home is None
    if own:
        home = os.path.realpath(tempfile.mkdtemp(prefix="f64dry-"))
    try:
        r = run_install(home, "--dry-run", *args, path=path)
        return r, sorted(os.listdir(home))
    finally:
        if own:
            shutil.rmtree(home, ignore_errors=True)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="f64-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self.state = os.path.join(self.home, ".local", "state", "claude-handoffs")

    def sp(self):
        return os.path.join(self.home, ".claude", "settings.json")

    def put_settings(self, d):
        os.makedirs(os.path.dirname(self.sp()), exist_ok=True)
        with open(self.sp(), "w") as f:
            json.dump(d, f)

    def wait_first_index(self):
        """An install may start a background index; wait so that it cannot change a file during a comparison."""
        log = os.path.join(self.state, "recall", "index-all.log")
        end = time.time() + 20
        while time.time() < end:
            if os.path.exists(log) and os.path.getsize(log) > 0:
                break
            time.sleep(0.2)
        time.sleep(0.5)

    def install(self, *args):
        r = run_install(self.home, *args)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.wait_first_index()
        return r

    def uninstall(self, *args):
        r = run_uninstall(self.home, *args)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r

    def p(self, rel):
        return os.path.join(self.home, rel)

    def bytes_of(self, rel):
        with open(self.p(rel), "rb") as f:
            return f.read()


# ------------------------------------------------------------------ F64.a: the default install is the core only
class DefaultInstall(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home, cls.res = installed_home()
        cls.settings = read_settings(cls.home)

    def test_f64_a_core_hook_events_present(self):
        self.assertTrue(CORE_EVENTS <= set(self.settings.get("hooks", {})), sorted(self.settings.get("hooks", {})))

    def test_f64_a_core_scripts_are_registered(self):
        cmds = "\n".join(commands(self.settings))
        for n in CORE_SCRIPTS:
            self.assertIn(n, cmds, n)

    def test_f64_a_session_start_check_and_decisions_list_are_registered(self):
        starts = [h["command"] for g in self.settings["hooks"]["SessionStart"] for h in g.get("hooks", [])]
        self.assertTrue(any("--check" in c for c in starts), starts)
        self.assertTrue(any("--ledger" in c for c in starts), starts)

    def test_f64_a_core_files_exist(self):
        for rel in CORE_FILES:
            self.assertTrue(os.path.isfile(os.path.join(self.home, rel)), rel)

    def test_f64_b_no_window_in_settings(self):
        self.assertIsNone(window_of(self.settings), self.settings.get("env"))
        self.assertNotIn(WINDOW, json.dumps(self.settings))

    def test_f64_c_no_nightly_jobs(self):
        self.assertFalse([p for p in tree(self.home) if "LaunchAgents" in p and LABEL_PREFIX in p], sorted(tree(self.home)))
        la = os.path.join(self.home, "Library", "LaunchAgents")
        self.assertEqual([n for n in (os.listdir(la) if os.path.isdir(la) else []) if "lossless" in n.lower()], [])

    def test_f64_d_no_llm_map_hook_or_skill(self):
        for rel in LLM_FILES:
            self.assertFalse(os.path.exists(os.path.join(self.home, rel)), rel)
        self.assertNotIn("llm_map", json.dumps(self.settings))
        self.assertNotIn("llm-map", json.dumps(self.settings))
        self.assertFalse(os.path.exists(os.path.join(self.home, ".claude", "skills", "llm-map")))

    def test_f64_e_default_prints_no_default_off_note(self):
        out = self.res.stdout + self.res.stderr
        self.assertEqual([l for l in out.split("\n") if NOTE_RE.search(l)], [], out)


# ------------------------------------------------------------------ F64.f: each opt-in flag adds exactly its part
class OptIn(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base_home, _ = installed_home()
        cls.base_settings = read_settings(cls.base_home)
        cls.base_tree = tree(cls.base_home)

    def test_f64_f_window_flag_sets_only_the_window(self):
        home, _ = installed_home("--window", "250000")
        s = read_settings(home)
        self.assertEqual(str(window_of(s)), "250000")
        self.assertEqual(without_window(s), without_window(self.base_settings))
        self.assertEqual(tree(home), self.base_tree)

    def test_f64_f_window_flag_does_not_add_nightly_or_llm_map(self):
        home, _ = installed_home("--window", "250000")
        for rel in LLM_FILES + PLISTS:
            self.assertFalse(os.path.exists(os.path.join(home, rel)), rel)

    def test_f64_g_nightly_flag_adds_only_the_nightly_jobs(self):
        home, _ = installed_home("--nightly")
        self.assertEqual(read_settings(home), self.base_settings)
        want = self.base_tree | (set(PLISTS) if IS_MACOS else set())
        self.assertEqual(tree(home), want)
        self.assertIsNone(window_of(read_settings(home)))

    @unittest.skipUnless(IS_MACOS, "LaunchAgents exist on macOS only")
    def test_f64_g_nightly_plists_are_valid(self):
        import plistlib
        home, _ = installed_home("--nightly")
        for rel in PLISTS:
            with open(os.path.join(home, rel), "rb") as f:
                d = plistlib.load(f)
            self.assertEqual(d["Label"], os.path.basename(rel)[:-len(".plist")])

# ------------------------------------------------------------------ F64.i: old flags are accepted and add nothing
class OldFlags(Base):
    def run_flag(self, *flags):
        r = self.install(*flags)
        s = read_settings(self.home)
        self.assertIsNone(window_of(s))
        self.assertFalse(set(PLISTS) & tree(self.home))
        self.assertFalse(set(LLM_FILES) & tree(self.home))
        return (r.stdout + r.stderr).split("\n")

    def test_f64_i_no_window_exits_0_with_one_note(self):
        notes = [l for l in self.run_flag("--no-window") if NOTE_RE.search(l)]
        self.assertEqual(len(notes), 1, notes)

    def test_f64_i_no_nightly_exits_0_with_one_note(self):
        notes = [l for l in self.run_flag("--no-nightly") if NOTE_RE.search(l)]
        self.assertEqual(len(notes), 1, notes)

    def test_f64_i_both_old_flags_exit_0_and_print_the_note(self):
        notes = [l for l in self.run_flag("--no-window", "--no-nightly") if NOTE_RE.search(l)]
        self.assertTrue(1 <= len(notes) <= 2, notes)

    def test_f64_i_old_flags_install_the_same_as_the_default(self):
        self.run_flag("--no-window", "--no-nightly")
        base, _ = installed_home()
        self.assertEqual(tree(self.home), tree(base))
        self.assertEqual(read_settings(self.home), read_settings(base))


# ------------------------------------------------------------------ F64.j: --dry-run and --help
class DryRunAndHelp(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="f64dr-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.path, self.log = make_stub_ollama(self.tmp)

    def tearDown(self):
        self.assertFalse(os.path.exists(self.log), "--dry-run called ollama")

    def test_f64_j_help_lists_the_new_flags(self):
        home = os.path.realpath(tempfile.mkdtemp(prefix="f64help-"))
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        r = run_install(home, "--help")
        self.assertEqual(r.returncode, 0, r.stderr)
        for f in ("--window", "--nightly", "--semantic", "--save-defaults", "--no-window", "--no-nightly", "--dry-run"):
            self.assertIn(f, r.stdout, f)
        self.assertEqual(sorted(os.listdir(home)), [])

    def test_f64_j_default_dry_run_lists_core_and_nothing_else(self):
        r, left = dry_run(path=self.path)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(left, [], "--dry-run wrote into HOME")
        out = r.stdout + r.stderr
        for word in ("PreCompact", "SessionStart", "SessionEnd", "SubagentStart", "recall.py", "recall.md",
                     "precompact-handoff.py", "postcompact-inject.py", "handoff-nudge.py"):
            self.assertIn(word, out, word)
        for word in (WINDOW, "LaunchAgent", "llm_map", "llm-map", "bge-m3", "ollama pull"):
            self.assertNotIn(word, plan(out), word)

    def test_f64_j_dry_run_window_lists_the_window_only(self):
        r, left = dry_run("--window", "123456", path=self.path)
        out = r.stdout + r.stderr
        self.assertEqual((r.returncode, left), (0, []), out)
        self.assertRegex(out, WINDOW + r"\s*=?\s*123456")
        for word in ("LaunchAgent", "llm_map", "llm-map", "bge-m3"):
            self.assertNotIn(word, plan(out), word)

    @unittest.skipUnless(IS_MACOS, "the nightly jobs are LaunchAgents on macOS only")
    def test_f64_j_dry_run_nightly_lists_both_jobs_only(self):
        r, left = dry_run("--nightly", path=self.path)
        out = r.stdout + r.stderr
        self.assertEqual((r.returncode, left), (0, []), out)
        self.assertIn("recall-index", out)
        self.assertIn("handoff-reconcile", out)
        for word in (WINDOW, "llm_map", "llm-map", "bge-m3"):
            self.assertNotIn(word, plan(out), word)

    def test_f64_j_dry_run_llm_map_flag_plans_no_llm_map_install(self):
        # F66.a: --llm-map is still accepted but installs nothing
        r, left = dry_run("--llm-map", path=self.path)
        out = r.stdout + r.stderr
        self.assertEqual((r.returncode, left), (0, []), out)
        self.assertNotIn("llm_map.py", plan(out))
        self.assertNotIn("SKILL.md", plan(out))
        for word in (WINDOW, "LaunchAgent", "bge-m3"):
            self.assertNotIn(word, plan(out), word)

    def test_f64_j_dry_run_semantic_lists_the_model_pull_and_changes_nothing(self):
        # SAFETY: --dry-run only. A real --semantic run would pull the bge-m3 model from the network.
        r, left = dry_run("--semantic", path=self.path)
        out = r.stdout + r.stderr
        self.assertEqual((r.returncode, left), (0, []), out)
        self.assertIn("bge-m3", out)
        for word in (WINDOW, "LaunchAgent", "llm_map", "llm-map"):
            self.assertNotIn(word, plan(out), word)

    def test_f64_j_dry_run_all_options_lists_every_part(self):
        r, left = dry_run("--window", "123456", "--nightly", "--semantic", path=self.path)
        out = r.stdout + r.stderr
        self.assertEqual((r.returncode, left), (0, []), out)
        for word in (WINDOW, "123456", "bge-m3"):
            self.assertIn(word, out, word)
        if IS_MACOS:
            self.assertIn("recall-index", out)
            self.assertIn("handoff-reconcile", out)


# ------------------------------------------------------------------ F64.m: --semantic (meaning search) is opt-in
class OllamaBase(Base):
    def setUp(self):
        super().setUp()
        self.path, self.log = make_stub_ollama(self.tmp)

    def pulls(self):
        if not os.path.exists(self.log):
            return []
        return [l.split() for l in open(self.log).read().split("\n") if l.strip() and l.split()[0] == "pull"]

    def yes(self, *args, home=None, path=None):
        r = run_install_yes(home or self.home, *args, path=path or self.path)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.wait_first_index()
        return r

    def defaults_file(self, home=None):
        return os.path.join(home or self.home, DEFAULTS_REL)


class Semantic(OllamaBase):
    def test_f64_m_default_install_never_calls_ollama(self):
        self.yes()
        self.assertEqual(self.pulls(), [])

    def test_f64_m_default_install_without_yes_never_calls_ollama(self):
        r = run_install(self.home, path=self.path)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.wait_first_index()
        self.assertEqual(self.pulls(), [])

    def test_f64_m_semantic_with_yes_pulls_bge_m3_through_the_stub(self):
        self.yes("--semantic", "--yes")
        self.assertIn(["pull", "bge-m3"], self.pulls())
        s = read_settings(self.home)
        self.assertIsNone(window_of(s))
        self.assertFalse((set(PLISTS) | set(LLM_FILES)) & tree(self.home))

    def test_f64_m_semantic_without_yes_and_without_a_terminal_does_not_pull(self):
        r = run_install(self.home, "--semantic", path=self.path)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.wait_first_index()
        self.assertEqual(self.pulls(), [])

    def test_f64_m_semantic_without_ollama_installs_and_prints_how_to_get_it(self):
        r = run_install(self.home, "--semantic", path=path_without_ollama(self.tmp))
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 0, out)
        self.wait_first_index()
        self.assertTrue(set(CORE_FILES) <= tree(self.home))
        self.assertRegex(out, r"(?i)ollama")


# ------------------------------------------------------------------ F64.n: --save-defaults
class SavedDefaults(OllamaBase):
    def test_f64_n_save_defaults_writes_the_file_with_semantic_on(self):
        self.yes("--semantic", "--yes", "--save-defaults")
        self.assertTrue(os.path.isfile(self.defaults_file()))
        self.assertIn("semantic=1", open(self.defaults_file()).read().split("\n"))  # spec F64.e line format
        self.assertEqual(len(self.pulls()), 1)

    def test_f64_n_plain_install_applies_the_saved_semantic_default(self):
        self.yes("--semantic", "--yes", "--save-defaults")
        n = len(self.pulls())
        self.yes("--yes")
        self.assertEqual(len(self.pulls()), n + 1)
        self.assertEqual(self.pulls()[-1], ["pull", "bge-m3"])

    def test_f64_n_no_semantic_turns_the_saved_default_off_for_one_run(self):
        self.yes("--semantic", "--yes", "--save-defaults")
        n = len(self.pulls())
        self.yes("--yes", "--no-semantic")
        self.assertEqual(len(self.pulls()), n)
        self.yes("--yes")  # the file is unchanged: the next plain run pulls again
        self.assertEqual(len(self.pulls()), n + 1)

    def test_f64_n_dry_run_mentions_the_saved_default(self):
        self.yes("--semantic", "--yes", "--save-defaults")
        n = len(self.pulls())
        r = run_install(self.home, "--dry-run", path=self.path)
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 0, out)
        self.assertIn("bge-m3", out)
        self.assertRegex(out, r"(?i)saved default|install-defaults|from saved")
        self.assertEqual(len(self.pulls()), n)

    def test_f64_n_dry_run_without_a_defaults_file_does_not_mention_saved_defaults(self):
        r = run_install(self.home, "--dry-run", path=self.path)
        out = r.stdout + r.stderr
        self.assertNotRegex(out, r"(?i)saved default|install-defaults|from saved")

    def test_f64_n_dry_run_with_save_defaults_writes_nothing(self):
        r = run_install(self.home, "--dry-run", "--save-defaults", "--nightly", path=self.path)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(os.path.exists(self.defaults_file()))
        self.assertEqual(sorted(os.listdir(self.home)), [])

    def test_f64_n_saved_window_and_nightly_apply_to_a_plain_run(self):
        self.install("--window", "250000", "--nightly", "--save-defaults")
        lines = open(self.defaults_file()).read().split("\n")
        for want in ("window=250000", "nightly=1"):  # spec F64.e line format
            self.assertIn(want, lines)
        home2 = os.path.join(self.tmp, "home2")
        os.makedirs(os.path.join(home2, ".config", "lossless-handoff"))
        shutil.copy(self.defaults_file(), self.defaults_file(home2))
        r = run_install(home2)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(str(window_of(read_settings(home2))), "250000")
        want = set(PLISTS) if IS_MACOS else set()
        self.assertTrue(want <= tree(home2), sorted(tree(home2)))

    def test_f64_n_command_line_flag_wins_and_no_flags_turn_parts_off(self):
        self.install("--window", "250000", "--nightly", "--save-defaults")
        for i, (args, check) in enumerate((
                (("--window", "300000"), lambda h: self.assertEqual(str(window_of(read_settings(h))), "300000")),
                (("--no-window",), lambda h: self.assertIsNone(window_of(read_settings(h)))),
                (("--no-nightly",), lambda h: self.assertFalse(set(PLISTS) & tree(h))))):
            h = os.path.join(self.tmp, "h%d" % i)
            os.makedirs(os.path.join(h, ".config", "lossless-handoff"))
            shutil.copy(self.defaults_file(), self.defaults_file(h))
            r = run_install(h, *args)
            self.assertEqual(r.returncode, 0, args and (r.stdout + r.stderr))
            check(h)

    def test_f64_n_no_flag_with_save_defaults_removes_that_default_from_the_file(self):
        self.install("--window", "250000", "--nightly", "--save-defaults")
        self.install("--no-nightly", "--save-defaults")
        lines = open(self.defaults_file()).read().split("\n")
        self.assertNotIn("nightly=1", lines)
        self.assertIn("window=250000", lines)
        # the parts that were installed stay (spec F64.d: a --no-* flag only skips adding a part)
        self.assertEqual(str(window_of(read_settings(self.home))), "250000")

    def test_f64_n_uninstall_keeps_the_defaults_file_and_purge_deletes_it(self):
        self.install("--window", "250000", "--save-defaults")
        self.uninstall()
        self.assertTrue(os.path.isfile(self.defaults_file()), "spec F64.f: uninstall keeps the defaults file")
        self.uninstall("--purge")
        self.assertFalse(os.path.exists(self.defaults_file()), "spec F64.f: --purge deletes the defaults file")

    def test_f64_n_install_without_save_defaults_writes_no_file(self):
        self.install("--window", "250000")
        self.assertFalse(os.path.exists(self.defaults_file()))

    def test_f64_n_saved_defaults_do_not_change_uninstall(self):
        self.install("--window", "250000", "--save-defaults")
        self.uninstall()
        for rel in CORE_FILES:
            self.assertFalse(os.path.exists(self.p(rel)), rel)


# ------------------------------------------------------------------ F64.k: a re-run never removes or changes
class Rerun(Base):
    def test_f64_k_default_rerun_keeps_an_existing_window(self):
        self.put_settings({"env": {WINDOW: "300000", "FOO": "1"}})
        self.install()
        self.assertEqual(str(window_of(read_settings(self.home))), "300000")
        self.install()
        s = read_settings(self.home)
        self.assertEqual(str(window_of(s)), "300000")
        self.assertEqual(s["env"]["FOO"], "1")

    def test_f64_k_window_flag_does_not_change_an_existing_value(self):
        self.put_settings({"env": {WINDOW: "300000"}})
        self.install("--window", "500000")
        self.assertEqual(str(window_of(read_settings(self.home))), "300000")

    def test_f64_k_no_window_flag_keeps_an_existing_value(self):
        self.put_settings({"env": {WINDOW: "300000"}})
        self.install("--no-window")
        self.assertEqual(str(window_of(read_settings(self.home))), "300000")

    def test_f64_k_window_set_by_a_flag_survives_a_default_rerun(self):
        self.install("--window", "250000")
        self.install()
        self.assertEqual(str(window_of(read_settings(self.home))), "250000")

    @unittest.skipUnless(IS_MACOS, "the nightly jobs are LaunchAgents on macOS only")
    def test_f64_k_default_rerun_keeps_existing_nightly_jobs(self):
        self.install("--nightly")
        before = {rel: self.bytes_of(rel) for rel in PLISTS}
        self.install()
        for rel in PLISTS:
            self.assertEqual(self.bytes_of(rel), before[rel], rel)
        self.install("--no-nightly")
        for rel in PLISTS:
            self.assertEqual(self.bytes_of(rel), before[rel], rel)

    def test_f64_k_no_flags_rerun_never_turns_off_an_installed_part(self):
        self.install("--window", "250000", "--nightly")
        for args in (("--no-nightly",), ("--no-window",), ()):
            self.install(*args)
            self.assertTrue(set(PLISTS) <= tree(self.home) or not IS_MACOS, args)
            self.assertEqual(str(window_of(read_settings(self.home))), "250000", args)

    def test_f64_k_rerun_with_a_flag_only_adds(self):
        self.install()
        core = tree(self.home)
        self.install("--nightly")
        added = core | (set(PLISTS) if IS_MACOS else set())
        self.assertEqual(tree(self.home), added)
        self.install("--window", "250000")
        self.assertEqual(tree(self.home), added)
        self.assertEqual(str(window_of(read_settings(self.home))), "250000")


# ------------------------------------------------------------------ F64.l: uninstall removes every part
class Uninstall(Base):
    def test_f64_l_uninstall_removes_the_opt_in_parts(self):
        before = {"permissions": {"allow": ["Bash(ls:*)"]}, "env": {"FOO": "1"}}
        self.put_settings(before)
        self.install("--window", "250000", "--nightly")
        self.assertEqual(str(window_of(read_settings(self.home))), "250000")
        self.uninstall()
        for rel in PLISTS + CORE_FILES:
            self.assertFalse(os.path.exists(self.p(rel)), rel)
        with open(self.sp()) as f:
            self.assertEqual(json.load(f), before)

    def test_f64_l_uninstall_of_a_default_install_restores_settings(self):
        before = {"permissions": {"allow": ["Bash(ls:*)"]}}
        self.put_settings(before)
        self.install()
        self.uninstall()
        with open(self.sp()) as f:
            self.assertEqual(json.load(f), before)
        for rel in CORE_FILES:
            self.assertFalse(os.path.exists(self.p(rel)), rel)


if __name__ == "__main__":
    unittest.main()
