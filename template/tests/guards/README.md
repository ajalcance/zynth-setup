# Guard fault tests

These tests prove the repository's guards **can actually fail**.

A guard that silently stops working is worse than no guard: it reports green while checking
nothing, and everyone downstream trusts it. That has happened here — a coverage check that scanned
zero files and printed a tick, a suppression scan that could not tell documentation from code.
Every guard therefore gets a negative test.

## The rule these tests follow

**Assert both directions.** A suite that only tests the failure case would pass even if a guard
failed unconditionally. Each guard has at least one test proving a clean input passes *and* one
proving a faulted input fails.

**Run the real script.** The tests execute the actual files in `scripts/` — never a copy of their
logic — because a test of a reimplementation proves nothing about the guard that gates CI.

**Isolate the check under test.** `meta_guard` has several checks; each test disables the others
with the corresponding `--allow-*` flag, so a passing test cannot be explained by a different
check firing.

## Running

```bash
make guard-tests     # or: backend/.venv/bin/pytest tests/guards -q
```

They are part of `make check` and run in the CI `static` job.
