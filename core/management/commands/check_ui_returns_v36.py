from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum
from django.template.loader import get_template
from django.urls import resolve

from core.daily_returns_v36 import _apply_return_batch
from core.finance_excel_v9 import digikala_receivable_total
from core.inventory_valuation_v17 import finished_inventory_value_v17
from core.models import AccountEntry, Brand, InventoryAdjustment, ProductCode, ProductSize, SaleDay, SaleLine, StockBalance, StockLocation


class Command(BaseCommand):
    help = "Rollback regression check for v36 UI safety and isolated daily returns."

    def _qty(self, brand, size, color):
        return int(StockBalance.objects.filter(
            brand=brand, size=size, color=color, location__key=StockLocation.HOME
        ).aggregate(v=Sum("qty"))["v"] or 0)

    def _business_snapshot(self):
        return {
            "finished": int(finished_inventory_value_v17()),
            "digi": int(digikala_receivable_total()),
            "entries": AccountEntry.objects.count(),
            "sales": SaleLine.objects.count(),
            "adjustments": InventoryAdjustment.objects.count(),
        }

    def handle(self, *args, **options):
        if resolve("/report/").func.__module__ != "core.report_v9":
            raise CommandError("report route changed away from report_v9")
        if resolve("/").func.__module__ != "core.excel_dashboard":
            raise CommandError("dashboard route changed away from excel_dashboard")
        if resolve("/sales/1/report/").func.__module__ != "core.daily_report_v8":
            raise CommandError("daily report route changed away from daily_report_v8")
        if resolve("/sales/1/return/").func.__module__ != "core.daily_returns_v36":
            raise CommandError("daily return route is not v36")

        for template_name in (
            "core/dashboard_excel.html",
            "core/daily_report_v36.html",
            "core/_daily_returns_v36.html",
            "core/report_excel_v36.html",
        ):
            try:
                get_template(template_name)
            except Exception as exc:
                raise CommandError(f"template load failed for {template_name}: {exc}") from exc

        # Every active fixed-composition Darma/Takvin code exposed as a full pack must
        # be internally consistent. Variable-color/no-composition codes stay loose-only.
        fixed_products = (
            ProductCode.objects.filter(brand__name__in=["دارما", "تکوین"], active=True)
            .select_related("brand")
            .prefetch_related("composition")
        )
        audited_fixed = 0
        for product in fixed_products:
            components = list(product.composition.all())
            if not components:
                continue
            audited_fixed += 1
            comp_total = sum(int(c.qty or 0) for c in components)
            if comp_total != int(product.pack_qty or 0):
                raise CommandError(
                    f"return pack catalog mismatch: {product.brand.name}/{product.code} "
                    f"composition={comp_total}, pack_qty={product.pack_qty}"
                )

        darma = Brand.objects.get(name="دارما")
        candidates = list(
            ProductSize.objects.filter(
                product__brand=darma,
                product__active=True,
                active=True,
                product__composition__isnull=False,
            )
            .select_related("product", "size")
            .prefetch_related("product__composition__color")
            .distinct()
        )
        ps = None
        for candidate in candidates:
            comp_total = sum(int(c.qty or 0) for c in candidate.product.composition.all())
            if comp_total > 0 and comp_total == int(candidate.product.pack_qty or 0):
                ps = candidate
                break
        if not ps:
            raise CommandError("no internally consistent fixed-composition Darma product-size found for return test")

        components = list(ps.product.composition.all())
        color = components[0].color
        before = self._business_snapshot()
        before_loose_qty = self._qty(darma, ps.size, color)

        with transaction.atomic():
            day, _ = SaleDay.objects.get_or_create(date=date(2099, 1, 1))
            loose_qty = 2
            result = _apply_return_batch(
                day=day, brand=darma, size=ps.size,
                loose_by_color=[(color, loose_qty)], pack_by_product_size=[],
            )
            if result["shorts"] != loose_qty:
                raise CommandError(f"loose return quantity mismatch: {result}")
            after_qty = self._qty(darma, ps.size, color)
            if after_qty != before_loose_qty + loose_qty:
                raise CommandError(f"HOME stock did not increase exactly: {before_loose_qty} -> {after_qty}")
            if int(digikala_receivable_total()) != before["digi"]:
                raise CommandError("loose return changed Digikala receivable")
            if AccountEntry.objects.count() != before["entries"]:
                raise CommandError("loose return created finance account entries")
            if SaleLine.objects.count() != before["sales"]:
                raise CommandError("loose return created/changed sales")
            if int(finished_inventory_value_v17()) <= before["finished"]:
                raise CommandError("loose return did not increase finished inventory value")
            transaction.set_rollback(True)

        if self._business_snapshot() != before or self._qty(darma, ps.size, color) != before_loose_qty:
            raise CommandError("loose-return rollback test left business data changed")

        component_before = {comp.color_id: self._qty(darma, ps.size, comp.color) for comp in components}
        with transaction.atomic():
            day, _ = SaleDay.objects.get_or_create(date=date(2099, 1, 2))
            result = _apply_return_batch(
                day=day, brand=darma, size=ps.size,
                loose_by_color=[], pack_by_product_size=[(ps, 1)],
            )
            if result["shorts"] != int(ps.product.pack_qty or 0):
                raise CommandError(f"full-pack return quantity mismatch: {result}")
            for comp in components:
                actual = self._qty(darma, ps.size, comp.color)
                expected = component_before[comp.color_id] + int(comp.qty or 0)
                if actual != expected:
                    raise CommandError(
                        f"full-pack component mismatch {comp.color.name}: expected {expected}, found {actual}"
                    )
            if int(digikala_receivable_total()) != before["digi"]:
                raise CommandError("full-pack return changed Digikala receivable")
            if AccountEntry.objects.count() != before["entries"]:
                raise CommandError("full-pack return created finance account entries")
            if SaleLine.objects.count() != before["sales"]:
                raise CommandError("full-pack return created/changed sales")
            if int(finished_inventory_value_v17()) <= before["finished"]:
                raise CommandError("full-pack return did not increase finished inventory value")
            transaction.set_rollback(True)

        if self._business_snapshot() != before:
            raise CommandError("full-pack rollback test left business data changed")
        for comp in components:
            if self._qty(darma, ps.size, comp.color) != component_before[comp.color_id]:
                raise CommandError("full-pack rollback test left HOME stock changed")

        self.stdout.write("UI + DAILY RETURNS V36 CHECK OK")
        self.stdout.write("Dashboard/report formulas and active routes preserved")
        self.stdout.write("Daily/report/dashboard templates load successfully")
        self.stdout.write(f"Fixed-pack catalog audited: {audited_fixed} Darma/Takvin product codes")
        self.stdout.write("Loose return: HOME stock only; no SaleLine/AccountEntry/Digikala movement")
        self.stdout.write("Full-pack return: ProductComposition restored to HOME exactly; no finance/sale movement")
        self.stdout.write("Both rollback tests left all business values unchanged")
