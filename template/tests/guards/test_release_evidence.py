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
    """What the release workflow writes must be what the validator accepts."""
    guard = install_guard(tmp_path, "release_evidence.py")
    write(tmp_path / "sbom-backend.spdx.json", '{"spdxVersion": "SPDX-2.3"}\n')
    emitted = tmp_path / "release-evidence.json"
    result = run_guard(
        guard,
        "--emit",
        "--tag", "v1.2.3",
        "--commit", COMMIT,
        "--run-url", "https://github.com/o/r/actions/runs/1",
        "--image", f"backend=ghcr.io/o/r-backend@{DIGEST}",
        "--sbom", "backend=sbom-backend.spdx.json",
        "--out", str(emitted),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    check = run_guard(guard, "--validate", str(emitted), "--expect-tag", "v1.2.3")
    assert check.returncode == 0, check.stdout + check.stderr


def test_emit_refuses_an_image_with_no_sbom(tmp_path):
    guard = install_guard(tmp_path, "release_evidence.py")
    result = run_guard(
        guard,
        "--emit",
        "--tag", "v1.2.3",
        "--commit", COMMIT,
        "--run-url", "https://github.com/o/r/actions/runs/1",
        "--image", f"backend=ghcr.io/o/r-backend@{DIGEST}",
        "--out", str(tmp_path / "e.json"),
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
