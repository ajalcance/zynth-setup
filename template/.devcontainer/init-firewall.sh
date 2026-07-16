#!/usr/bin/env bash
# ==============================================================================
# Default-deny egress firewall for the dev sandbox.
# ==============================================================================
# An AI agent runs code it wrote without a human reading every line. This limits the
# blast radius: outbound traffic is DENIED except to an allow-list (GitHub, package
# registries, sigstore). A prompt-injected or buggy dependency can't quietly exfiltrate
# or call home. It VERIFIES itself at the end and exits non-zero if the policy isn't
# actually in force — fail-closed. See docs/decisions/0004.
#
# Runs at container start (needs NET_ADMIN; wired in devcontainer.json). Widen the
# allow-list below for hosts your project legitimately needs.
# ==============================================================================
set -euo pipefail
IFS=$'\n\t'

ALLOW_DOMAINS=(
  github.com api.github.com codeload.github.com objects.githubusercontent.com
  raw.githubusercontent.com ghcr.io pkg-containers.githubusercontent.com
  registry.npmjs.org pypi.org files.pythonhosted.org
  fulcio.sigstore.dev rekor.sigstore.dev tuf-repo-cdn.sigstore.dev
)

echo "Configuring default-deny egress firewall…"
iptables -F
iptables -X 2>/dev/null || true
ipset destroy allowed 2>/dev/null || true
ipset create allowed hash:net

# GitHub's published infra ranges (web + api + git).
if meta=$(curl -fsS --max-time 20 https://api.github.com/meta); then
  echo "$meta" | jq -r '(.web + .api + .git)[]' | while read -r cidr; do
    ipset add allowed "$cidr" 2>/dev/null || true
  done
fi

# Resolve the allow-list domains to current IPs.
for domain in "${ALLOW_DOMAINS[@]}"; do
  for ip in $(dig +short A "$domain" | grep -E '^[0-9.]+$'); do
    ipset add allowed "$ip" 2>/dev/null || true
  done
done

# Policy: drop everything, then permit loopback, established flows, DNS, and the allow-list.
iptables -P INPUT DROP
iptables -P FORWARD DROP
iptables -P OUTPUT DROP
iptables -A INPUT  -i lo -j ACCEPT
iptables -A OUTPUT -o lo -j ACCEPT
iptables -A INPUT  -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -A OUTPUT -p udp --dport 53 -j ACCEPT
iptables -A OUTPUT -p tcp --dport 53 -j ACCEPT
iptables -A OUTPUT -m set --match-set allowed dst -j ACCEPT

# ---- Fail-closed self-check: an allowed host must work, a random host must not. ----
if ! curl -fsS --max-time 10 https://api.github.com/zen >/dev/null; then
  echo "FATAL: an allow-listed host (github.com) is unreachable — firewall misconfigured." >&2
  exit 1
fi
if curl -fsS --max-time 5 https://example.com >/dev/null 2>&1; then
  echo "FATAL: egress is NOT blocked (example.com reachable) — sandbox is open." >&2
  exit 1
fi
echo "✓ egress sandbox active — default-deny verified (allow-list reachable, everything else blocked)."
