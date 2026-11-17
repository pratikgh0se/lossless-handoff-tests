# Lossless Handoff: acceptance tests

These are code-blind acceptance tests for https://github.com/pratikgh0se/lossless-handoff. They are written only from the `docs/spec.md` file of that repo.

## The code-blind rule

The people and agents who build the hooks never read these tests. They see only the test names and the assertion output.

## How to run

From the repo root, run this command:

```
HANDOFF_HOOKS_DIR=/path/to/lossless-handoff/hooks python3 -W ignore -m unittest discover -s .
```

## CI

The lossless-handoff repo checks out this repo at the commit named in its `tests.ref` file. It then runs the suite against `hooks/`.

## History

The history came from pratikgh0se/bento-mods-tests (folder `handoff-hooks`) on 2026-11-17.
