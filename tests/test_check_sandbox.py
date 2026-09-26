"""The sandbox check can fail, proves nothing from a probe that errored, and leaves nothing behind.

These run in CI (no sandbox) and in the agent's session (sandboxed) alike: none of them depends
on which side of the sandbox it runs.
"""

from __future__ import annotations

import importlib.util
import sys

import pytest
from conftest import SCRIPTS

spec = importlib.util.spec_from_file_location("check_sandbox", SCRIPTS / "check_sandbox.py")
check_sandbox = importlib.util.module_from_spec(spec)
sys.modules["check_sandbox"] = check_sandbox
spec.loader.exec_module(check_sandbox)

DENIED, ALLOWED, Probe = check_sandbox.DENIED, check_sandbox.ALLOWED, check_sandbox.Probe


def outcomes(*pairs: tuple[str, str]) -> list:
    return [(Probe(f"p{i}", expect, "    pass"), got) for i, (expect, got) in enumerate(pairs)]


def test_every_probe_holding_passes_and_prints_the_denominator(capsys):
    assert check_sandbox.judge(outcomes((DENIED, DENIED), (ALLOWED, ALLOWED))) == 0
    assert "2/2 probes held" in capsys.readouterr().out


@pytest.mark.parametrize(
    "got",
    [ALLOWED, "error: FileNotFoundError(2, 'No such file or directory')"],
    ids=["the-sandbox-let-it-through", "the-probe-errored"],
)
def test_one_probe_not_refused_fails_the_check(got, capsys):
    assert check_sandbox.judge(outcomes((DENIED, DENIED), (DENIED, got))) == 1
    assert "1/2 probes held" in capsys.readouterr().out


def test_a_control_the_sandbox_refused_fails_the_check():
    # A sandbox that refuses everything would pass every DENIED probe; the controls catch it.
    assert check_sandbox.judge(outcomes((DENIED, DENIED), (ALLOWED, DENIED))) == 1


def test_no_probes_is_a_failure_not_a_pass(capsys):
    assert check_sandbox.judge([]) == 1
    assert "no probe ran" in capsys.readouterr().out


def test_a_missing_path_is_an_error_not_a_refusal(tmp_path):
    # ~/.ssh absent would otherwise read as "denied" and pass a sandbox that denies nothing.
    probe = Probe("missing", DENIED, f"    __import__('os').listdir({str(tmp_path / 'nope')!r})")
    assert check_sandbox.run(probe).startswith("error:")


def test_both_kinds_of_control_are_present():
    kinds = {(p.expect, "urlopen" in p.body) for p in check_sandbox.probes()}
    assert (ALLOWED, False) in kinds, "no filesystem control: a deny-all sandbox would pass"
    assert (ALLOWED, True) in kinds, "no network control: a no-network sandbox would pass"
    assert (DENIED, True) in kinds, "nothing proves the network allowlist"


def test_every_probe_that_creates_a_file_removes_it():
    for probe in check_sandbox.probes():
        if "'x')" in probe.body:
            assert probe.cleanup is not None, f"{probe.name}: would leave its file behind"
            assert str(probe.cleanup) in probe.body, f"{probe.name}: cleans up the wrong path"


def test_the_write_probes_leave_nothing_behind_on_either_side_of_the_sandbox():
    # Outside the sandbox these writes succeed — in $HOME and .git/hooks — so this one is real.
    written = [p for p in check_sandbox.probes() if p.cleanup is not None]
    assert written, "no write probes found"
    for probe in written:
        check_sandbox.run(probe)
        assert not probe.cleanup.exists(), f"{probe.name}: left {probe.cleanup}"


def test_a_walled_folder_is_probed_by_listing_it():
    # Seatbelt lets a lookup of a walled folder through and refuses only the listing: a folder
    # probed with stat() reads "allowed" and fails a sandbox that holds.
    by_name = {p.name: p for p in check_sandbox.probes()}
    for wall in check_sandbox.HOME_WALL_FOLDERS:
        probe = by_name[f"list ~/{wall}"]
        assert probe.expect == DENIED and "listdir(" in probe.body, wall


def test_the_home_walls_are_probed():
    names = {p.name for p in check_sandbox.probes() if p.expect == DENIED}
    for wall in ("Desktop", "Downloads", "Documents"):
        assert f"list ~/{wall}" in names, f"~/{wall} is walled but never probed"


def test_the_project_inside_the_walled_documents_is_a_control():
    # ~/Documents is walled with this project allowed inside it; a control proves the exception.
    controls = [p for p in check_sandbox.probes() if p.expect == ALLOWED]
    assert any(repr(str(check_sandbox.ROOT)) in p.body and "stat(" in p.body for p in controls)
