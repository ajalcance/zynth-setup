# Lessons — building and releasing the template

Mistakes that were made here, kept so they are made once. Each is short on purpose: the rule it
produced is in CLAUDE.md, and the check that holds it is named. Template-facing lessons for
adopters live in `template/docs/LESSONS.md`.

- **A check that inspected nothing reports green.** A secret scan that read no commits, a
  Jinja check that skipped without jinja2, a hooks gate that commits with no hook installed —
  all printed OK. Every check prints what it inspected and refuses an empty set. (CLAUDE.md 5.)
- **Verification from a subset is not verification.** Scratch runs skipped the generated
  project's own pre-commit hooks; two blank lines reached CI. `make verify` runs every gate in
  every variant. (CLAUDE.md 2.)
- **A tame test input hides real bugs.** The self-test used the project name `CI Demo` for
  months; long names broke ruff and prettier on day one for adopters. Keep the long-name leg.
- **Interpolating a copier value into a linted line breaks the adopter's first commit.** Use a
  short constant or `| tojson`. (CLAUDE.md 6.)
- **A permission rule is a prefix glob.** `git push origin v1 --force` does not match a deny on
  `git push --force*`. Test a rule with the dangerous flag last. (Template ADR-0007.)
- **A hook's `allow` loses to a static `ask`.** A scope hook that returned `allow` waived
  nothing for a day. Test a control through the path it has to hold, not where it is easiest.
- **GitHub ignores `env:` overrides of `GITHUB_*` variables**, silently. (CLAUDE.md 9.)
- **The first pull request is the first test of the pull-request path.** Every self-test run
  was a push until PR #6; two gates had never run on a PR event.
- **Tagging changes what "the previous release" means.** (CLAUDE.md 10.)
- **A version that sorts low is a release nobody gets.** `v0.3.1` after `v3.1.0`. (ADR 0003.)
- **Green is a moving target.** Live advisory databases turn a pinned project red with no
  change here; the daily scheduled self-test is load-bearing.
- **Job count is the CI cost driver**, not duration — GitHub bills each job rounded up to a
  minute. Batch short checks; keep label re-runs off the generation matrix.
- **A test that reads the working tree passes on the machine that wrote it.** The cited-paths
  check resolved against the disk, where an ignored local settings file existed; CI's clean
  checkout failed it. Resolve against `git ls-files`. Green locally is one environment.
- **A surviving mutant is a missing test.** Two tests once named a bug and did not exercise
  it. (CLAUDE.md 4.)
