"""Entry point. Run an audit with:  python audit.py

All the real code lives in the compliancelens/ package; this file only starts it.
"""

import sys

from compliancelens.cli import main

if __name__ == "__main__":
    sys.exit(main())
