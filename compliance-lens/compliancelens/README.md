# compliancelens/ — the Python package

All the code lives here. (The folder name has no hyphen because Python package
names can't contain one.) `../audit.py` just starts `cli.main()`.

| Path | Version | Job |
| --- | --- | --- |
| `__init__.py` | V1 | Version number |
| `cli.py` | V1 | Runs the audit and prints results (V2: subcommands) |
| `engine.py` | V1 | Loads rules, calls collectors, applies checks, builds verdicts |
| `evidence.py` | V1 | Saves each result as JSON (V2: meta files, manifest, verify) |
| `connectors/` | V1 | Collect evidence from one system each |
| `storage/` | V2 | SQLite results database |
| `evaluator/` | V4 | AI checks for screenshots and documents |
| `dashboard/` | V5 | Web dashboard |
| `reporting/` | V6 | HTML/PDF reports |

Flow: `cli` → `engine` → `connectors` → `engine` check → `evidence`.

**Never put here:** secrets, evidence, or generated files.
