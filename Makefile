# The template REPOSITORY's own gate — what this repo asks of itself before a change merges.
#
# The template ships `make check` to every adopter; this is the same idea for the repository
# that ships it. One definition, two invocations: CI runs `make check PY=python3` (the `repo`
# job in .github/workflows/template-test.yml) and a maintainer runs `make check` locally.
# Generated projects are proved separately, by the self-test's `generate` matrix.
#
#   make check    hooks + lint + policy + test (run before every push)
#   make hooks    the pre-commit hooks over every file (hooks-install: run them on commit)
#   make lint     ruff + black on the root harness; shellcheck; actionlint + zizmor on workflows
#   make policy   secret scan with canary, unicode hazards, pins, ignore rules, Jinja, owner tier
#   make test     fault tests for the root guards and the repository's own invariants
#   make venv     a root .venv with the pinned tools (requirements-selftest.txt)
PY ?= .venv/bin/python
ZIZMOR ?= .venv/bin/zizmor
CI_TOOLS ?= $(HOME)/.cache/ci-tools
# The root harness. template/ has its own gates and is proved by generating from it.
HARNESS := scripts tests

.PHONY: help check hooks hooks-install lint policy test venv

help:
	@echo "Targets: check | hooks | hooks-install | lint | policy | test | venv"

check: hooks lint policy test

venv:
	python3 -m venv .venv
	.venv/bin/pip install -q -c requirements-selftest.txt copier jinja2 pyyaml pytest ruff black zizmor pre-commit

# The same hooks the template ships, at the same SHAs (.pre-commit-config.yaml).
hooks:
	$(PY) -m pre_commit run --all-files --show-diff-on-failure

hooks-install:
	$(PY) -m pre_commit install

# The template's harness rule set, not a second one: template/ruff-harness.toml.
lint:
	$(PY) -m ruff check --config template/ruff-harness.toml $(HARNESS)
	$(PY) -m black --check -q -l 100 $(HARNESS)
	shellcheck scripts/*.sh
	template/scripts/ci_tools.sh "$(CI_TOOLS)"
	"$(CI_TOOLS)/actionlint" -color
	$(ZIZMOR) --offline .github/workflows

policy:
	$(PY) scripts/secret_scan.py --auto
	$(PY) scripts/check_unicode_hazards.py
	$(PY) template/scripts/check_pins.py requirements-selftest.txt
	scripts/check-tracked-ignores.sh
	PYTHON=$(PY) scripts/check-jinja-syntax.sh
	$(PY) scripts/check-owner-questions.py

test:
	$(PY) -m pytest -q tests
