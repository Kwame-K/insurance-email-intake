import argparse
from pathlib import Path

import uvicorn

from insurance_email_intake.api import build_service
from insurance_email_intake.models import IntakeStatus
from insurance_email_intake.settings import get_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="insurance-email-intake")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan", help="Process every .eml file once.")
    scan.add_argument("--inbox", type=Path, default=None)

    serve = subparsers.add_parser("serve", help="Run the HTTP API.")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8004)

    args = parser.parse_args(argv)
    settings = get_settings()

    if args.command == "scan":
        service = build_service(settings)
        results = service.scan_inbox(args.inbox or settings.inbox_dir)
        for result in results:
            print(
                f"[{result.status}] {result.source_id} "
                f"workflow={result.workflow_status} decision={result.decision} "
                f"missing={result.missing_fields}"
            )
        ok = {IntakeStatus.PROCESSED, IntakeStatus.DUPLICATE}
        return 0 if all(result.status in ok for result in results) else 1

    uvicorn.run(
        "insurance_email_intake.api:create_app",
        factory=True,
        host=args.host,
        port=args.port,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
