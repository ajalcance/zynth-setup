# 0002. Defense-in-depth against malicious & AI-generated code

- **Status:** Accepted
- **Date:** initial scaffold
- **Deciders:** project owner

## Context

Code enters this repo from humans and AI assistants. Both can introduce dangerous capabilities —
arbitrary code execution, unsafe deserialization, destructive operations, secret leakage, or
exfiltration — by accident or otherwise. No single control catches everything.

## Decision

Layered, mechanical controls that run automatically, not by memory:

1. **Secret hygiene** — `.gitignore` → **gitleaks** (pre-commit + CI) → `detect-private-key` hook.
   Only `.env.example` placeholders are committed.
2. **SAST** — a repo-owned **Semgrep "dangerous-ops"** ruleset (blocking) flags `eval`/`exec`,
   `shell=True`, unsafe deserialization, decode-then-execute, destructive FS/SQL, and requests to
   hardcoded IPs. Plus **bandit** and community Semgrep rules (advisory).
3. **Supply chain** — pinned dependencies, `pip-audit` / `npm audit` in CI, Dependabot updates.
4. **Runtime containment** — non-root containers, least-privilege DB roles, backups. Static rules
   catch capability; runtime least-privilege is the stronger layer.
5. **Fail closed** — missing config / ambiguous auth denies; no insecure fallback.

Justified exceptions use an inline `# nosemgrep: <rule-id> — <why>`; blanket disabling is not allowed.

## Consequences

- Accidental and unsophisticated-malicious dangerous code is caught before merge.
- Not a complete defense against a determined, obfuscating attacker — hence the runtime layer.

## Alternatives considered

- **Review-only.** Rejected: humans miss these consistently; mechanical gates don't.
