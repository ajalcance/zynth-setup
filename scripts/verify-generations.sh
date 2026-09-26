#!/usr/bin/env bash
# ==============================================================================
# Generate every variant from the WORKING TREE and run each generated project's gates.
#
# The verification a change to template/ needs before it is committed (CLAUDE.md, rule 2).
# It lived for months as scratch scripts on one maintainer's machine, which is how the
# generated project's own pre-commit hooks came to be skipped in a "verified" run and two
# stray blank lines reached CI. Versioned, it cannot quietly lose a step.
#
# Variants: full (every module), minimal (none), hooks-off (minimal without the Claude
# policy — the one variant where the agent-policy tests must SKIP rather than pass).
# Gates, per variant, in the order an adopter meets them: the pre-commit hooks (by committing,
# exactly as an adopter's first commit does), make policy, harness, sast, infra-lint, audit,
# guard-tests. The self-test in CI runs these plus the frontend, docs, image and copier-update
# gates, which need Node, Docker and QEMU; this is the part every maintainer can run.
#
# Output goes to .copier-test/ (ignored), inside the project: the confinement hook refuses
# changes outside it. Inside the agent's OS sandbox (ADR 0004; Claude Code sets
# SANDBOX_RUNTIME) it goes to $TMPDIR instead. Under the project the sandbox refuses every
# .git/config, git hook and *.pem file, and a generated project needs all three: `git
# init`, its pre-commit hook, the CA bundle in its venv. $TMPDIR is already writable
# there, so nothing is widened. Usage: scripts/verify-generations.sh [variant ...]
# ==============================================================================
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
out="$root/.copier-test"
if [ -n "${SANDBOX_RUNTIME:-}" ]; then
  tmp="${TMPDIR:?verify: inside the sandbox but TMPDIR is unset}"
  out="${tmp%/}/zynth-setup-verify"
fi
copier="${COPIER:-$root/.venv/bin/copier}"
[ -x "$copier" ] || { echo "verify: REFUSED — no copier at $copier. Run \`make venv\`." >&2; exit 2; }

variant_data() {
  case "$1" in
    full) echo "-d include_frontend=true -d include_docs_site=true -d include_deploy=true -d include_compliance_spine=true -d server_host=deploy.example.com" ;;
    minimal) echo "-d include_frontend=false -d include_docs_site=false -d include_deploy=false -d include_compliance_spine=false" ;;
    hooks-off) echo "-d include_frontend=false -d include_docs_site=false -d include_deploy=false -d include_compliance_spine=false -d include_claude_hooks=false" ;;
    *) return 1 ;;
  esac
}

variants=("$@")
[ ${#variants[@]} -gt 0 ] || variants=(full minimal hooks-off)

failures=0
report=()
mkdir -p "$out"
echo "verify: output in $out"

for variant in "${variants[@]}"; do
  data="$(variant_data "$variant")" || { echo "verify: unknown variant '$variant'" >&2; exit 2; }
  dest="$out/$variant"
  logs="$out/$variant.logs"
  rm -rf "$dest" "$logs"
  mkdir -p "$logs"
  echo "== $variant: generating from the working tree"
  # shellcheck disable=SC2086 # $data is a list of flags, split on purpose
  if ! "$copier" copy --defaults --trust --vcs-ref HEAD \
      --data-file "$root/.github/self-test-owner.yml" -d "project_name=Verify ${variant}" \
      $data "$root" "$dest" >"$logs/generate.log" 2>&1; then
    report+=("$variant  FAIL generate   (see $logs/generate.log)")
    failures=$((failures + 1))
    continue
  fi

  venv="$dest/backend/.venv/bin"
  "$venv/pip" install -q -c "$dest/requirements-ci.txt" semgrep zizmor pre-commit >"$logs/tools.log" 2>&1

  run_gate() {
    local name=$1
    shift
    if (cd "$dest" && env PATH="$venv:$PATH" CI_TOOLS="$out/.ci-tools" "$@") >"$logs/$name.log" 2>&1; then
      report+=("$variant  pass $name")
    else
      report+=("$variant  FAIL $name   (see $logs/$name.log)")
      failures=$((failures + 1))
    fi
  }

  # Every gate runs with the generated Makefile's own defaults — the relative venv paths an
  # adopter uses. Overriding them with absolute paths broke on a project path with a space.
  #
  # The adopter's first commit, hooks and all. gitleaks is skipped only because its hook builds
  # from Go source; `make policy` runs the same gitleaks version, pinned by checksum.
  # A commit with no hook installed "passes" having run nothing — so a missing hook fails.
  run_gate hooks bash -c 'test -f .git/hooks/pre-commit || { echo "no pre-commit hook installed: the commit would run nothing"; exit 1; }; git add -A && SKIP=gitleaks git -c user.email=v@example.com -c user.name=verify commit -qm "first commit"'
  run_gate policy make policy
  run_gate harness make harness
  run_gate sast make sast
  run_gate infra-lint make infra-lint
  run_gate audit make audit
  run_gate guard-tests make guard-tests

  counts="$(grep -hoE '[0-9]+ passed(, [0-9]+ skipped)?' "$logs/guard-tests.log" | tail -1)"
  report+=("$variant  guard tests: ${counts:-none counted}")
done

echo
printf '%s\n' "${report[@]}"
echo
if [ "$failures" -gt 0 ]; then
  echo "verify: FAILED — $failures gate(s) red across ${#variants[@]} variant(s). Logs under $out."
  exit 1
fi
echo "verify: OK — every gate green across ${#variants[@]} variant(s)."
