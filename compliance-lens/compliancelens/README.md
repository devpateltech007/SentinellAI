# compliancelens/ — the Python package

All the code lives here. (The folder name has no hyphen because Python package
names can't contain one.) `../audit.py` just starts `cli.main()`.

| Path | Version | Job |
| --- | --- | --- |
| `__init__.py` | V1 | Version number |
| `cli.py` | V2 | The commands (`run`, `history`, `verify`, `login`) and what they print |
| `runner.py` | V2 | Runs an audit and saves it (files, screenshots, database); verifies a saved run |
| `engine.py` | V1 | Loads and checks rules (V4: rule kinds, `ai_check`), calls collectors, applies checks, builds verdicts |
| `config.py` | V5 | `config/settings.yaml`: which rules are turned off for future audits |
| `run_options.py` | V5 | One set of run choices for the CLI and the dashboard (AI, screenshots, rules), checked the same way; starts the run |
| `locking.py` | V5 | One audit at a time: the lock shared by audits, the dashboard and the experiment's capture |
| `queries.py` | V5 | What the database says, ready to show: machine and effective verdicts, run states (incl. interrupted), the review queue, run comparison |
| `review.py` | V5 | Human reviews: checks (note, verdict, complete run, stale form) and saves one append-only row |
| `evidence.py` | V2 | Evidence files, meta files, screenshot banners (V3), saved documents (V4), manifest, SHA-256 checks |
| `connectors/` | V1 | Collect evidence from one system each; `browser.py` (V3) takes screenshots; `files.py` (V4) reads policy documents |
| `storage/` | V2 | SQLite results database |
| `evaluator/` | V4 | AI checks for screenshots and documents (any model, set in `.env`) |
| `dashboard/` | V5 | Web dashboard |
| `reporting/` | V6 | HTML/PDF reports |

Flow: `cli` (or the dashboard) → `run_options` → `runner` → `engine` → `connectors` → `engine` check → `connectors/browser`
screenshot (V3, rules with a `screenshot:` block) → `evaluator` AI check (V4, document and
vision rules, and cross-checks) → `evidence` + `storage`.

**Never put here:** secrets, evidence, or generated files.
