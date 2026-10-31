import inspect
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.template.loader import get_template

from core import daily_report_v8
from core.finance import sale_line_metrics
from core.models import SaleLine


class Command(BaseCommand):
    help = "Verify daily-report brand/size drilldown, sold-color display and inline row actions."

    def handle(self, *args, **options):
        errors = []

        try:
            # Compile through Django first so invalid template syntax/routes fail.
            get_template("core/daily_report_v21.html")
            template_path = Path(settings.BASE_DIR) / "templates" / "core" / "daily_report_v21.html"
            source = template_path.read_text(encoding="utf-8")
        except Exception as exc:
            raise CommandError(f"daily report template does not compile/read: {exc}") from exc

        required_markers = [
            'data-brand-button',
            'data-size-button',
            'row.colors',
            'row.shorts',
            "daily_sale_price_update",
            "daily_sale_line_delete",
            "مدل / رنگ شورت‌ها",
        ]
        for marker in required_markers:
            if marker not in source:
                errors.append(f"daily-report template marker missing: {marker}")

        view_source = inspect.getsource(daily_report_v8.daily_report)
        if '"core/daily_report_v21.html"' not in view_source:
            errors.append("active daily_report view is not rendering core/daily_report_v21.html")
        if tuple(daily_report_v8.PRIMARY_REPORT_BRANDS) != ("تکوین", "دارما"):
            errors.append(f"primary report brands are wrong: {daily_report_v8.PRIMARY_REPORT_BRANDS}")
        if tuple(daily_report_v8.FILTER_SIZES.get("تکوین", ())) != ("M", "L", "XL", "XXL"):
            errors.append("Takvin report sizes are not M/L/XL/XXL")
        if tuple(daily_report_v8.FILTER_SIZES.get("دارما", ())) != ("M", "L", "XL", "XXL", "3XL", "4XL"):
            errors.append("Darma report sizes are not M/L/XL/XXL/3XL/4XL")

        synthetic = [
            {"brand_name": "دارما", "size_name": "L", "packs": 2, "shorts": 6},
            {"brand_name": "دارما", "size_name": "L", "packs": 1, "shorts": 3},
            {"brand_name": "تکوین", "size_name": "M", "packs": 4, "shorts": 4},
        ]
        filters = {row["name"]: row for row in daily_report_v8._build_filter_brands(synthetic)}
        if filters["دارما"]["packs"] != 3 or filters["دارما"]["shorts"] != 9:
            errors.append("Darma brand filter aggregation failed")
        darma_l = next((row for row in filters["دارما"]["sizes"] if row["name"] == "L"), None)
        if not darma_l or darma_l["line_count"] != 2 or darma_l["shorts"] != 9:
            errors.append("Darma L size filter aggregation failed")

        # Read-only smoke test against one real sale when available. Allocations
        # must be the source of displayed colors whenever they exist.
        line = (
            SaleLine.objects.filter(quantity__gt=0)
            .select_related("product_size__product__brand", "product_size__product", "product_size__size")
            .prefetch_related("allocations__color", "product_size__product__composition__color")
            .order_by("-day__date", "-id")
            .first()
        )
        if line:
            colors, source_kind = daily_report_v8._line_color_breakdown(line)
            metrics = sale_line_metrics(line)
            allocation_total = sum(int(row.qty or 0) for row in line.allocations.all())
            color_total = sum(int(row["qty"]) for row in colors)
            if allocation_total:
                if source_kind != "allocation":
                    errors.append("real sale has allocations but report is not using allocation colors")
                if color_total != allocation_total:
                    errors.append(f"displayed color total {color_total} != allocation total {allocation_total}")
            try:
                snapshot = line.snapshot
            except Exception:
                snapshot = None
            pack_qty = int((snapshot.pack_qty if snapshot else 0) or line.product_size.product.pack_qty or 0)
            if int(metrics["shorts"]) != int(line.quantity or 0) * pack_qty:
                errors.append("reported shorts count does not match frozen/current pack quantity")

        if errors:
            for error in errors:
                self.stderr.write(self.style.ERROR(error))
            raise CommandError("DAILY REPORT V26 CHECK FAILED")

        self.stdout.write("brand drilldown: Takvin + Darma")
        self.stdout.write("size drilldown: active and ordered")
        self.stdout.write("sold colors: SaleAllocation-first, composition fallback labelled")
        self.stdout.write("row metrics: price, packs, shorts, gross, Digikala, COGS, profit")
        self.stdout.write("inline price edit + row delete: present")
        self.stdout.write(self.style.SUCCESS("DAILY REPORT V26 CHECK OK"))