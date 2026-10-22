# ComplianceLens shortcuts. Run `make help` to see them.
# Every command uses the project's own virtual environment in .venv/.

PYTHON ?= python3.11
VENV   := .venv
BIN    := $(VENV)/bin

.DEFAULT_GOAL := help
.PHONY: help setup test lint format audit crosscheck history verify report login aitest dashboard experiment analyze clean

help:  ## Show this list
	@grep -E '^[a-z]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-10s %s\n", $$1, $$2}'

setup:  ## Create .venv, install everything (and Chromium), turn on git hooks
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -r requirements-dev.txt
	$(BIN)/pip install -e .
	$(BIN)/python -m playwright install chromium
	@if [ -f ../.pre-commit-config.yaml ]; then $(BIN)/pre-commit install; \
	else echo "No ../.pre-commit-config.yaml yet: skipping git hooks"; fi
	@echo "Done. Next: cp .env.example .env  and fill it in."
	@echo "PDF reports need the Pango libraries (macOS: brew install pango)."

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

crosscheck:  ## Audit, and let the AI also read the code rules' screenshots (verdicts unchanged)
	$(BIN)/python audit.py run --cross-check

history:  ## Show past audit runs
	$(BIN)/python audit.py history

verify:  ## Check a run's evidence: make verify RUN=run-0007
	@if [ -z "$(RUN)" ]; then echo "Usage: make verify RUN=run-0007"; exit 2; fi
	$(BIN)/python audit.py verify $(RUN)

report:  ## Export a run's audit report: make report RUN=run-0042 [FORMAT=html|pdf|both]
	@if [ -z "$(RUN)" ]; then echo "Usage: make report RUN=run-0042 [FORMAT=html|pdf|both]"; exit 2; fi
	$(BIN)/python audit.py report $(RUN) --format $(or $(FORMAT),both)

login:  ## Save a login for screenshots: make login SITE=github (or aws)
	@if [ -z "$(SITE)" ]; then echo "Usage: make login SITE=github   (or SITE=aws)"; exit 2; fi
	$(BIN)/python audit.py login $(SITE)

aitest:  ## Check the AI model set in .env (one text and one image call)
	$(BIN)/python audit.py ai-test

dashboard:  ## Web dashboard on http://127.0.0.1:8000 (needs DASHBOARD_PASSWORD in .env)
	$(BIN)/python -m compliancelens.dashboard

experiment:  ## Research experiment: the AI judges every captured case 3 times (resumes)
	$(BIN)/python -m experiment.lab run --resume

analyze:  ## Research experiment: the results tables (no AI call)
	$(BIN)/python -m experiment.lab analyze

clean:  ## Delete caches and the virtual environment (keeps evidence and logins)
	rm -rf $(VENV) .pytest_cache .ruff_cache .coverage htmlcov build dist *.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
