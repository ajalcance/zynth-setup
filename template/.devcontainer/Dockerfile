# Sandboxed dev image: the project toolchain + a default-deny egress firewall
# (init-firewall.sh). See docs/decisions/0004.
FROM mcr.microsoft.com/devcontainers/python:1-3.12-bookworm

# Firewall tooling. iptables/ipset apply the policy at container start (needs NET_ADMIN).
RUN apt-get update && apt-get install -y --no-install-recommends \
        iptables ipset dnsutils jq \
    && rm -rf /var/lib/apt/lists/*

COPY init-firewall.sh /usr/local/bin/init-firewall.sh
RUN chmod +x /usr/local/bin/init-firewall.sh \
    && echo 'vscode ALL=(root) NOPASSWD: /usr/local/bin/init-firewall.sh' \
       > /etc/sudoers.d/init-firewall
