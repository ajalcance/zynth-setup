#!/usr/bin/env bash
# ==============================================================================
# One-time hardening of the TEMPLATE repository on GitHub — run by the owner.
#
#   gh auth login                 # admin on ajalcance/zynth-setup
#   ./scripts/bootstrap-repo.sh
#
# The template ships the same script to adopters (template/scripts/bootstrap-repo.sh). This
# repository ran without it until 2026-09-25: main unprotected, tags movable, and secret
# scanning, push protection and Dependabot alerts all off on a public repository.
#
# What it applies, each idempotent:
#   1. every ruleset in .github/rulesets/ — main (PRs only, ci-complete + guard-label
#      required, no bypass) and release tags (never deleted or re-pointed);
#   2. the labels the workflows and Dependabot use;
#   3. secret scanning + push protection, Dependabot alerts + security updates;
#   4. merge settings that match the ruleset (rebase only; delete merged branches).
#
# Enforcement lives in repository settings, not in a file, so an agent working in the
# repository cannot make a check non-required or merge past it. That is also why this is the
# owner's to run: the agent's session hook asks before any `gh api` mutation.
# ==============================================================================
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ruleset_dir="$here/../.github/rulesets"

for bin in gh jq; do
  command -v "$bin" >/dev/null 2>&1 || { echo "error: '$bin' is required." >&2; exit 1; }
done

shopt -s nullglob
ruleset_files=("$ruleset_dir"/*.json)
shopt -u nullglob
[ ${#ruleset_files[@]} -gt 0 ] || { echo "error: no rulesets in $ruleset_dir" >&2; exit 1; }

repo="$(gh repo view --json nameWithOwner -q .nameWithOwner)"
echo "Hardening $repo"

# --- 1. Rulesets --------------------------------------------------------------------------
for ruleset_file in "${ruleset_files[@]}"; do
  name="$(jq -r .name "$ruleset_file")"
  existing_id="$(gh api "repos/$repo/rulesets" --jq ".[] | select(.name==\"$name\") | .id" | head -n1)"
  if [ -n "$existing_id" ]; then
    gh api -X PUT "repos/$repo/rulesets/$existing_id" --input "$ruleset_file" >/dev/null
    echo "✓ ruleset '$name' updated (id $existing_id)"
  else
    gh api -X POST "repos/$repo/rulesets" --input "$ruleset_file" >/dev/null
    echo "✓ ruleset '$name' created"
  fi
done

# --- 2. Labels ----------------------------------------------------------------------------
labels=(
  "guardrail-change|B60205|A deliberate, reviewed change to a guard — applied by the owner only"
  "dependencies|0366D6|A dependency update"
  "ci|5319E7|Continuous integration and tooling"
)
for entry in "${labels[@]}"; do
  IFS='|' read -r name colour description <<<"$entry"
  gh label create "$name" --repo "$repo" --color "$colour" --description "$description" --force >/dev/null
  echo "✓ label '$name'"
done

# --- 3. Security features -----------------------------------------------------------------
gh api -X PATCH "repos/$repo" --input - >/dev/null <<'JSON'
{
  "security_and_analysis": {
    "secret_scanning": { "status": "enabled" },
    "secret_scanning_push_protection": { "status": "enabled" }
  }
}
JSON
echo "✓ secret scanning + push protection"
gh api -X PUT "repos/$repo/vulnerability-alerts" >/dev/null
echo "✓ Dependabot alerts"
gh api -X PUT "repos/$repo/automated-security-fixes" >/dev/null
echo "✓ Dependabot security updates"

# --- 4. Merge settings that match the ruleset ---------------------------------------------
gh api -X PATCH "repos/$repo" \
  -F allow_rebase_merge=true -F allow_squash_merge=false -F allow_merge_commit=false \
  -F delete_branch_on_merge=true >/dev/null
echo "✓ merges: rebase only; merged branches deleted"

# --- Verify, with a denominator ------------------------------------------------------------
echo
echo "Now in force:"
gh api "repos/$repo/rulesets" --jq '.[] | "  ruleset \(.name) (\(.target), \(.enforcement))"'
gh api "repos/$repo" --jq '.security_and_analysis | to_entries[] | "  \(.key): \(.value.status)"'
