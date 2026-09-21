"""A release record that can drift, or describes a different release, is worse than none.

`release-evidence.json` is what someone reads when they need to know what actually shipped —
usually while something is on fire. Its whole value is that a later reader can check it, so the
validator rejects anything that only *looks* like a fact: an image named by a mutable tag, an
abbreviated commit, a missing SBOM hash, or a perfectly valid document belonging to a different
release.
"""

from __future__ import annotations

import json

from conftest import SCRIPTS, install_guard, run_guard, write

GUARD = SCRIPTS / "release_evidence.py"

DIGEST = "sha256:" + "ab" * 32
OTHER_DIGEST = "sha256:" + "cd" * 32
COMMIT = "0" * 39 + "1"


def _document(**overrides) -> dict:
    document = {
        "schema_version": 1,
        "tag": "v1.2.3",
        "commit": COMMIT,
        "run_url": "https://github.com/o/r/actions/runs/12345",
        "built_at": "2026-07-31T12:00:00Z",
        "components": [
            {
                "name": "backend",
                "image": f"ghcr.io/o/r-backend@{DIGEST}",
                "sbom_file": "sbom-backend.spdx.json",
                "sbom_sha256": "ef" * 32,
            }
        ],
        "production_readiness": {"clean": True, "open_blockers": []},
    }
    document.update(overrides)
    return document


def _sandbox(tmp_path, document: dict | str = None, name: str = "release-evidence.json"):
    guard = install_guard(tmp_path, "release_evidence.py")
    body = document if isinstance(document, str) else json.dumps(document or _document(), indent=2)
    write(tmp_path / name, body + "\n")
    return guard, tmp_path / name


# --- The shape of a usable record -----------------------------------------------------------


def test_a_complete_document_validates(tmp_path):
    guard, path = _sandbox(tmp_path)
    result = run_guard(guard, "--validate", str(path))
    assert result.returncode == 0, result.stdout + result.stderr


def test_an_image_named_by_tag_is_rejected(tmp_path):
    """The central rule: a tag is a mutable pointer, so it records a name, not bytes."""
    document = _document()
    document["components"][0]["image"] = "ghcr.io/o/r-backend:v1.2.3"
    guard, path = _sandbox(tmp_path, document)
    result = run_guard(guard, "--validate", str(path))
    assert result.returncode != 0, "an image reference by tag must be rejected"
    assert "not pinned by digest" in result.stdout


def test_a_truncated_digest_is_rejected(tmp_path):
    document = _document()
    document["components"][0]["image"] = "ghcr.io/o/r-backend@sha256:abcdef"
    guard, path = _sandbox(tmp_path, document)
    assert run_guard(guard, "--validate", str(path)).returncode != 0


def test_an_abbreviated_commit_is_rejected(tmp_path):
    """A short sha can become ambiguous as the repository grows; the record must not."""
    guard, path = _sandbox(tmp_path, _document(commit=COMMIT[:12]))
    result = run_guard(guard, "--validate", str(path))
    assert result.returncode != 0
    assert "40-character sha" in result.stdout


def test_a_missing_sbom_hash_is_rejected(tmp_path):
    document = _document()
    del document["components"][0]["sbom_sha256"]
    guard, path = _sandbox(tmp_path, document)
    assert run_guard(guard, "--validate", str(path)).returncode != 0


def test_no_components_is_rejected(tmp_path):
    guard, path = _sandbox(tmp_path, _document(components=[]))
    assert run_guard(guard, "--validate", str(path)).returncode != 0


def test_duplicate_component_names_are_rejected(tmp_path):
    document = _document()
    document["components"].append(dict(document["components"][0]))
    guard, path = _sandbox(tmp_path, document)
    assert run_guard(guard, "--validate", str(path)).returncode != 0


def test_a_bad_timestamp_is_rejected(tmp_path):
    guard, path = _sandbox(tmp_path, _document(built_at="last Tuesday"))
    assert run_guard(guard, "--validate", str(path)).returncode != 0


def test_a_missing_run_url_is_rejected(tmp_path):
    guard, path = _sandbox(tmp_path, _document(run_url=""))
    assert run_guard(guard, "--validate", str(path)).returncode != 0


def test_malformed_json_is_rejected(tmp_path):
    guard, path = _sandbox(tmp_path, "{not json")
    assert run_guard(guard, "--validate", str(path)).returncode != 0


def test_a_missing_file_is_rejected(tmp_path):
    guard = install_guard(tmp_path, "release_evidence.py")
    assert run_guard(guard, "--validate", str(tmp_path / "absent.json")).returncode != 0


# --- Evidence must belong to the release being promoted -------------------------------------


def test_evidence_for_another_release_is_rejected(tmp_path):
    """A valid document from a DIFFERENT release passes every structural check.

    This is the failure that promotes the wrong bytes while every signature verifies, so the
    expected tag is checked explicitly rather than assumed from the file being present.
    """
    guard, path = _sandbox(tmp_path)
    result = run_guard(guard, "--validate", str(path), "--expect-tag", "v9.9.9")
    assert result.returncode != 0, "evidence for a different release must be rejected"
    assert "different release" in result.stdout


def test_evidence_for_the_expected_release_passes(tmp_path):
    guard, path = _sandbox(tmp_path)
    result = run_guard(guard, "--validate", str(path), "--expect-tag", "v1.2.3")
    assert result.returncode == 0, result.stdout + result.stderr


# --- Emit / consume round trip ---------------------------------------------------------------


def test_emitted_evidence_validates(tmp_path):
    """What the release workflow writes must be what the validator accepts.

    Including the readiness verdict: the workflow scans the tree and binds the result, so a
    round trip that skipped it would test a document the release never produces.
    """
    guard = install_guard(tmp_path, "release_evidence.py")
    write(tmp_path / "sbom-backend.spdx.json", '{"spdxVersion": "SPDX-2.3"}\n')
    write(tmp_path / "production-readiness.json", json.dumps({"clean": True, "open_blockers": []}))
    emitted = tmp_path / "release-evidence.json"
    result = run_guard(
        guard,
        "--emit",
        "--tag",
        "v1.2.3",
        "--commit",
        COMMIT,
        "--run-url",
        "https://github.com/o/r/actions/runs/1",
        "--image",
        f"backend=ghcr.io/o/r-backend@{DIGEST}",
        "--sbom",
        "backend=sbom-backend.spdx.json",
        "--production-readiness",
        "production-readiness.json",
        "--out",
        str(emitted),
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    check = run_guard(
        guard,
        "--validate",
        str(emitted),
        "--expect-tag",
        "v1.2.3",
        "--require-clean",
        cwd=tmp_path,
    )
    assert check.returncode == 0, check.stdout + check.stderr


def test_emit_refuses_an_image_with_no_sbom(tmp_path):
    guard = install_guard(tmp_path, "release_evidence.py")
    result = run_guard(
        guard,
        "--emit",
        "--tag",
        "v1.2.3",
        "--commit",
        COMMIT,
        "--run-url",
        "https://github.com/o/r/actions/runs/1",
        "--image",
        f"backend=ghcr.io/o/r-backend@{DIGEST}",
        "--out",
        str(tmp_path / "e.json"),
    )
    assert result.returncode != 0, "an image with no SBOM must not be recorded as evidence"


def test_list_images_prints_only_refs(tmp_path):
    document = _document()
    document["components"].append(
        {
            "name": "frontend",
            "image": f"ghcr.io/o/r-frontend@{OTHER_DIGEST}",
            "sbom_file": "sbom-frontend.spdx.json",
            "sbom_sha256": "12" * 32,
        }
    )
    guard, path = _sandbox(tmp_path, document)
    result = run_guard(guard, "--list", "images", str(path))
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.split() == [
        f"ghcr.io/o/r-backend@{DIGEST}",
        f"ghcr.io/o/r-frontend@{OTHER_DIGEST}",
    ], result.stdout


def test_list_env_prints_deploy_assignments(tmp_path):
    guard, path = _sandbox(tmp_path)
    result = run_guard(guard, "--list", "env", str(path))
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == f"BACKEND_IMAGE=ghcr.io/o/r-backend@{DIGEST}"


def test_list_refuses_an_invalid_document(tmp_path):
    """A consumer must never act on a document the validator would reject."""
    document = _document()
    document["components"][0]["image"] = "ghcr.io/o/r-backend:latest"
    guard, path = _sandbox(tmp_path, document)
    result = run_guard(guard, "--list", "images", str(path))
    assert result.returncode != 0, "listing must fail on a document that does not validate"
    assert "not pinned by digest" in result.stdout, "and it must fail for the stated reason"


# --- The readiness verdict travels INSIDE the signed document ---------------------------
#
# `--strict` used to run in one place, the tag, and the tag does not reach production.
# Promotion and deploy do, and neither ran it. Re-deriving the verdict at either point is
# unsound: promotion checks out the DEFAULT BRANCH and the deploy host has whatever was last
# pulled, so a fresh scan describes the wrong tree. If main has since closed a blocker the
# image still contains, that scan passes — and it looks like a control the whole time.
#
# So the fact is bound to the bytes it describes, and fails closed in three directions.


def test_evidence_without_a_readiness_verdict_is_refused(tmp_path):
    """(1) A missing verdict is not clean. Evidence predating the field is refused."""
    document = _document()
    del document["production_readiness"]
    guard, path = _sandbox(tmp_path, document)
    result = run_guard(guard, "--validate", path)
    assert result.returncode != 0, "a release that records no readiness verdict must be refused"
    assert "production_readiness is missing" in result.stdout, result.stdout


def test_a_verdict_that_contradicts_itself_is_refused(tmp_path):
    """(3) clean and open_blockers must agree, so neither can be edited alone."""
    guard, path = _sandbox(
        tmp_path,
        _document(production_readiness={"clean": True, "open_blockers": ["auth-stub"]}),
    )
    result = run_guard(guard, "--validate", path)
    assert result.returncode != 0, "clean=true beside an open blocker must be refused"
    assert "contradicts itself" in result.stdout, result.stdout


def test_an_open_blocker_is_only_refused_under_require_clean(tmp_path):
    """A candidate mid-build-phase is still valid evidence; it is just not promotable."""
    guard, path = _sandbox(
        tmp_path,
        _document(production_readiness={"clean": False, "open_blockers": ["auth-stub"]}),
    )
    assert run_guard(guard, "--validate", path).returncode == 0, "the document is well-formed"
    blocked = run_guard(guard, "--validate", path, "--require-clean")
    assert blocked.returncode != 0, "--require-clean must refuse an open blocker"
    assert "auth-stub" in blocked.stdout, blocked.stdout


def test_a_clean_verdict_passes_require_clean(tmp_path):
    guard, path = _sandbox(tmp_path)
    assert run_guard(guard, "--validate", path, "--require-clean").returncode == 0


def test_emitting_without_a_verdict_refuses_rather_than_assuming_clean(tmp_path):
    """(2) An unreadable register must refuse to emit — an empty blocker list means clean."""
    guard = install_guard(tmp_path, "release_evidence.py")
    write(tmp_path / "sbom.json", "{}\n")
    result = run_guard(
        guard,
        "--emit",
        "--tag",
        "v1.2.3",
        "--commit",
        COMMIT,
        "--run-url",
        "https://github.com/o/r/actions/runs/1",
        "--image",
        f"backend=ghcr.io/o/r-backend@{DIGEST}",
        "--sbom",
        f"backend={tmp_path / 'sbom.json'}",
        "--production-readiness",
        str(tmp_path / "absent.json"),
        "--out",
        str(tmp_path / "out.json"),
        cwd=tmp_path,
    )
    assert result.returncode != 0, "no verdict must mean no evidence, not evidence saying clean"
    assert not (tmp_path / "out.json").exists(), "a refused emit must write nothing"


def test_a_hand_edited_verdict_file_is_refused_at_emit_time(tmp_path):
    guard = install_guard(tmp_path, "release_evidence.py")
    write(tmp_path / "sbom.json", "{}\n")
    write(tmp_path / "verdict.json", json.dumps({"clean": True, "open_blockers": ["stub"]}))
    result = run_guard(
        guard,
        "--emit",
        "--tag",
        "v1.2.3",
        "--commit",
        COMMIT,
        "--run-url",
        "https://github.com/o/r/actions/runs/1",
        "--image",
        f"backend=ghcr.io/o/r-backend@{DIGEST}",
        "--sbom",
        f"backend={tmp_path / 'sbom.json'}",
        "--production-readiness",
        str(tmp_path / "verdict.json"),
        "--out",
        str(tmp_path / "out.json"),
        cwd=tmp_path,
    )
    assert result.returncode != 0, "the two fields must agree at emit time as well"
