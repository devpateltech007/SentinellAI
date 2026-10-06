"""Entry point. Run an audit with:  python audit.py   (or: python audit.py run)

Other commands: python audit.py history, python audit.py verify run-0007,
python audit.py login github (or aws) to save a login for screenshots.
All the real code lives in the compliancelens/ package; this file only starts it.
"""

from compliancelens.cli import main

if __name__ == "__main__":
    main()
