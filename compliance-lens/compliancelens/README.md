# compliancelens/ — the Python package

All the code lives here. (The folder name has no hyphen because Python package
names can't contain one.) `../audit.py` just starts `cli.main()`.

| Path | Version | Job |
| --- | --- | --- |
| `__init__.py` | V1 | Version number |
| `cli.py` | V2 | The commands (`run`, `history`, `verify`) and what they print |
| `runner.py` | V2 | Runs an audit and saves it (files + database); verifies a saved run |
| `engine.py` | V1 | Loads and checks rules, calls collectors, applies checks, builds verdicts |
| `evidence.py` | V2 | Evidence files, meta files, manifest, SHA-256 checks |
| `connectors/` | V1 | Collect evidence from one system each |
| `storage/` | V2 | SQLite results database |
| `evaluator/` | V4 | AI checks for screenshots and documents |
| `dashboard/` | V5 | Web dashboard |
| `reporting/` | V6 | HTML/PDF reports |

Flow: `cli` → `runner` → `engine` → `connectors` → `engine` check → `evidence` + `storage`.

**Never put here:** secrets, evidence, or generated files.
