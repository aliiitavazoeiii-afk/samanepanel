from django.core.management.base import BaseCommand, CommandError

from core.capital_history_v87 import capital_as_of, current_capital_breakdown
from core.dateutils import format_jalali, parse_jalali_date


class Command(BaseCommand):
    help = "V87 read-only check for selected-period capital reconstruction."

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            required=True,
            help="Jalali date, for example 1405/06/15",
        )

    def handle(self, *args, **options):
        try:
            as_of = parse_jalali_date(options["date"])
        except Exception as exc:
            raise CommandError(f"Invalid Jalali date: {exc}")

        current = current_capital_breakdown()
        result = capital_as_of(as_of)

        self.stdout.write(f"as_of={format_jalali(as_of)}")
        self.stdout.write(f"current_capital={int(current['capital_total'])}")
        self.stdout.write(f"period_end_capital={int(result['capital_total'])}")
        self.stdout.write(f"post_period_delta={int(result.get('post_period_delta') or 0)}")
        self.stdout.write(f"source={result.get('source')}")

        parts = result.get("delta_parts") or {}
        for key in sorted(parts):
            self.stdout.write(f"delta.{key}={int(parts[key] or 0)}")

        warnings = result.get("warnings") or []
        self.stdout.write(f"warnings={len(warnings)}")
        for index, warning in enumerate(warnings, 1):
            self.stdout.write(f"warning.{index}={warning}")

        if not result.get("is_historical") and int(result["capital_total"]) != int(current["capital_total"]):
            raise CommandError("Current capital invariant failed.")

        self.stdout.write(self.style.SUCCESS("V87 historical-capital check completed (read-only)."))
