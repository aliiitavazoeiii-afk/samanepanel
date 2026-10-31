from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.template.loader import get_template
from django.urls import resolve, reverse

from core.digikala_center_v43 import get_daily_orders_center, get_packages_board


class Command(BaseCommand):
    help = "Check Digikala Center V43 routes/templates/read-only source and optional live date split."

    def add_arguments(self, parser):
        parser.add_argument("--live", action="store_true")

    def handle(self, *args, **options):
        expected = {
            "digikala": "digikala_home",
            "digikala_orders": "digikala_orders",
            "digikala_packages": "digikala_packages",
            "digikala_sales": "digikala_sales",
            "digikala_warehouse": "digikala_warehouse",
            "digikala_returns": "digikala_returns",
        }
        for route_name, function_name in expected.items():
            match = resolve(reverse(route_name))
            if getattr(match.func, "__name__", "") != function_name:
                raise CommandError(f"route {route_name} does not resolve to {function_name}")

        detail = resolve(reverse("digikala_package_detail", kwargs={"package_id": 1}))
        if getattr(detail.func, "__name__", "") != "digikala_package_detail":
            raise CommandError("package detail route mismatch")

        for template in (
            "core/digikala_center_v43.html",
            "core/digikala_orders_v43.html",
            "core/digikala_packages_v43.html",
            "core/digikala_package_detail_v43.html",
            "core/digikala_sales_v43.html",
            "core/digikala_returns_v43.html",
            "core/_digikala_nav_v43.html",
        ):
            get_template(template)

        source = Path("/app/core/digikala_center_v43.py").read_text(encoding="utf-8")
        views = Path("/app/core/digikala_views_v40.py").read_text(encoding="utf-8")
        urls = Path("/app/core/urls.py").read_text(encoding="utf-8")

        required_source = (
            "get_daily_orders_center",
            "get_packages_board",
            "get_sales_board",
            "get_returns_board",
            '"product_id": _int(row.get("productId"))',
            '"variant_id": variant_id',
            'search[to_commitment_date]',
        )
        for token in required_source:
            if token not in source:
                raise CommandError(f"V43 source token missing: {token}")

        for token in (
            'path("digikala/orders/"',
            'path("digikala/packages/"',
            'path("digikala/sales/"',
            'path("digikala/returns/"',
        ):
            if token not in urls:
                raise CommandError(f"V43 route missing: {token}")

        if "digikala_center_v43.html" not in views:
            raise CommandError("Digikala home does not render V43 center")

        forbidden = (
            "SaleLine.objects.create",
            "SaleLine.objects.update",
            "StockBalance.objects",
            "InventoryMovement.objects",
            "AccountEntry.objects",
            "transaction.atomic",
            "requests.post",
            "requests.put",
            "requests.patch",
            "requests.delete",
        )
        for token in forbidden:
            if token in source:
                raise CommandError(f"read-only boundary violated by token: {token}")

        self.stdout.write(self.style.SUCCESS("DIGIKALA CENTER V43 SOURCE CHECK OK"))

        if not options["live"]:
            return

        orders = get_daily_orders_center(force=True)
        self.stdout.write(
            "V43 DAILY SPLIT: "
            f"tomorrow={orders.get('tomorrow_total', 0)} "
            f"day_after={orders.get('day_after_total', 0)} "
            f"later={orders.get('later_total', 0)} "
            f"delayed={orders.get('delayed_total', 0)} "
            f"future={orders.get('future_total', 0)} "
            f"split_ok={orders.get('date_split_ok', False)}"
        )
        if orders.get("date_split_error"):
            self.stdout.write(self.style.WARNING(f"V43 DATE SPLIT FILTER FALLBACK: {orders['date_split_error']}"))
        elif orders.get("tomorrow_total", 0) + orders.get("day_after_total", 0) + orders.get("later_total", 0) != orders.get("future_total", 0):
            raise CommandError("V43 future date split does not reconcile to nextDays total")

        packages = get_packages_board(force=True)
        if packages.get("available"):
            self.stdout.write(self.style.SUCCESS(f"V43 PACKAGE ENDPOINT OK rows={packages.get('total', 0)}"))
        else:
            self.stdout.write(self.style.WARNING(f"V43 PACKAGE ENDPOINT NOT YET VERIFIED: {packages.get('error') or 'no usable response'}"))

        self.stdout.write(self.style.SUCCESS("DIGIKALA CENTER V43 LIVE READ CHECK FINISHED"))
