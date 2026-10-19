"""The research experiment (V4 Stage 5): how well does an AI read compliance settings
from screenshots, compared with code reading the same settings from the API?

    python -m experiment.lab --help        (run from compliance-lens/)

1. capture   change the test accounts to make each case, take the picture, put the
             settings back (world.py, capture.py)
2. labels    two people label every picture separately (labels.py)
3. run       the AI judges every picture 3 times (run.py)
4. analyze   accuracy, false PASS, abstentions, consistency, cost (analyze.py)

Unlike the audit tool in compliancelens/, this package CHANGES settings (only in
world.py, with its own logins). See experiment/README.md.
"""

import os
from pathlib import Path

EXPERIMENT_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = EXPERIMENT_DIR.parent
DATA_ENV = "COMPLIANCELENS_EXPERIMENT_DATA"  # tests point both at temporary files
LABELS_ENV = "COMPLIANCELENS_EXPERIMENT_LABELS"


def data_dir() -> Path:
    """experiment/data/ (gitignored): pictures, API data, AI answers, labelling packs."""
    return Path(os.environ.get(DATA_ENV) or EXPERIMENT_DIR / "data")


def labels_path() -> Path:
    """experiment/labels.csv: committed, and fixed before the AI runs."""
    return Path(os.environ.get(LABELS_ENV) or EXPERIMENT_DIR / "labels.csv")
