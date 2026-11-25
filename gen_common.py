"""F90 generic layer: a seeded transcript generator (stdlib only, deterministic per seed) for the F90.f shape matrix,
and generators for the G1 / G2 grammars of F90.a. Code-blind: written from the F90 text only.

Rules for the tests that use this module:
- every failure message prints the seed and the shape (use `tag(seed, shape)`);
- every generated message holds a unique text (a token with the seed, the shape and the index);
- a test asserts a relation to the generated input, not a literal."""
import json, os, random, re

SEEDS = list(range(1, 21))  # at least 20 seeds (F90 task 1)

# ---- the F90.f shape matrix. Each shape is a set of features. `main` and `sub` choose the file kind.
FEATURES = ("main", "sub", "user_str", "user_blocks", "tool_str", "tool_blocks", "thinking", "unicode", "long",
            "trailing_ws", "secrets", "boundary", "huge")
MATRIX = {
    "main-plain": {"main", "user_str"},
    "main-user-blocks": {"main", "user_blocks"},
    "sub-plain": {"sub", "user_str"},
    "sub-tool-blocks": {"sub", "user_blocks", "tool_blocks"},
    "main-tool-str": {"main", "user_str", "tool_str"},
    "main-tool-blocks": {"main", "user_str", "tool_blocks"},
    "main-thinking": {"main", "user_str", "thinking"},
    "main-unicode": {"main", "user_blocks", "unicode"},
    "main-long": {"main", "user_str", "long"},
    "main-trailing-ws": {"main", "user_str", "trailing_ws"},
    "main-secrets": {"main", "user_str", "secrets", "tool_blocks"},
    "main-boundary": {"main", "user_str", "boundary", "tool_str"},
    "main-huge": {"main", "user_str", "huge"},
    "all-in-one": {"main", "user_blocks", "tool_blocks", "thinking", "unicode", "long", "trailing_ws", "secrets",
                   "boundary"},
    "sub-all-in-one": {"sub", "user_blocks", "tool_blocks", "thinking", "unicode", "long", "trailing_ws", "secrets",
                       "boundary"},
}
CAP_CHARS = 40000  # F44.12: `open --full` prints the first 40000 chars of a message, then a cut marker

WORDS = ("alpha", "bravo", "delta", "echo", "fox", "gamma", "hotel", "india", "kilo", "lima", "mike", "nova", "oscar",
         "papa", "quebec", "romeo", "sierra", "tango", "uniform", "victor", "whisky", "yankee", "zulu")
UNI = ("café naïve", "日本語のテキスト", "emoji \U0001F600\U0001F680\U0001F9EA",
       "مرحبا", "z̈ combining", "ßüñ")


def tag(seed, shape):
    return "[seed=%s shape=%s]" % (seed, shape)


def sid_for(seed, n=0):
    """A session id of 36 chars; the first 8 chars are lower-case hex and differ per (seed, n)."""
    r = random.Random("sid-%s-%s" % (seed, n))
    h = "".join(r.choice("0123456789abcdef") for _ in range(32))
    return "%s-%s-4%s-8%s-%s" % (h[:8], h[8:12], h[13:16], h[17:20], h[20:32])


class Msg:
    def __init__(self, line, role, texts, kind):
        self.line, self.role, self.texts, self.kind = line, role, texts, kind  # texts: expected pieces, in order


class Transcript:
    def __init__(self, seed, shape):
        self.seed, self.shape = seed, shape
        self.features = MATRIX[shape]
        self.sid = sid_for(seed)
        self.agent = None
        self.lines = []
        self.msgs = []
        self.planted = []  # strings that must never survive redact(): (needle,)
        self.rng = random.Random("%s/%s" % (seed, shape))
        self.tool_n = 0

    # ---- text
    def text(self, idx, kind):
        r, f = self.rng, self.features
        words = " ".join(r.choice(WORDS) for _ in range(r.randint(3, 12)))
        t = "TOK%sS%sI%d%s %s" % (self.seed, sum(map(ord, self.shape)), idx, kind[0], words)
        if "unicode" in f:
            t += " " + r.choice(UNI) + "\n" + r.choice(UNI)
        if r.random() < 0.3:
            t += "\nsecond line " + r.choice(WORDS)
        if "long" in f and idx % 4 == 1:
            while len(t) < 20000 + r.randint(0, 3000):
                t += " " + " ".join(r.choice(WORDS) for _ in range(30))
        if "huge" in f and idx == 1:
            while len(t) < CAP_CHARS + 5000 + r.randint(0, 2000):
                t += " " + " ".join(r.choice(WORDS) for _ in range(30))
        if "trailing_ws" in f and idx % 2 == 0:
            t += r.choice(["  ", " \t ", "\t\t", "   \t"])
        return t

    def add(self, entry, role, texts, kind):
        self.lines.append(json.dumps(entry))
        self.msgs.append(Msg(len(self.lines), role, texts, kind))

    def rec(self, kind, content, **flags):
        d = {"type": kind, "sessionId": self.sid, "cwd": self.cwd,
             "timestamp": "2026-03-%02dT12:%02d:%02dZ" % (1 + self.seed % 27, len(self.lines) // 60, len(self.lines) % 60),
             "message": {"role": kind, "content": content}}
        if self.agent:
            d.update(isSidechain=True, agentId=self.agent)
        d.update(flags)
        return d

    def build(self, cwd, secrets=None):
        """Fill the transcript. `secrets` is a list of (raw text, [parts that must never survive])."""
        self.cwd = cwd
        f, r = self.features, self.rng
        if "sub" in f:
            self.agent = "".join(r.choice("0123456789abcdef") for _ in range(8))
        n_turns = r.randint(3, 6)
        idx = 0
        for turn in range(n_turns):
            idx += 1
            t = self.text(idx, "user")
            if "secrets" in f and secrets and turn == 0:
                raw, needles = secrets[(self.seed + turn) % len(secrets)]
                t += "\nplanted: " + raw
                self.planted += needles
            if "user_blocks" in f and (turn % 2 == 0 or "user_str" not in f):
                self.add(self.rec("user", [{"type": "text", "text": t}]), "user", [t], "user")
            else:
                self.add(self.rec("user", t), "user", [t], "user")
            idx += 1
            at = self.text(idx, "assistant")
            blocks = []
            if "thinking" in f:
                blocks.append({"type": "thinking", "thinking": "thought %s %s" % (self.seed, r.choice(WORDS)),
                               "signature": "sig"})
            blocks.append({"type": "text", "text": at})
            self.add(self.rec("assistant", blocks), "assistant", [at], "assistant")
            if "tool_str" in f or "tool_blocks" in f:
                self.tool_n += 1
                tid = "toolu_%s_%d" % (self.seed, self.tool_n)
                self.lines.append(json.dumps(self.rec("assistant", [{"type": "tool_use", "id": tid, "name": "Read",
                                                                    "input": {"file_path": "/x/%d.txt" % turn}}])))
                if "tool_blocks" in f and ("tool_str" not in f or turn % 2 == 0):
                    k = r.randint(2, 4)
                    pieces = [self.text(idx * 10 + j, "tool") for j in range(k)]
                    if "secrets" in f and secrets and turn == 1:
                        raw, needles = secrets[(self.seed + turn + 1) % len(secrets)]
                        pieces[-1] += " planted: " + raw
                        self.planted += needles
                    content = [{"type": "text", "text": p} for p in pieces]
                    self.add(self.rec("user", [{"type": "tool_result", "tool_use_id": tid, "content": content}]),
                             "tool", pieces, "tool_blocks")
                else:
                    piece = self.text(idx * 10, "tool")
                    self.add(self.rec("user", [{"type": "tool_result", "tool_use_id": tid, "content": piece}]),
                             "tool", [piece], "tool_str")
            if "boundary" in f and turn == n_turns // 2:
                b = self.rec("system", "Conversation compacted", subtype="compact_boundary",
                             compactMetadata={"trigger": "auto", "preTokens": 1000})
                del b["message"]
                b["content"] = "Conversation compacted"
                self.lines.append(json.dumps(b))
                self.lines.append(json.dumps(self.rec("user", "This session is being continued summary%s%d %s" % (
                    self.seed, turn, r.choice(WORDS)), isCompactSummary=True)))
        return self


def write_transcript(tr, home, project_dir):
    """Write `tr` under HOME/.claude/projects/<slug of project_dir>/ (the layout F44 and F57 describe). Returns the
    path of the file and the recall id prefix (`<sid8>:` or `<sid8>/<agent8>:`)."""
    slug = re.sub(r"[^A-Za-z0-9]", "-", project_dir)
    d = os.path.join(home, ".claude", "projects", slug)
    if tr.agent:
        d = os.path.join(d, tr.sid, "subagents")
        name = "agent-%s.jsonl" % tr.agent
        prefix = "%s/%s:" % (tr.sid[:8], tr.agent[:8])
    else:
        name = tr.sid + ".jsonl"
        prefix = "%s:" % tr.sid[:8]
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, name)
    with open(p, "w", encoding="utf-8") as fh:
        for l in tr.lines:
            fh.write(l + "\n")
    return p, prefix


# ============================================================ G1: decisions lines (F90.a)
TAGS = ("rule", "decision", "task")
CAPS_WORDS = ("RETIRED", "DONE", "NOTE", "TODO", "OLD", "X")


def date(r):
    return "20%02d-%02d-%02d" % (r.randint(24, 29), r.randint(1, 12), r.randint(1, 28))


def plain_text(r, uniq):
    """Text of a decisions line: no ` | `, does not start with a word in capitals followed by ` [` or `:`."""
    return "%s %s" % (uniq, " ".join(r.choice(WORDS) for _ in range(r.randint(2, 7))))


def valid_lines(seed, start=1):
    """One list of valid G1 lines, one of each form, with unique text. Returns [(line, form, fields)]. `fields` has
    `n`, `kind` (rule/decision/task/untagged/...), `uniq`."""
    r = random.Random("g1-%s" % seed)
    out, n = [], start

    def u(label):
        return "G1%s%d%s" % (label, seed, n)

    forms = ("active", "untagged", "nowhy_tagged", "nowhy_untagged", "superseded", "resolved")
    for form in forms:
        for tg in (TAGS if form in ("active", "nowhy_tagged") else (None,)):
            uniq = u(form[:3] + (tg or "")[:2])
            body = plain_text(r, uniq)
            d = date(r)
            if form == "active":
                line = "- D%d [%s] [%s] %s | why: %s" % (n, d, tg, body, "because " + r.choice(WORDS))
                out.append((line, form, {"n": n, "kind": tg, "uniq": uniq, "active": True}))
            elif form == "untagged":
                line = "- D%d [%s] %s | why: %s" % (n, d, body, "because " + r.choice(WORDS))
                out.append((line, form, {"n": n, "kind": "untagged", "uniq": uniq, "active": True}))
            elif form == "nowhy_tagged":
                line = "- D%d [%s] [%s] %s" % (n, d, tg, body)
                out.append((line, form, {"n": n, "kind": tg, "uniq": uniq, "active": True}))
            elif form == "nowhy_untagged":
                line = "- D%d [%s] %s" % (n, d, body)
                out.append((line, form, {"n": n, "kind": "untagged", "uniq": uniq, "active": True}))
            elif form == "superseded":
                line = "- D%d [%s] SUPERSEDED by D%d [%s]: [rule] %s | because: replaced" % (n, d, n + 50, date(r), body)
                out.append((line, form, {"n": n, "kind": "superseded", "uniq": uniq, "active": False}))
            else:
                line = "- D%d [%s] RESOLVED [%s]: finished | was: [task] %s | why: y" % (n, d, date(r), body)
                out.append((line, form, {"n": n, "kind": "resolved", "uniq": uniq, "active": False}))
            n += 1
    return out


def malformed_lines(seed, start=100):
    """Malformed G1 lines with unique text. Returns [(line, uniq, n)]. None of them is a header, blank, or comment."""
    r = random.Random("g1m-%s" % seed)
    n = start
    makers = [
        lambda n, u, d: "- D%d [%s] RETIRED [%s] (ended): [rule] %s | why: y" % (n, d, d, u),
        lambda n, u, d: "- D%d [%s] DONE: %s" % (n, d, u),
        lambda n, u, d: "D%d no dash %s" % (n, u),
        lambda n, u, d: "- D%d [%s] NOTE [x] %s | why: y" % (n, d, u),
        lambda n, u, d: "- D%d [2026-13-45x] [rule] %s | why: y" % (n, u),
        lambda n, u, d: "- D%d [%s] [rule] %s | why: y" % (0, d, u),  # n must be 1 or more
        lambda n, u, d: "* D%d [%s] [rule] %s | why: y" % (n, d, u),
        lambda n, u, d: "- D%d %s | why: y" % (n, u),  # no date
        lambda n, u, d: "- DX%d [%s] [rule] %s | why: y" % (n, d, u),
        lambda n, u, d: "- D%d [%s] SUPERSEDED by D%d: [rule] %s | because: r" % (n, d, n + 1, u),  # no date in by-part
        lambda n, u, d: "- D%d [%s] RESOLVED: %s | was: x" % (n, d, u),  # no date in resolved
    ]
    r.shuffle(makers)
    out = []
    for mk in makers[: 3 + seed % 4]:
        u = "MAL%d%s%d" % (seed, "".join(r.choice("abcdefgh") for _ in range(4)), n)
        out.append((mk(n, u, date(r)), u, n))
        n += 1
    return out


# ============================================================ G2: recall hit ids
def hex_n(r, n):
    return "".join(r.choice("0123456789abcdef-") for _ in range(n))


def valid_ids(seed):
    r = random.Random("g2-%s" % seed)
    out = []
    for _ in range(4):
        s = hex_n(r, 8)
        out.append("%s:%d" % (s, r.randint(1, 99999)))
        out.append("%s/%s:%d" % (s, hex_n(r, 8), r.randint(1, 99999)))
    return out


def malformed_ids(seed):
    r = random.Random("g2m-%s" % seed)
    s, a = hex_n(r, 8), hex_n(r, 8)
    return ["%s:0" % s, "%s:-3" % s, "%s:x" % s, "%s" % s, "%s:" % s, "%s/%s" % (s, a), "%s/:4" % s,
            "%s:4" % s[:7], "%sg:4" % s[:7], "%s//%s:4" % (s, a), "/%s:4" % a, "%s/%s:4" % (s, a[:6])]


# ============================================================ run helpers
import shutil, subprocess, sys, tempfile, unittest
from helpers import HOOKS_DIR

RECALL_PY = os.path.join(HOOKS_DIR, "recall.py")
SESSION_VAR = "CLAUDE_CODE_SESSION_ID"
TIMEOUT = 55  # every subprocess stays below 60 s

_REDACT_PY = r'''
import importlib.util, json, os, re, sys
hooks = sys.argv[1]
spec = importlib.util.spec_from_file_location("recall", os.path.join(hooks, "recall.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
fn = getattr(m, "redact", None)
if fn is None:
    ns = {"re": re, "os": os, "sys": sys, "json": json, "__name__": "redaction_copy"}
    with open(os.path.join(hooks, "lossless_handoff", "redaction.py")) as f:
        exec(compile(f.read(), "redaction.py", "exec"), ns)
    fn = ns["redact"]
print(json.dumps([fn(t) for t in json.load(sys.stdin)]))
'''


def redact_all(texts):
    """redact() of each text, computed by the product in one child process."""
    r = subprocess.run([sys.executable, "-c", _REDACT_PY, HOOKS_DIR], input=json.dumps(texts), capture_output=True,
                       text=True, timeout=TIMEOUT, env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8"})
    if r.returncode != 0:
        raise RuntimeError("redact helper failed: " + r.stderr[-500:])
    return json.loads(r.stdout)


HDR = re.compile(r"(?m)^--- (\S+) \d{4}-\d\d-\d\d[^\n]* (\w+)$")
CUT = re.compile(r"\n\[cut: (\d+) more chars[^\]\n]*\]\n?$")


def parse_open(out):
    """{id: (role, body)} of the output of `recall.py open`. A body is the text between its header line and the next
    header, without exactly one closing newline. A cut marker at the end of a body is not part of the body."""
    ms = list(HDR.finditer(out))
    res = {}
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(out)
        chunk = out[m.end() + 1:end]
        if chunk.endswith("\n"):
            chunk = chunk[:-1]
        if i + 1 == len(ms):  # the footer that names ids the output did not show is not part of the last body
            chunk = re.sub(r"\n\[not shown: [^\]]*\]$", "", chunk)
        res[m.group(1)] = (m.group(2), chunk)
    return res


class GenHome(unittest.TestCase):
    """A temp HOME with git projects whose transcripts come from the generator. No test methods here."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="f90-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)

    def project(self, name):
        p = os.path.join(self.tmp, name)
        os.makedirs(p, exist_ok=True)
        subprocess.run(["git", "init", "-q", p], check=True, capture_output=True, timeout=TIMEOUT)
        return p

    def put(self, tr, proj):
        return write_transcript(tr, self.home, proj)

    def rc(self, *args, sid=None, cwd=None, extra_env=None):
        env = {"HOME": self.home, "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8", "TZ": "UTC",
               "RECALL_EMBED_URL": "http://127.0.0.1:9"}
        if sid:
            env[SESSION_VAR] = sid
        env.update(extra_env or {})
        return subprocess.run([sys.executable, RECALL_PY, *args], capture_output=True, text=True, env=env,
                              timeout=TIMEOUT, cwd=cwd or self.tmp, stdin=subprocess.DEVNULL)

    def open_msgs(self, tr, prefix, proj, sid=None):
        ids = [prefix + str(m.line) for m in tr.msgs]
        got, raw = {}, ""
        todo = [ids[i:i + 10] for i in range(0, len(ids), 10)]  # recall.py takes at most 10 ids in one call
        while todo:
            batch = todo.pop(0)
            r = self.rc("open", *batch, "--full", "--around", "0", "--cwd", proj, sid=sid)
            self.assertEqual(r.returncode, 0, "%s open failed: %s" % (tag(tr.seed, tr.shape), r.stderr[-300:]))
            part = parse_open(r.stdout)
            got.update(part)
            raw += r.stdout
            miss = [i for i in batch if i not in part]  # a long output names the ids it did not show: ask again
            if miss and len(batch) == 1:
                self.fail("%s id %s is not in the output" % (tag(tr.seed, tr.shape), batch[0]))
            if miss and len(miss) == len(batch):  # nothing shown: use smaller batches
                h = len(miss) // 2
                todo = [miss[:h], miss[h:]] + todo
            elif miss:
                todo = [miss] + todo
        return ids, got, raw


def secret_samples():
    from test_f65_redaction import SECRETS
    return [SECRETS[k] for k in sorted(SECRETS)]
