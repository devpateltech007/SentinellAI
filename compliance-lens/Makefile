# ComplianceLens shortcuts. Run `make help` to see them.
# Every command uses the project's own virtual environment in .venv/.

PYTHON ?= python3.11
VENV   := .venv
BIN    := $(VENV)/bin

.DEFAULT_GOAL := help
.PHONY: help setup test lint format audit history verify clean

help:  ## Show this list
	@grep -E '^[a-z]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-8s %s\n", $$1, $$2}'

setup:  ## Create .venv, install everything, turn on git hooks
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -r requirements-dev.txt
	$(BIN)/pip install -e .
	@if [ -f ../.pre-commit-config.yaml ]; then $(BIN)/pre-commit install; \
	else echo "No ../.pre-commit-config.yaml yet: skipping git hooks"; fi
	@echo "Done. Next: cp .env.example .env  and fill it in."

test:  ## Run all tests with a coverage report
	$(BIN)/pytest --cov

lint:  ## Check code style (no changes made)
	$(BIN)/ruff check .
	$(BIN)/ruff format --check .

format:  ## Fix code style automatically
	$(BIN)/ruff check --fix .
	$(BIN)/ruff format .

audit:  ## Run a compliance audit (all rules)
	$(BIN)/python audit.py run

history:  ## Show past audit runs
	$(BIN)/python audit.py history

verify:  ## Check a run's evidence: make verify RUN=run-0007
	@if [ -z "$(RUN)" ]; then echo "Usage: make verify RUN=run-0007"; exit 2; fi
	$(BIN)/python audit.py verify $(RUN)

clean:  ## Delete caches and the virtual environment (keeps evidence)
	rm -rf $(VENV) .pytest_cache .ruff_cache .coverage htmlcov build dist *.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
