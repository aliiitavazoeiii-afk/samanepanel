from django.core.management.base import BaseCommand, CommandError

from core.digikala_client_v40 import DigikalaAPIError
from core.digikala_delivery_v41 import get_delivery_board


class Command(BaseCommand):
    help = "Validate V41 read-only Digikala delivery commitments board."

    def add_arguments(self, parser):
        parser.add_argument("--live", action="store_true")

    def handle(self, *args, **options):
        if not options["live"]:
            self.stdout.write("V41 delivery module import OK")
            self.stdout.write(self.style.SUCCESS("DIGIKALA DELIVERY V41 CHECK OK"))
            return

        try:
            board = get_delivery_board(force=True)
        except DigikalaAPIError as exc:
            raise CommandError(str(exc)) from exc

        required = [
            "effective_total",
            "total_commitments",
            "future_total",
            "today_total",
            "delayed_total",
            "variant_count",
            "rows",
        ]
        missing = [key for key in required if key not in board]
        if missing:
            raise CommandError(f"V41 board missing keys: {', '.join(missing)}")
        if board["total_commitments"] < board["effective_total"]:
            raise CommandError("Digikala total commitments is lower than effective commitments")
        if not isinstance(board["rows"], list):
            raise CommandError("Digikala delivery rows is not a list")
        row_sum = sum(int(row.get("due_qty") or 0) for row in board["rows"])
        if row_sum != int(board.get("actionable_rows_total") or 0):
            raise CommandError("V41 delivery row sum does not match actionable row total")

        self.stdout.write(
            "DIGIKALA DELIVERY LIVE READ OK "
            f"effective={board['effective_total']} "
            f"total={board['total_commitments']} "
            f"future={board['future_total']} "
            f"today={board['today_total']} "
            f"delayed={board['delayed_total']} "
            f"variants={board['variant_count']} "
            f"rows_sum={row_sum} "
            f"counts_match={board['counts_match']}"
        )
        self.stdout.write("NO INTERNAL BUSINESS DATA CHANGED")
        self.stdout.write(self.style.SUCCESS("DIGIKALA DELIVERY V41 CHECK OK"))
