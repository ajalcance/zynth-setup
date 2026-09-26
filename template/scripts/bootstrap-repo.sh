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
# Applies every ruleset in .github/rulesets/ — main (pull requests only, ci-complete
# required, no bypass) and release tags (v* can never be deleted or re-pointed) — then
# the labels, the security features your plan allows, and merge settings that match the
# ruleset. Idempotent: re-running updates everything in place.
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

# ------------------------------------------------------------------------------
# Protected-change labels. The workflows READ these labels; GitHub only lets you apply a
# label that exists, so an unprovisioned label is an override nobody can grant and a hold
# nobody can place. Idempotent: --force updates an existing label rather than failing.
# ------------------------------------------------------------------------------
labels=(
  "guardrail-change|B60205|A deliberate, reviewed change to a guard-defining file"
  "allow-suppressions|D93F0B|A justified new suppression marker"
  "no-tests-needed|FBCA04|A pure refactor or rename with no behaviour change"
  "sensitive-change-approved|B60205|A reviewed change to a sensitive path"
  "allow-exemptions|D93F0B|A justified threshold move or scanner-exemption growth"
  "no-changelog|C5DEF5|Code changed with no user-visible effect, so no CHANGELOG entry"
  "release-blocker|000000|An owner hold: while an issue carries this, releases are denied"
  # Dependabot's labels. GitHub drops a label that does not exist, so an unprovisioned flag
  # silently never appears — and `needs-owner` is how a bot's guard bump asks for the owner.
  "needs-owner|FBCA04|A bot's change to a guard: the owner reviews, then applies guardrail-change"
  "dependencies|0366D6|A dependency update"
  "ci|5319E7|Continuous integration and tooling"
  "backend|1D76DB|Backend"
  "frontend|0E8A16|Frontend"
  "docs-site|C2E0C6|Docs site"
  "docker|0DB7ED|Container images"
)
echo
echo "Provisioning protected-change labels on $repo ..."
for entry in "${labels[@]}"; do
  IFS='|' read -r name colour description <<<"$entry"
  gh label create "$name" --repo "$repo" --color "$colour" --description "$description" --force >/dev/null
  echo "✓ label '$name'"
done

# ------------------------------------------------------------------------------
# Security features. Nothing turned these on, so an adopter's repository ran with secret
# scanning, push protection and Dependabot alerts OFF unless someone went looking. Each is
# attempted and its outcome printed: on a PRIVATE repository without GitHub Advanced Security,
# secret scanning is unavailable — said out loud, not failed on, because the committed gates
# still scan (gitleaks in pre-commit, and the canary-checked secret scan in CI).
# ------------------------------------------------------------------------------
echo
echo "Enabling security features on $repo ..."
if gh api -X PATCH "repos/$repo" --input - >/dev/null 2>&1 <<'JSON'
{
  "security_and_analysis": {
    "secret_scanning": { "status": "enabled" },
    "secret_scanning_push_protection": { "status": "enabled" }
  }
}
JSON
then
  echo "✓ secret scanning + push protection"
else
  echo "⚠ secret scanning + push protection NOT enabled — unavailable on this plan (a private"
  echo "  repository needs GitHub Advanced Security). CI's secret scan and the gitleaks hook"
  echo "  still run; enable it in Settings → Code security if your plan allows."
fi
if gh api -X PUT "repos/$repo/vulnerability-alerts" >/dev/null 2>&1; then
  echo "✓ Dependabot alerts"
else
  echo "⚠ Dependabot alerts NOT enabled — enable them in Settings → Code security."
fi
if gh api -X PUT "repos/$repo/automated-security-fixes" >/dev/null 2>&1; then
  echo "✓ Dependabot security updates"
else
  echo "⚠ Dependabot security updates NOT enabled — enable them in Settings → Code security."
fi

# Merge settings that match the ruleset: it allows squash only, so a merge button offering
# anything else is a button the ruleset then refuses. tests/guards/test_workflow_invariants.py
# holds the two files to the same answer.
gh api -X PATCH "repos/$repo" \
  -F allow_squash_merge=true -F allow_merge_commit=false -F allow_rebase_merge=false \
  -F delete_branch_on_merge=true >/dev/null
echo "✓ merges: squash only (the ruleset's one method); merged branches deleted"

echo
echo "Verify:  gh api repos/$repo/rulesets --jq '.[].name'"
echo "         gh label list --repo $repo"
echo "Note: the required check is 'ci-complete' — the first PR wires it up once CI has run once."
