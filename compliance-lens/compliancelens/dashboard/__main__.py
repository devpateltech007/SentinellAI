"""python -m compliancelens.dashboard [--port 8000] [--host 127.0.0.1] [--rules-file ...]

Serves the dashboard on this computer only (127.0.0.1) unless --host says otherwise.
One process: the audit lock and the job manager assume a single worker.
"""

import argparse
import ipaddress
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

from compliancelens.cli import PROJECT_ROOT, RULES_FILE
from compliancelens.dashboard import app, auth


def _is_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m compliancelens.dashboard")
    parser.add_argument("--host", default="127.0.0.1", help="address to listen on")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--rules-file", type=Path, default=RULES_FILE)
    args = parser.parse_args(argv)

    load_dotenv(PROJECT_ROOT / ".env")
    hosts = auth.LOCAL_HOSTS if _is_loopback(args.host) else (*auth.LOCAL_HOSTS, args.host)
    settings = auth.Settings.from_env(args.rules_file, hosts)
    if settings.password is None:
        print(f"Warning: {auth.PASSWORD_ENV} is not set in .env: nobody can sign in.")
    if not _is_loopback(args.host):
        print(f"Warning: listening on {args.host}: other computers can reach the sign-in page.")
    print(f"ComplianceLens dashboard: http://{args.host}:{args.port}/  (Ctrl+C to stop)")
    uvicorn.run(app.create_app(settings), host=args.host, port=args.port, workers=1)
    return 0


if __name__ == "__main__":  # pragma: no cover - started by `python -m`
    raise SystemExit(main())
