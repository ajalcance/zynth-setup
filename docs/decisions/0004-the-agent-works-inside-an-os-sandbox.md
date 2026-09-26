# 0004. The agent works inside an OS sandbox on this repository

Date: 2026-09-26

## Status

Accepted.

## Context

Until now the agent working here was held by two layers: permission rules in
`.claude/settings.json`, and the session hooks that read each Bash command line
(`confine_to_project.py`, `block_dangerous_bash.py`). Both judge **the command the agent
types**. Neither sees what that command launches: a test runner, a build tool, an install
script, a poisoned dependency. `make verify` alone runs copier, pip, npm, semgrep, pytest and
gitleaks. Any of them could read `~/.ssh`, another project, or the owner's GitHub login, and
could reach any host.

The owner has an "Agent Sandbox Kit": macOS Seatbelt through Claude Code's `sandbox`
settings, first proved on zynth-auth. It wraps every command and every process that command
starts. The owner asked for it here, and **only here, not in the template**.

## Decision

1. **The sandbox is on for this repository**, configured by the kit's generator (v4) in
   `.claude/settings.local.json`: machine-local, git-ignored, the owner's. The agent's file
   tools are denied edits to it, and the sandbox denies its shell the same. So only the owner
   can change it, from their own terminal. MAINTAINING.md records how to apply, roll back and
   renew it.
2. **What it holds:**
   - **Blocked:** every sibling project and the folder that holds them; other projects' Claude
     memory; `~/.ssh`, `~/.config/gh` and the other credential stores; the project's `.env`
     files; writes to `.claude/`, `.git/config` and git hooks; any host that is not one of
     GitHub, PyPI, npm or semgrep.dev.
   - **The rest of the home folder** (`scripts/sandbox-home-walls.sh`): Desktop, Downloads,
     the rest of Documents, Pictures, Movies, Music, Mail, Messages, Safari, cookies, iCloud
     Drive, browser profiles, shell history, and other AI tools' configuration. The kit walls
     off siblings and credentials only; a prompt-injected build step reading `~/Downloads` is
     the same leak. `.env` files are also denied to the file tools by name, at any depth.
   - **Machine-wide**, through managed settings no project can override: no project's agent
     may edit its own settings, the user's settings, or the managed settings themselves.
   - **Allowed:** writes inside the project, `$TMPDIR` and the tool caches named in
     MAINTAINING.md.
   - `failIfUnavailable` is on, and no unsandboxed command is allowed.
3. **The agent's GitHub identity is a repo-only fine-grained token** (`GH_CONFIG_DIR`), not
   the owner's login. `gh` runs outside the sandbox (Go's TLS cannot run inside it), so the
   token is what bounds it. The token has no admin, secrets or settings scope. It cannot
   change a ruleset or apply a label a PR check reads. That is still the owner's account to
   GitHub: separation needs a separate machine account (backlog C3).
4. **Tools that cannot use the macOS trust store inside the sandbox get it by environment**,
   not by a wider sandbox:
   - pip: `PIP_USE_DEPRECATED=legacy-certs` and `PIP_CERT=/etc/ssl/cert.pem`. It verifies
     against the system's certificate file, because the bundle it vendors inside `.venv` is a
     `*.pem` file that this repository's own `Read(./**/*.pem)` rule makes unreadable;
   - `SSL_CERT_FILE=/etc/ssl/cert.pem` (semgrep);
   - semgrep's log, settings and version check moved into an already-allowed cache.

   TLS is verified in every case.
5. **Proved, not assumed.** `make sandbox-verify` (`scripts/check_sandbox.py`) runs 17 probes,
   each in its own child process. 14 must be refused. 3 are controls it must allow, including
   this project inside the walled Documents, so a sandbox that refuses everything cannot pass.
   A walled folder is probed by listing it: Seatbelt lets a folder's lookup through and
   refuses only its listing, so a `stat()` probe reads "allowed" on a wall that holds. The
   check prints the denominator, and it fails outside the sandbox, in CI or the owner's
   terminal, by design. Three things a child process cannot observe are checked by hand after
   any change to the settings:
   - a standalone `gh` works with the repo-only token;
   - that token is refused another repository: `gh api repos/<owner>/<other>/collaborators`
     answers 403, "Resource not accessible by personal access token". It still *lists* the
     owner's public repositories, because anyone may read those;
   - the agent's Read tool is refused a file in a sibling project.
6. **Not in the template.** The kit is macOS-specific and its settings name this machine's
   paths. The template already ships its own isolation for adopters: the agent devcontainer.
   What the sandbox teaches about the template is recorded in `docs/BACKLOG.md`.
7. **When a check fails inside the sandbox, fix the check, never widen the sandbox.** A
   blocked host or path is named in the violation. It is added only when real work needs it,
   through the owner, and never by the agent.

## Consequences

- Working habits change; CLAUDE.md §4 lists them. The main ones:
  - `gh` and `git commit` run as standalone commands;
  - no `git push -u` and no tracking branches, because both write `.git/config`;
  - commit messages come from a file.
- Running the gates inside the sandbox found four problems on day one:
  - The pre-commit end-of-file fixer opens `.claude/*` files for writing.
  - `make verify`'s scratch generations cannot create their own `.git/config`, hooks or
    `*.pem` files inside the project.
  - pip and semgrep failed TLS. For pip in a project venv, the cause is partly ours: the
    `*.pem` deny rule, which the template ships too (backlog T20).
  - The secret scan's downloader ignores `HTTPS_PROXY`, so it cannot fetch gitleaks
    through any proxy. That affects adopters behind a corporate proxy too (backlog T19).

  The TLS failures are fixed by decision 4. The other three are guard changes, each its own
  pull request. Until they merge, the owner runs `make hooks` and `make verify` from their
  own terminal, where CI runs them too.
- The sandbox is per machine. A second maintainer, or a new Mac, has no sandbox until the kit
  is applied there. `make sandbox-verify` says so at once.
