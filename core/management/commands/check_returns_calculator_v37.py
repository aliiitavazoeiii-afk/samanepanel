from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum
from django.template.loader import get_template
from django.urls import Resolver404, resolve

from core.calculator_v37 import _solve_sale_price
from core.finance import digikala_fee_for_unit
from core.finance_excel_v9 import digikala_receivable_total
from core.inventory_valuation_v17 import finished_inventory_value_v17
from core.models import AccountEntry, Brand, InventoryAdjustment, ProductSize, SaleLine, StockBalance, StockLocation
from core.returns_v37 import _apply_code_batch, _apply_color_batch


class Command(BaseCommand):
    help = "Regression check for standalone returns and current-margin calculator v37."

    def _home_qty(self, brand, size, color):
        return int(StockBalance.objects.filter(
            brand=brand, size=size, color=color, location__key=StockLocation.HOME
        ).aggregate(v=Sum("qty"))["v"] or 0)

    def _snapshot(self):
        return {
            "finished": int(finished_inventory_value_v17()),
            "digi": int(digikala_receivable_total()),
            "entries": AccountEntry.objects.count(),
            "sales": SaleLine.objects.count(),
            "adjustments": InventoryAdjustment.objects.count(),
        }

    def handle(self, *args, **options):
        if resolve("/returns/").func.__module__ != "core.returns_v37":
            raise CommandError("/returns/ is not routed to returns_v37")
        if resolve("/returns/apply/").func.__module__ != "core.returns_v37":
            raise CommandError("/returns/apply/ is not routed to returns_v37")
        if resolve("/calculator/").func.__module__ != "core.calculator_v37":
            raise CommandError("calculator route is not v37")
        if resolve("/calculator/target-quote/").func.__module__ != "core.calculator_v37":
            raise CommandError("target calculator route is not v37")
        try:
            resolve("/sales/1/return/")
            raise CommandError("old daily-report return route still exists")
        except Resolver404:
            pass

        for name in (
            "core/daily_report_v21.html",
            "core/returns_v37.html",
            "core/calculator_v37.html",
            "core/_calculator_target_result_v37.html",
            "core/report_excel_v36.html",
        ):
            try:
                get_template(name)
            except Exception as exc:
                raise CommandError(f"template load failed: {name}: {exc}") from exc

        # Exact fee-engine solver check: returned price must meet target and one toman less must not.
        cost = 100000
        target = 50.0
        price = _solve_sale_price(cost, target)
        achieved = price - int(digikala_fee_for_unit(price)) - cost
        target_profit = cost * target / 100
        if achieved < target_profit:
            raise CommandError("target calculator undershot requested profit ratio")
        if price > 0:
            previous = price - 1
            previous_profit = previous - int(digikala_fee_for_unit(previous)) - cost
            if previous_profit >= target_profit:
                raise CommandError("target calculator did not return minimum valid sale price")

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
            comps = list(candidate.product.composition.all())
            if comps and sum(int(c.qty or 0) for c in comps) == int(candidate.product.pack_qty or 0):
                ps = candidate
                break
        if not ps:
            raise CommandError("no consistent fixed-composition Darma product-size available for return test")
        components = list(ps.product.composition.all())
        first_color = components[0].color
        before = self._snapshot()

        # 1) Loose-color return round trip.
        loose_before = self._home_qty(darma, ps.size, first_color)
        with transaction.atomic():
            result = _apply_color_batch(
                when=date.today(), brand=darma, size=ps.size,
                entries=[(first_color, 2)],
            )
            if result["shorts"] != 2:
                raise CommandError(f"color-return quantity mismatch: {result}")
            if self._home_qty(darma, ps.size, first_color) != loose_before + 2:
                raise CommandError("color return did not add exact HOME quantity")
            if int(digikala_receivable_total()) != before["digi"]:
                raise CommandError("color return changed Digikala receivable")
            if AccountEntry.objects.count() != before["entries"] or SaleLine.objects.count() != before["sales"]:
                raise CommandError("color return changed finance/sales")
            if int(finished_inventory_value_v17()) <= before["finished"]:
                raise CommandError("color return did not increase inventory value")
            transaction.set_rollback(True)
        if self._snapshot() != before or self._home_qty(darma, ps.size, first_color) != loose_before:
            raise CommandError("color-return rollback left business data changed")

        # 2) Full-code pack round trip: every composition color must return exactly.
        component_before = {
            comp.color_id: self._home_qty(darma, ps.size, comp.color)
            for comp in components
        }
        with transaction.atomic():
            result = _apply_code_batch(
                when=date.today(), brand=darma, size=ps.size,
                entries=[(ps, 1)],
            )
            if result["shorts"] != int(ps.product.pack_qty or 0):
                raise CommandError(f"code-return quantity mismatch: {result}")
            for comp in components:
                actual = self._home_qty(darma, ps.size, comp.color)
                expected = component_before[comp.color_id] + int(comp.qty or 0)
                if actual != expected:
                    raise CommandError(
                        f"code return component mismatch {comp.color.name}: expected {expected}, found {actual}"
                    )
            if int(digikala_receivable_total()) != before["digi"]:
                raise CommandError("code return changed Digikala receivable")
            if AccountEntry.objects.count() != before["entries"] or SaleLine.objects.count() != before["sales"]:
                raise CommandError("code return changed finance/sales")
            if int(finished_inventory_value_v17()) <= before["finished"]:
                raise CommandError("code return did not increase inventory value")
            transaction.set_rollback(True)
        if self._snapshot() != before:
            raise CommandError("code-return rollback left business data changed")
        for comp in components:
            if self._home_qty(darma, ps.size, comp.color) != component_before[comp.color_id]:
                raise CommandError("code-return rollback left HOME stock changed")

        self.stdout.write("RETURNS + CALCULATOR V37 CHECK OK")
        self.stdout.write("Old return box/route removed from daily report")
        self.stdout.write("Color return: exact HOME-only round trip; no finance/sale/Digikala movement")
        self.stdout.write("Code return: exact ProductComposition HOME round trip; no finance/sale/Digikala movement")
        self.stdout.write("Target calculator uses exact existing Digikala fee engine")
        self.stdout.write("Rollback tests left business values unchanged")
