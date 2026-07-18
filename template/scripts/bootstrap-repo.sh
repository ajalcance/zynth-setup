#!/usr/bin/env bash
# ==============================================================================
# One-time repo hardening — applies the branch ruleset so the guards can't be
# edited away. Run once after the repo exists on GitHub and you are authenticated:
#
#   gh auth login          # needs 'repo' + admin on this repo
#   ./scripts/bootstrap-repo.sh
#
# Enforcement lives in repo settings (not a committed file), so an agent working in
# the repo cannot make CI non-required or merge past it. See docs/decisions/0004.
# Idempotent: re-running updates the existing ruleset in place.
# ==============================================================================
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ruleset_dir="$here/../.github/rulesets"

for bin in gh jq; do
  command -v "$bin" >/dev/null 2>&1 || { echo "error: '$bin' is required (install it, then re-run)." >&2; exit 1; }
done
[ -d "$ruleset_dir" ] || { echo "error: ruleset directory not found at $ruleset_dir" >&2; exit 1; }

# Apply EVERY ruleset in the directory, not one hardcoded file: adding a ruleset should be a
# matter of dropping in a .json, not editing this script (a file an adopter would never think
# to check). Fails closed if the directory is empty.
shopt -s nullglob
ruleset_files=("$ruleset_dir"/*.json)
shopt -u nullglob
[ ${#ruleset_files[@]} -gt 0 ] || { echo "error: no rulesets found in $ruleset_dir" >&2; exit 1; }

repo="$(gh repo view --json nameWithOwner -q .nameWithOwner)"

for ruleset_file in "${ruleset_files[@]}"; do
  name="$(jq -r .name "$ruleset_file")"
  echo "Applying ruleset '$name' to $repo ..."

  existing_id="$(gh api "repos/$repo/rulesets" --jq ".[] | select(.name==\"$name\") | .id" 2>/dev/null | head -n1 || true)"

  if [ -n "$existing_id" ]; then
    gh api -X PUT "repos/$repo/rulesets/$existing_id" --input "$ruleset_file" >/dev/null
    echo "✓ Updated existing ruleset (id $existing_id)."
  else
    gh api -X POST "repos/$repo/rulesets" --input "$ruleset_file" >/dev/null
    echo "✓ Created ruleset."
  fi
done

echo
echo "Verify:  gh api repos/$repo/rulesets --jq '.[].name'"
echo "Note: the required check is 'ci-complete' — the first PR wires it up once CI has run once."
