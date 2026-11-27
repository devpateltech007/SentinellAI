# ComplianceLens in a container (V7 stretch goal: Docker).
#
#   docker build -t compliancelens .                        the tool (the last stage: runtime)
#   docker build -t compliancelens-test --target test .   the tool plus the test suite
#
# No secrets are built in: .env, sessions/, evidence/, the database, settings.yaml and
# employees.csv are mounted at run time (.dockerignore keeps them out of the build).

FROM python:3.12-slim-trixie AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Pango for the PDF report (WeasyPrint); fonts so screenshots and PDFs have real text.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 \
        fonts-dejavu-core fonts-liberation fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Pinned libraries first, so code changes don't reinstall them.
COPY requirements.txt .
RUN pip install -r requirements.txt \
    && python -m playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

# The tool itself. It runs from /app (not installed as a package) because it finds
# rules/, config/, evidence/ and the database next to its own folder.
COPY pyproject.toml README.md Makefile audit.py ./
COPY compliancelens/ compliancelens/
COPY rules/ rules/
COPY policies/ policies/
COPY config/ config/
COPY data/ data/
COPY evidence/ evidence/
COPY sessions/ sessions/
COPY reports/ reports/

# Run as a normal user, never root. It owns the folders the tool writes to.
RUN useradd --create-home --uid 1000 app \
    && mkdir -p logs \
    && chown -R app:app /app
USER app

CMD ["python", "audit.py", "--help"]


# The same image plus the developer libraries and the tests: `make test` on Linux.
FROM base AS test
USER root
COPY requirements-dev.txt .
RUN pip install -r requirements-dev.txt
COPY tests/ tests/
COPY experiment/ experiment/
COPY scripts/ scripts/
COPY docs/ docs/
RUN chown -R app:app /app
USER app
CMD ["python", "-m", "pytest", "--cov", "--cov-report=term-missing:skip-covered", "-q"]


# The image people run (last, so a plain `docker build` makes this one).
FROM base AS runtime
