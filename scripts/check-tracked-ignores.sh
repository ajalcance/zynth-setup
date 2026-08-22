#!/usr/bin/env bash
# ==============================================================================
# Fail if any TRACKED file is matched by an ignore rule — template-repo tooling.
#
# Copier's dirty-repo flow clones with --no-checkout and re-stages the worktree
# against an EMPTY index, so gitignore rules bind files that are normally
# tracked-and-immune. A tracked template file matched by any rule (including the
# generated project's own template/.gitignore, whose rules also apply inside this
# repo) is then silently DELETED from every generation made from a locally
# modified template. That is how `.env.*` swallowed .env.example.jinja for weeks
# while CI stayed green. Un-ignore the file or rename it — never generate around it.
#
# Runs in CI (template-test.yml) and locally (see MAINTAINING.md). Same artifact
# in both places, per the CI-layer-mirroring rule.
# ==============================================================================
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

# Non-verbose on purpose: -v also reports NEGATION matches, which would
# false-positive on exactly the files an un-ignore exception rescues.
# check-ignore exits 0 = something is ignored (bad), 1 = nothing (good),
# >1 = it could not evaluate (a malformed pattern, a git failure) — which must
# fail too: "could not check" reported as "clean" is a green tick over nothing.
set +e
matched="$(git ls-files | git check-ignore --no-index --stdin)"
rc=$?
set -e

total="$(git ls-files | wc -l | tr -d ' ')"

case "$rc" in
  1)
    echo "ignore-rule check: OK — none of the $total tracked files end up ignored."
    ;;
  0)
    echo "ignore-rule check: FAILED — tracked files matched by ignore rules;" >&2
    echo "copier's dirty-repo flow will silently drop these from local generations:" >&2
    echo "$matched" >&2
    exit 1
    ;;
  *)
    echo "ignore-rule check: FAILED — git check-ignore exited $rc; the ignore rules" >&2
    echo "could not be evaluated (unreadable excludes config, or not a repo). Nothing" >&2
    echo "was verified — 'could not check' must never read as 'clean'." >&2
    exit "$rc"
    ;;
esac
