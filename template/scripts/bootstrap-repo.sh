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
ruleset_file="$here/../.github/rulesets/main.json"

for bin in gh jq; do
  command -v "$bin" >/dev/null 2>&1 || { echo "error: '$bin' is required (install it, then re-run)." >&2; exit 1; }
done
[ -f "$ruleset_file" ] || { echo "error: ruleset not found at $ruleset_file" >&2; exit 1; }

repo="$(gh repo view --json nameWithOwner -q .nameWithOwner)"
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

echo
echo "Verify:  gh api repos/$repo/rulesets --jq '.[].name'"
echo "Note: the required check is 'ci-complete' — the first PR wires it up once CI has run once."
