#!/usr/bin/env bash
# Wall off the rest of the home folder from the agent (ADR 0004). The owner runs this, in their
# own terminal, after the Agent Sandbox Kit has been applied: the agent is denied its settings.
#
# Adds to .claude/settings.local.json:
#   sandbox.filesystem.denyRead — the folders below, plus ~/Documents as a whole (the project
#     stays readable: it is already in allowRead, and the sandbox honours allow-inside-deny)
#   permissions.deny — the same walls for the agent's own file tools. A permission rule has no
#     allow-inside-deny, so ~/Documents is walled entry by entry: every entry in it except
#     "Software Applications" (whose siblings the kit already walls)
#   permissions.deny — .env files by bare name, so at any depth (".env.example" stays readable)
# Backs the file up first; refuses unless the sandbox is on; validates before replacing.
set -euo pipefail

cd "$(dirname "$0")/.."
F=.claude/settings.local.json
jq -e '.sandbox.enabled == true' "$F" >/dev/null || { echo "REFUSED: no sandbox in $F"; exit 1; }
cp "$F" "$F.bak-pre-home-walls"

walls=(
  Desktop Downloads Pictures Movies Music
  Library/Mail Library/Messages Library/Safari Library/Cookies "Library/Mobile Documents"
  "Library/Application Support/Google" "Library/Application Support/Firefox"
  "Library/Application Support/BraveSoftware" "Library/Application Support/Microsoft Edge"
  "Library/Application Support/Arc" "Library/Application Support/Claude"
  .zsh_history .bash_history .zsh_sessions .python_history .node_repl_history .lesshst
  .cursor .codex .gemini .continue .claude.json
)
walls_json="$(printf '%s\n' "${walls[@]}" | jq -R --arg h "$HOME" '$h + "/" + .' | jq -s .)"
docs_json="$(find "$HOME/Documents" -mindepth 1 -maxdepth 1 ! -name 'Software Applications' -print0 \
  | jq -Rs 'split("\u0000") | map(select(length > 0))')"

jq --arg docs "$HOME/Documents" --argjson walls "$walls_json" --argjson other "$docs_json" '
  .sandbox.filesystem.denyRead = ((.sandbox.filesystem.denyRead + $walls + [$docs]) | unique)
  | .permissions.deny = ((.permissions.deny
      + ([$walls[], $other[]] | map("Read(/" + . + ")", "Read(/" + . + "/**)"))
      + ["Read(.env)", "Read(.env.local)", "Read(.env.development)", "Read(.env.test)",
         "Read(.env.staging)", "Read(.env.production)"]) | unique)
' "$F" > "$F.new"

jq -e --arg docs "$HOME/Documents" '
  .sandbox.enabled == true
  and (.sandbox.filesystem.denyRead | index($docs)) != null
  and (.sandbox.filesystem.allowRead | map(test("/zynth-setup$")) | any)
' "$F.new" >/dev/null || { rm -f "$F.new"; echo "REFUSED: result failed validation; nothing changed"; exit 1; }
mv "$F.new" "$F"
git check-ignore -q "$F"

echo "walls added: $(jq '.sandbox.filesystem.denyRead | length' "$F") sandbox read walls," \
  "$(jq '.permissions.deny | length' "$F") deny rules, $(jq 'length' <<<"$docs_json") other" \
  "Documents entries walled — restart this project's Claude session"
