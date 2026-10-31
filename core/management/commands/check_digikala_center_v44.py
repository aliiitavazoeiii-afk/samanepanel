from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.template.loader import get_template
from django.urls import resolve, reverse

from core.digikala_center_v44 import (
    get_daily_orders_center,
    get_packages_board,
    get_products_board,
    get_returns_board,
    get_sales_board,
)


class Command(BaseCommand):
    help = "Validate Digikala Center V44 read-only corrections and optional live API behavior."

    def add_arguments(self, parser):
        parser.add_argument("--live", action="store_true")

    def handle(self, *args, **options):
        self._source_checks()
        if not options["live"]:
            self.stdout.write("DIGIKALA CENTER V44 SOURCE CHECK OK")
            return

        orders = get_daily_orders_center(force=True)
        if not orders.get("date_split_ok"):
            raise CommandError(f"future commitment date split failed: {orders.get('date_split_error') or orders.get('split_issue_variants')}")
        if int(orders.get("tomorrow_total") or 0) + int(orders.get("day_after_total") or 0) + int(orders.get("later_total") or 0) != int(orders.get("future_total") or 0):
            raise CommandError("future commitment split identity mismatch")
        self.stdout.write("V44 DAILY SPLIT")
        self.stdout.write(f"TOMORROW={orders.get('tomorrow_total', 0)} PRODUCTS={len(orders.get('tomorrow_products') or [])}")
        self.stdout.write(f"DAY_AFTER={orders.get('day_after_total', 0)} PRODUCTS={len(orders.get('day_after_products') or [])}")
        self.stdout.write(f"LATER={orders.get('later_total', 0)} PRODUCTS={len(orders.get('later_products') or [])}")
        self.stdout.write(f"FUTURE={orders.get('future_total', 0)}")
        self.stdout.write("SPLIT_OK=True")

        products = get_products_board(force=True)
        if int(products.get("variant_count") or 0) <= 0 or int(products.get("product_count") or 0) <= 0:
            raise CommandError("inventory-backed products page returned no products")
        self.stdout.write("V44 PRODUCTS")
        self.stdout.write(f"DKP={products.get('product_count', 0)}")
        self.stdout.write(f"DKPC={products.get('variant_count', 0)}")

        # Reuse the inventory cache loaded by products; do not fetch ~1,300 rows again.
        returns = get_returns_board(force=False)
        self.stdout.write("V44 RETURN WAREHOUSE")
        self.stdout.write(f"RETURN_QTY={returns.get('total', 0)}")
        self.stdout.write(f"RETURN_VARIANTS={returns.get('variant_count', 0)}")
        titles = sorted({title for row in returns.get("rows", []) for title in row.get("warehouse_titles", [])})
        self.stdout.write("RETURN_WAREHOUSES=" + (" | ".join(titles) if titles else "NONE"))
        if any("مرجوعی" not in title for title in titles):
            raise CommandError("non-return warehouse leaked into return board")

        packages = get_packages_board(force=True)
        self.stdout.write("V44 PACKAGES")
        self.stdout.write(f"AVAILABLE={packages.get('available', False)}")
        self.stdout.write(f"SOURCE={packages.get('source') or 'NONE'}")
        self.stdout.write(f"COUNT={packages.get('total', 0)}")

        try:
            sales = get_sales_board(force=True)
        except Exception as exc:
            raise CommandError(f"sales board failed: {exc}") from exc
        if not sales.get("source"):
            raise CommandError("sales board has no active source")
        self.stdout.write("V44 SALES")
        self.stdout.write(f"SOURCE={sales.get('source')}")
        self.stdout.write(f"MONTH={sales.get('jalali_month', '—')}")
        self.stdout.write(f"QTY={sales.get('total_quantity', 0)}")
        self.stdout.write(f"ROWS={sales.get('order_rows', 0)}")
        self.stdout.write("NO BUSINESS DATA CHANGED")
        self.stdout.write("DIGIKALA CENTER V44 LIVE READ OK")

    def _source_checks(self):
        for name in (
            "core/digikala_shared_v44.py",
            "core/digikala_center_v44.py",
            "templates/core/digikala_products_v44.html",
            "templates/core/digikala_returns_v43.html",
        ):
            if not Path(name).is_file():
                raise CommandError(f"missing V44 source: {name}")

        center = Path("core/digikala_center_v44.py").read_text(encoding="utf-8")
        shared = Path("core/digikala_shared_v44.py").read_text(encoding="utf-8")
        returns_page = Path("templates/core/digikala_returns_v43.html").read_text(encoding="utf-8")
        settings = Path("config/settings.py").read_text(encoding="utf-8")

        if '"search[is_effective]"' in center:
            raise CommandError("future commitment splitter still uses is_effective")
        for required in (
            '"search[to_commitment_date]"',
            '"/open-api/v1/orders/history"',
            '"/open-api/v1/orders"',
            '"مرجوعی"',
            "get_inventory_rows",
        ):
            if required not in center:
                raise CommandError(f"V44 source marker missing: {required}")
        if "ThreadPoolExecutor" not in shared or "MAX_PAGE_WORKERS = 3" not in shared:
            raise CommandError("bounded pagination concurrency missing")
        if "FileBasedCache" not in settings:
            raise CommandError("shared multi-worker cache missing")
        if "r.return_stock" in returns_page:
            raise CommandError("old return_stock UI leaked into V44")

        route_expectations = {
            "digikala_orders": "/digikala/orders/",
            "digikala_products": "/digikala/products/",
            "digikala_packages": "/digikala/packages/",
            "digikala_sales": "/digikala/sales/",
            "digikala_returns": "/digikala/returns/",
        }
        for name, expected in route_expectations.items():
            path = reverse(name)
            if path != expected:
                raise CommandError(f"route mismatch {name}: {path}")
            resolve(path)

        for template in (
            "core/digikala_center_v43.html",
            "core/digikala_orders_v43.html",
            "core/digikala_products_v44.html",
            "core/digikala_packages_v43.html",
            "core/digikala_sales_v43.html",
            "core/digikala_returns_v43.html",
        ):
            get_template(template)
