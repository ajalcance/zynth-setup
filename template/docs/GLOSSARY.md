# Glossary

Plain-language definitions of the terms used across this project. If a doc uses a word you don't
recognize, it's probably here. Ordered roughly from "most important" to "supporting detail."

---

### Guardrail
An automated rule that protects the project from a mistake — a check that runs by itself and
stops something risky. In this project, **the guardrails are the point**: because an AI writes
much of the code without line-by-line human review, the guardrails are what keep it safe.

### Fail closed
When something is unclear, missing, or broken, the safe choice is to **stop / deny**, not to
quietly continue. Example: if a required secret is missing, the app refuses to start rather than
running in an insecure mode. The opposite — "fail open" — is when a failure lets things through;
that's how accidents happen, so we avoid it for anything security-related.

### Fail open
The deliberate opposite of fail-closed, used only where safety isn't at stake. Example: the
optional auto-formatter is best-effort — if it can't run, it simply does nothing rather than
blocking your work. Convenience features fail open; protections fail closed.

### Gate / CI check
A "gate" is a check that must pass before code is allowed through. **CI** (Continuous
Integration) is the service that runs these gates automatically every time code is pushed. If a
gate is red, the change is blocked until it's fixed. Think of it as an automatic reviewer that
never gets tired.

### Ruleset (branch protection)
A setting on the code host (GitHub) that makes the rules *a property of the repository itself*,
not a file someone can edit away. It's what forces "all checks must pass, and guardrail changes
need a human's approval" — enforced on the server, where an AI assistant can't bypass it.

### CODEOWNERS
A file that says "changes to these sensitive areas require a specific person's approval." It's
how we say: feature code can flow quickly, but changes to the *guardrails themselves* always get
a human's eyes.

### ADR (Architecture Decision Record)
A short, dated note that records **a decision and why it was made** — the reasoning, the
alternatives, the trade-offs. Stored under the decisions folder and numbered in order. When you
wonder "why is it done this way?", the ADRs are the answer. New decisions get a new ADR.

### As-built vs. target
Two different pictures of the system, kept as separate docs on purpose:
- **Target** — what we intend to build (the blueprint).
- **As-built** — what actually exists and runs *today*.
Keeping them separate prevents the common lie where docs describe a system that was never
finished.

### Definition of Done (DoD)
The checklist for what "finished" means here: not just working code, but updated docs, an ADR if
a new decision was made, a changelog entry, and green checks. A change isn't done until the
written record matches reality.

### Secret / key
A password, API key, token, or private cryptographic key — anything that grants access. The
number-one rule is that these **never** enter the project's history, because once committed
they're effectively exposed forever. Only example files with fake placeholder values are stored.

### Secret scanning (gitleaks)
An automatic scan that looks through changes for things that resemble secrets (keys, tokens) and
blocks them before they can be saved into history.

### SAST (Semgrep)
"Static Application Security Testing" — a tool (here, Semgrep) that reads the code without
running it and flags patterns known to be dangerous (for example, code that could run arbitrary
commands). A smoke detector for risky code.

### Dependency audit / pinning
- **Audit** — checking the third-party libraries you rely on for known vulnerabilities.
- **Pinning** — recording the *exact* version of each library, so an install is repeatable and a
  surprise update can't sneak in. Version changes then become explicit, reviewable edits.

### Supply chain
Everything your project depends on that you didn't write — libraries, base images, build tools.
A "supply-chain attack" is when one of those is tampered with. Pinning, auditing, and behavioral
scanning defend against it.

### Signing & provenance (cosign)
A way to cryptographically **sign** a built artifact (like a container image) and record where it
came from, so the server can **verify** it's genuine before running it. Prevents a swapped or
tampered build from being deployed. Used only if the deploy option is enabled.

### Egress firewall (sandbox)
A control in the development sandbox that **blocks outbound network connections** except to an
approved list (like the code host and package registries). If a dependency is malicious, it
can't "phone home" or steal data, because it simply can't reach the internet.

### Non-root image
A packaging choice where the service runs as a limited user, not as the all-powerful "root"
account. If the service is ever compromised, the attacker inherits fewer privileges.

### Compliance / observability spine
An optional built-in system that records *what the application did* in a tamper-evident log, and
automatically checks that every meaningful action is accounted for (recorded, monitored, and
audited). Useful when you must *prove* what happened — for audits or regulations.

### Principal / actor
"Who did this?" — the identity attached to an action (a user, or the system itself). The spine
records the principal as the actor on each event, so the log answers *who*, not just *what*.

### Hash-chained audit log
A record where each entry is cryptographically linked to the one before it, so you can detect if
any past entry was altered or deleted. Tamper-evidence for the activity log.

### Copier / template
**Copier** is the tool that created this project from a reusable **template**. It remembers your
answers, so later you can pull in improvements to the template without redoing your setup.

### Pre-commit hook
A check that runs on your own machine *before* a change is saved, catching simple problems (like
a stray secret or a formatting slip) early — before they ever reach the server.

### make check / make dod-check
Single commands that run the full set of local checks. `make check` runs the code gates (format,
types, security, tests); `make dod-check` verifies the docs still match the code. Green on both
means your change is in good shape.
