import os
import stat
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from core.digikala_client_v40 import (
    ACCESS_TOKEN_FILE,
    REFRESH_TOKEN_FILE,
    SECRET_DIR,
    DigikalaAPIError,
    get_summary,
)


class Command(BaseCommand):
    help = "Validate V40 Digikala secret mount and optionally the live read-only API."

    def add_arguments(self, parser):
        parser.add_argument(
            "--live",
            action="store_true",
            help="Call only the approved GET endpoints (plus token refresh if the access token expired).",
        )

    def _check_secret(self, path: Path):
        if not path.is_file():
            raise CommandError(f"Missing Digikala secret file: {path}")
        if not path.read_text(encoding="utf-8").strip():
            raise CommandError(f"Empty Digikala secret file: {path.name}")
        mode = stat.S_IMODE(os.stat(path).st_mode)
        if mode & 0o077:
            raise CommandError(f"Unsafe permissions on {path.name}: {oct(mode)} (expected no group/world access)")

    def handle(self, *args, **options):
        if not SECRET_DIR.is_dir():
            raise CommandError(f"Digikala secret directory is not mounted: {SECRET_DIR}")
        self._check_secret(ACCESS_TOKEN_FILE)
        self._check_secret(REFRESH_TOKEN_FILE)
        self.stdout.write("DIGIKALA SECRET MOUNT OK")

        if options["live"]:
            try:
                summary = get_summary(force=True)
            except DigikalaAPIError as exc:
                raise CommandError(str(exc)) from exc
            if not summary.get("connected"):
                raise CommandError("Digikala API returned no successful read-only response")
            required = ["orders_total", "inventory_total", "commitments_total", "invoices_total"]
            missing = [key for key in required if key not in summary]
            if missing:
                raise CommandError(f"Digikala summary missing keys: {', '.join(missing)}")
            self.stdout.write(
                "DIGIKALA LIVE READ OK "
                f"orders={summary['orders_total']} "
                f"inventory={summary['inventory_total']} "
                f"commitments={summary['commitments_total']} "
                f"invoices={summary['invoices_total']} "
                f"partial_errors={len(summary.get('errors') or {})}"
            )

        self.stdout.write("NO BUSINESS DATA CHANGED")
        self.stdout.write(self.style.SUCCESS("DIGIKALA V40 CHECK OK"))
