#!/usr/bin/env python3
"""Release evidence — what was built, from what, and which exact bytes were signed.

A release that says "version 1.2.3 was built from main" is a claim. A release that names the
commit, the workflow run, and the **content digest** of every image, alongside an SBOM for each,
is a record you can check afterwards. The difference matters most in the case you actually care
about: something shipped, and nobody can now say what was in it.

The document is deliberately narrow. It records only facts a later reader can verify
independently, and the validator rejects anything that merely looks like a fact:

    python3 scripts/release_evidence.py --emit --tag v1.2.3 --commit <sha> \\
        --run-url https://github.com/o/r/actions/runs/1 \\
        --image backend=ghcr.io/o/r-backend@sha256:<64 hex> \\
        --sbom backend=sbom-backend.spdx.json --out release-evidence.json

    python3 scripts/release_evidence.py --validate release-evidence.json [--expect-tag v1.2.3]
    python3 scripts/release_evidence.py --list images release-evidence.json   # one ref per line
    python3 scripts/release_evidence.py --list env release-evidence.json      # NAME_IMAGE=ref

The ``--list`` modes exist so the release workflow never embeds a parser in a YAML ``run:``
block. Logic inside a workflow string cannot be run, tested, or fixed anywhere else; the same
rule that keeps guards in ``scripts/`` applies here. Both modes validate before printing, so a
malformed document cannot be consumed by a later step.

**Every image reference must be pinned by digest.** A tag is a mutable pointer: evidence naming
``:v1.2.3`` records what that name meant at the moment of writing, and nothing about what it
means now. Evidence that can silently come to describe different bytes is not evidence, so the
validator refuses it.

``--expect-tag`` is what makes promotion safe: promoting a release verifies that the evidence in
hand is the evidence *for that release*, not a valid document from some other one.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

SCHEMA_VERSION = 1

TAG_RE = re.compile(r"^v\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
# registry/path@sha256:<64 hex> — a digest, never a tag.
DIGEST_REF_RE = re.compile(r"^[a-z0-9.\-]+(:[0-9]+)?/[a-z0-9._\-/]+@sha256:[0-9a-f]{64}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
URL_RE = re.compile(r"^https://\S+$")


def _pairs(values: list[str], flag: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for value in values:
        name, separator, rest = value.partition("=")
        if not separator or not name or not rest:
            raise SystemExit(f"error: {flag} expects name=value, got '{value}'")
        out[name] = rest
    return out


def _readiness(path: str) -> dict:
    """The production-readiness verdict, read from the scan of THIS tree at build time.

    Bound into the evidence rather than re-derived later, because the later checks run
    somewhere else: promotion checks out the default branch, and the deploy host has whatever
    the operator last pulled. A verdict computed against the wrong tree passes while the image
    still carries the blocker — and it looks like a control the whole time.
    """
    try:
        verdict = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(
            f"error: cannot read the production-readiness verdict at {path} ({exc}). Run\n"
            f"  python3 scripts/prod_readiness.py --json {path}\n"
            f"first. Evidence is not emitted without one: a missing verdict is not 'clean'."
        ) from exc
    if not isinstance(verdict, dict) or not isinstance(verdict.get("clean"), bool):
        raise SystemExit(f"error: {path} is not a production-readiness verdict")
    blockers = verdict.get("open_blockers")
    if not isinstance(blockers, list) or any(not isinstance(b, str) for b in blockers):
        raise SystemExit(f"error: {path}: 'open_blockers' must be a list of ids")
    if verdict["clean"] != (not blockers):
        raise SystemExit(
            f"error: {path} says clean={verdict['clean']} with {len(blockers)} open blocker(s). "
            f"The two must agree, so neither can be edited alone."
        )
    return {"clean": verdict["clean"], "open_blockers": sorted(blockers)}


def emit(args: argparse.Namespace) -> int:
    images = _pairs(args.image, "--image")
    sboms = _pairs(args.sbom, "--sbom")

    components = []
    for name in sorted(images):
        sbom_path = sboms.get(name)
        if sbom_path is None:
            raise SystemExit(f"error: no --sbom given for image '{name}'")
        data = Path(sbom_path).read_bytes()
        components.append(
            {
                "name": name,
                "image": images[name],
                "sbom_file": Path(sbom_path).name,
                "sbom_sha256": hashlib.sha256(data).hexdigest(),
            }
        )

    document = {
        "schema_version": SCHEMA_VERSION,
        "tag": args.tag,
        "commit": args.commit,
        "run_url": args.run_url,
        "built_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "components": components,
        "production_readiness": _readiness(args.production_readiness),
    }
    Path(args.out).write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(f"release-evidence: wrote {args.out} — {len(components)} component(s).")
    return 0


def _check_readiness(document: dict, errors: list[str], require_clean: bool) -> None:
    """Fail closed in three directions. Two refusals downstream depend on this field."""
    verdict = document.get("production_readiness")
    if not isinstance(verdict, dict):
        # (1) A missing verdict is NOT clean. Evidence predating the field is refused rather
        # than waved through: "we did not record it" and "there was nothing to record" are
        # different facts, and only one of them is safe to deploy.
        errors.append(
            "production_readiness is missing — a release that does not record its readiness "
            "verdict cannot be promoted. Re-cut it: the candidate binds the verdict into the "
            "evidence, because a scan run at promotion time would describe the wrong tree."
        )
        return
    clean, blockers = verdict.get("clean"), verdict.get("open_blockers")
    if not isinstance(clean, bool) or not isinstance(blockers, list):
        errors.append("production_readiness must carry a boolean 'clean' and a list of ids")
        return
    # (3) The two must agree, so neither can be edited alone.
    if clean != (not blockers):
        errors.append(
            f"production_readiness says clean={clean} with {len(blockers)} open blocker(s) — "
            f"the verdict contradicts itself, so one of the two was edited by hand"
        )
        return
    if require_clean and not clean:
        errors.append(
            "production_readiness records "
            + ", ".join(str(b) for b in blockers)
            + " open at build time. A signed candidate carries its own refusal: these bytes "
            "contain the stand-in, whatever the default branch looks like now."
        )


def validate(
    path: Path, expect_tag: str | None, quiet: bool = False, require_clean: bool = False
) -> int:
    errors: list[str] = []
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"release-evidence: FAILED — cannot read {path}: {exc}")
        return 1
    if not isinstance(document, dict):
        print(f"release-evidence: FAILED — {path} is not an evidence document")
        return 1

    if document.get("schema_version") != SCHEMA_VERSION:
        errors.append(
            f"schema_version is {document.get('schema_version')!r}, expected {SCHEMA_VERSION}"
        )

    tag = document.get("tag", "")
    if not TAG_RE.match(str(tag)):
        errors.append(f"tag {tag!r} is not a release tag")
    elif expect_tag and tag != expect_tag:
        errors.append(
            f"evidence is for {tag}, but {expect_tag} is being released — this document belongs "
            f"to a different release and proves nothing about this one"
        )

    if not COMMIT_RE.match(str(document.get("commit", ""))):
        errors.append(
            f"commit {document.get('commit')!r} is not a full 40-character sha — an abbreviated "
            f"or missing commit cannot be resolved unambiguously later"
        )

    if not URL_RE.match(str(document.get("run_url", ""))):
        errors.append("run_url is missing or is not an https URL — the build is unattributable")

    built_at = str(document.get("built_at", ""))
    try:
        datetime.strptime(built_at, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        errors.append(f"built_at {built_at!r} is not an ISO-8601 UTC timestamp")

    _check_readiness(document, errors, require_clean)

    components = document.get("components")
    if not isinstance(components, list) or not components:
        errors.append("components is empty — a release that built nothing is not a release")
        components = []

    seen: set[str] = set()
    for index, component in enumerate(components):
        where = f"components[{index}]"
        if not isinstance(component, dict):
            errors.append(f"{where} is not an object")
            continue
        name = str(component.get("name", ""))
        if not name:
            errors.append(f"{where} has no name")
        elif name in seen:
            errors.append(f"{where}: duplicate component name {name!r}")
        seen.add(name)

        image = str(component.get("image", ""))
        if not DIGEST_REF_RE.match(image):
            errors.append(
                f"{where} ({name}): image {image!r} is not pinned by digest. A tag is a mutable "
                f"pointer — evidence naming one records what that name meant, not what runs."
            )
        if not SHA256_RE.match(str(component.get("sbom_sha256", ""))):
            errors.append(
                f"{where} ({name}): sbom_sha256 is missing or malformed — without it the SBOM "
                f"attached to the release cannot be tied to this record"
            )
        if not str(component.get("sbom_file", "")):
            errors.append(f"{where} ({name}): sbom_file is missing")

    if errors:
        print(f"release-evidence: FAILED — {path} is not usable as evidence\n")
        for error in errors:
            print(f"  ✗ {error}")
        print(
            "\nA release record that can drift, or that describes a different release, is worse\n"
            "than none: it is believed. Fix the document, or do not promote from it."
        )
        return 1

    if not quiet:
        print(
            f"release-evidence: OK — {tag} at {document['commit'][:12]}, "
            f"{len(components)} component(s), all pinned by digest."
        )
        for component in components:
            print(f"  • {component['name']}: {component['image']}")
    return 0


def listing(path: Path, what: str) -> int:
    """Print the image refs (or .env assignments) from an evidence document.

    Validates first: a consumer must never act on a document the validator would reject.
    """
    if validate(path, None, quiet=True) != 0:
        return 1
    document = json.loads(path.read_text(encoding="utf-8"))
    lines = []
    for component in document["components"]:
        if what == "images":
            lines.append(component["image"])
        else:
            lines.append(f"{component['name'].upper()}_IMAGE={component['image']}")
    print("\n".join(lines))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--emit", action="store_true", help="write an evidence document")
    mode.add_argument("--validate", metavar="FILE", help="check an evidence document")
    mode.add_argument(
        "--list",
        nargs=2,
        metavar=("images|env", "FILE"),
        help="print the recorded image refs, or .env assignments for the deploy host",
    )
    parser.add_argument("--expect-tag", default=None, help="the tag this evidence must be for")
    parser.add_argument("--tag", default=None)
    parser.add_argument("--commit", default=None)
    parser.add_argument("--run-url", default=None)
    parser.add_argument("--image", action="append", default=[], metavar="NAME=REF")
    parser.add_argument("--sbom", action="append", default=[], metavar="NAME=PATH")
    parser.add_argument("--out", default="release-evidence.json")
    parser.add_argument(
        "--production-readiness",
        default="production-readiness.json",
        metavar="FILE",
        help="the verdict from `prod_readiness.py --json`, bound into the document",
    )
    parser.add_argument(
        "--require-clean",
        action="store_true",
        help="with --validate: also refuse evidence whose recorded verdict is not clean",
    )
    args = parser.parse_args()

    if args.validate:
        return validate(Path(args.validate), args.expect_tag, require_clean=args.require_clean)
    if args.list:
        what, path = args.list
        if what not in ("images", "env"):
            raise SystemExit(f"error: --list expects 'images' or 'env', got '{what}'")
        return listing(Path(path), what)
    for required in ("tag", "commit", "run_url"):
        if not getattr(args, required):
            raise SystemExit(f"error: --emit requires --{required.replace('_', '-')}")
    return emit(args)


if __name__ == "__main__":
    sys.exit(main())
