#!/usr/bin/env bash
# The two single-binary linters `make infra-lint` runs — actionlint (workflow syntax and
# expressions) and hadolint (Dockerfiles) — fetched by VERSION and verified by checksum on
# EVERY run. The cache is not trusted: a tampered file is deleted and the run fails, the
# same rule scripts/secret_scan.py applies to gitleaks. zizmor is not here: it ships on PyPI,
# so requirements-ci.txt pins it like the other scanners.
#
# Usage: scripts/ci_tools.sh <dir>   — leaves <dir>/actionlint and <dir>/hadolint runnable.
# Bumping a version means updating its checksums below, from the upstream checksum file, in a
# change that carries the 'guardrail-change' label: these are programs that judge a change.
set -euo pipefail

ACTIONLINT_VERSION=1.7.12
HADOLINT_VERSION=2.15.1

dir=${1:?usage: scripts/ci_tools.sh <dir>}

os=$(uname -s | tr '[:upper:]' '[:lower:]')
case "$(uname -m)" in
  x86_64 | amd64) arch=amd64 ;;
  arm64 | aarch64) arch=arm64 ;;
  *) echo "ci-tools: no pinned build for $(uname -m)" >&2; exit 2 ;;
esac

# sha256 from the upstream checksum files (actionlint_<v>_checksums.txt, checksums.sha256).
case "$os-$arch" in
  linux-amd64)
    actionlint_sha=8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8
    hadolint_asset=hadolint-linux-x86_64
    hadolint_sha=c7187db94eeeeca956519a6af171adc31453941a1e777961f6e680f697c8c507 ;;
  linux-arm64)
    actionlint_sha=325e971b6ba9bfa504672e29be93c24981eeb1c07576d730e9f7c8805afff0c6
    hadolint_asset=hadolint-linux-arm64
    hadolint_sha=f6198ef8090f404dbb771abfee086eb8c48ac177f30da7fd3510aca35b344b5d ;;
  darwin-amd64)
    actionlint_sha=5b44c3bc2255115c9b69e30efc0fecdf498fdb63c5d58e17084fd5f16324c644
    hadolint_asset=hadolint-macos-x86_64
    hadolint_sha=ffe9bb18b23d5ed1eae50237aecdbb523d016e96da0bd4e7aa432040acfc3fde ;;
  darwin-arm64)
    actionlint_sha=aba9ced2dee8d27fecca3dc7feb1a7f9a52caefa1eb46f3271ea66b6e0e6953f
    hadolint_asset=hadolint-macos-arm64
    hadolint_sha=5c09f3213f8e40406abe048233d985eebef336d4a6a20021be47fadb6cf480a2 ;;
  *) echo "ci-tools: no pinned build for $os-$arch" >&2; exit 2 ;;
esac

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1
  else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

# verify <file> <expected>: a mismatch deletes the file, so the next run fetches afresh.
verify() {
  local actual
  actual=$(sha256_of "$1")
  if [ "$actual" != "$2" ]; then
    rm -f "$1"
    echo "ci-tools: checksum mismatch for $1 — expected $2, got $actual. Deleted; refusing to run it." >&2
    exit 1
  fi
}

# fetch <url> <file>: only when absent — the checksum, not the download, is the trust. Written
# to a temporary name and renamed, so a concurrent run (two make targets, two jobs sharing a
# cache) never reads a half-written file and reports a checksum mismatch that is not one.
fetch() {
  if [ ! -f "$2" ]; then
    curl -fsSL --retry 3 -o "$2.part.$$" "$1"
    mv -f "$2.part.$$" "$2"
  fi
}

mkdir -p "$dir"

tarball="$dir/actionlint_${ACTIONLINT_VERSION}_${os}_${arch}.tar.gz"
fetch "https://github.com/rhysd/actionlint/releases/download/v${ACTIONLINT_VERSION}/actionlint_${ACTIONLINT_VERSION}_${os}_${arch}.tar.gz" "$tarball"
verify "$tarball" "$actionlint_sha"
tar -xzf "$tarball" -C "$dir" actionlint

binary="$dir/hadolint-${HADOLINT_VERSION}-${hadolint_asset}"
fetch "https://github.com/hadolint/hadolint/releases/download/v${HADOLINT_VERSION}/${hadolint_asset}" "$binary"
verify "$binary" "$hadolint_sha"
cp "$binary" "$dir/hadolint" && chmod +x "$dir/hadolint"

echo "ci-tools: actionlint ${ACTIONLINT_VERSION} + hadolint ${HADOLINT_VERSION} verified by checksum (${os}-${arch}) in ${dir}"
