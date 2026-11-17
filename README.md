# Lossless Handoff: acceptance tests

These are code-blind acceptance tests for https://github.com/pratikgh0se/lossless-handoff. They are written only from the `docs/spec.md` file of that repo.

## The code-blind rule

The people and agents who build the hooks never read these tests. They see only the test names and the assertion output.

## How to run

From the repo root, run this command:

```
HANDOFF_HOOKS_DIR=/path/to/lossless-handoff/hooks python3 -W ignore -m unittest discover -s .
```

## Environment variables

- `HANDOFF_HOOKS_DIR`: the `hooks/` folder under test. Required.
- `LOSSLESS_HANDOFF_REPO`: the root of the lossless-handoff repo. The default is the parent of `HANDOFF_HOOKS_DIR`. Set it only if `hooks/` is not directly under the repo root. `helpers.py` builds every repo path (`install.sh`, `uninstall.sh`, `tools/handoff-canary/run.sh`) from this one value.

## Safety

Some tests run `install.sh` (and `uninstall.sh`). `helpers.py` runs them only with these settings, so no test can forget them:

- `HOME` is a temp folder. The helper refuses the real HOME.
- `LOSSLESS_HANDOFF_NO_LAUNCHCTL=1`. Without it, launchctl would load or unload real jobs in your login session.
- `RECALL_EMBED_URL=http://127.0.0.1:9`, a closed port, and the helper refuses `--yes`. Nothing goes to the network and no model is pulled.

Never run `install.sh` or `uninstall.sh` from a test with the real HOME. After a run, `launchctl list | grep -i lossless` must print nothing.

The install runs once per argument set per test process. The result is read-only for the tests. The plist tests run on macOS only and skip on Linux.

## CI

The lossless-handoff repo checks out this repo at the commit named in its `tests.ref` file. It then runs the suite against `hooks/`.

## History

The history came from pratikgh0se/bento-mods-tests (folder `handoff-hooks`) on 2026-11-17. The tests were later ported from the machine-setup layout to the lossless-handoff layout. See `SPEC-GAPS.md`.
