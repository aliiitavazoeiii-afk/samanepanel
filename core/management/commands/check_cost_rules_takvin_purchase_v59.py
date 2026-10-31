from datetime import date
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum
from django.template.loader import get_template

from core.models import (
    Brand,
    Color,
    ExcelManualSetting,
    InventoryMovement,
    Size,
    StockBalance,
    StockLocation,
    TakvinPurchase,
)
from core.novani_cost_v59 import novani_cost_for, set_novani_cost_rule
from core.takvin_v5 import _apply_purchase_stock, _reverse_purchase_stock


class Command(BaseCommand):
    help = "Transactional regression for V59 Novani dated cost + Takvin purchase inventory."

    def _home_qty(self, brand, size, color):
        return int(
            StockBalance.objects.filter(
                brand=brand,
                size=size,
                color=color,
                location__key=StockLocation.HOME,
            ).aggregate(v=Sum("qty"))["v"]
            or 0
        )

    def handle(self, *args, **options):
        try:
            get_template("core/settings_rules_v17.html")
            get_template("core/inventory_v19.html")
        except Exception as exc:
            raise CommandError(f"V59 template compile failed: {exc}") from exc

        rules_source = (
            Path(settings.BASE_DIR) / "templates" / "core" / "settings_rules_v17.html"
        ).read_text(encoding="utf-8")
        for marker in ("novani_cost_rule", "بهای تمام‌شده هر شورت Novani", "jalali-date"):
            if marker not in rules_source:
                raise CommandError(f"V59 Novani rules UI marker missing: {marker}")

        takvin = Brand.objects.filter(name="تکوین").first()
        home = StockLocation.objects.filter(key=StockLocation.HOME).first()
        size = Size.objects.filter(name__in=["M", "L", "XL", "XXL"]).order_by("sort_order", "id").first()
        color = Color.objects.filter(active=True).order_by("id").first()
        if not takvin or not home or not size or not color:
            raise CommandError("V59 regression needs Takvin brand, HOME, one size and one color")

        debt_obj = ExcelManualSetting.objects.filter(key="takvin_debt").first()
        debt_before = int(debt_obj.value or 0) if debt_obj else 0
        stock_before = self._home_qty(takvin, size, color)
        movement_count_before = InventoryMovement.objects.count()
        purchase_count_before = TakvinPurchase.objects.count()

        with transaction.atomic():
            try:
                # Novani: one future-dated rule changes that date forward only.
                future = date(2099, 1, 2)
                before_future = date(2099, 1, 1)
                prior_cost = int(novani_cost_for(before_future))
                sentinel_cost = prior_cost + 12345
                set_novani_cost_rule(future, sentinel_cost)
                if int(novani_cost_for(future)) != sentinel_cost:
                    raise CommandError("V59 Novani future rule did not resolve to its exact sentinel cost")
                if int(novani_cost_for(before_future)) != prior_cost:
                    raise CommandError("V59 Novani future rule changed the prior-date cost")

                # Takvin: purchase stock apply is physical-only; debt is managed by takvin_v5.
                obj = TakvinPurchase.objects.create(
                    date=date.today(),
                    size=size,
                    color=color,
                    qty=2,
                    list_unit_price=100000,
                    discount_percent=0,
                    net_unit_price=100000,
                    total_cost=200000,
                    note="[v59-regression]",
                    applied=False,
                )
                applied_qty = _apply_purchase_stock(obj)
                if applied_qty != 2:
                    raise CommandError("V59 Takvin purchase apply quantity mismatch")
                if self._home_qty(takvin, size, color) != stock_before + 2:
                    raise CommandError("V59 Takvin purchase did not add exact HOME stock")
                movement = InventoryMovement.objects.filter(
                    movement_type=InventoryMovement.PURCHASE,
                    reference=f"takvin-purchase:{obj.id}",
                ).first()
                if not movement or int(movement.delta or 0) != 2:
                    raise CommandError("V59 Takvin purchase movement missing/mismatched")

                reversed_qty = _reverse_purchase_stock(obj)
                if reversed_qty != 2:
                    raise CommandError("V59 Takvin purchase reverse quantity mismatch")
                if self._home_qty(takvin, size, color) != stock_before:
                    raise CommandError("V59 Takvin purchase reverse did not restore HOME stock")
                if InventoryMovement.objects.filter(reference=f"takvin-purchase:{obj.id}").exists():
                    raise CommandError("V59 Takvin purchase reverse left movement behind")

                debt_now = int(
                    ExcelManualSetting.objects.filter(key="takvin_debt").values_list("value", flat=True).first()
                    or 0
                )
                if debt_now != debt_before:
                    raise CommandError("V59 physical Takvin purchase helper changed Takvin debt")
            finally:
                transaction.set_rollback(True)

        if self._home_qty(takvin, size, color) != stock_before:
            raise CommandError("V59 regression rollback left Takvin stock changed")
        if InventoryMovement.objects.count() != movement_count_before:
            raise CommandError("V59 regression rollback left inventory movement changed")
        if TakvinPurchase.objects.count() != purchase_count_before:
            raise CommandError("V59 regression rollback left TakvinPurchase changed")
        debt_after = int(
            ExcelManualSetting.objects.filter(key="takvin_debt").values_list("value", flat=True).first()
            or 0
        )
        if debt_after != debt_before:
            raise CommandError("V59 regression rollback left Takvin debt changed")

        self.stdout.write("NOVANI DATE-EFFECTIVE COST V59 CHECK OK")
        self.stdout.write("TAKVIN PURCHASE HOME STOCK APPLY/REVERSE V59 CHECK OK")
        self.stdout.write("NO TEST DATA CHANGED")
        self.stdout.write(self.style.SUCCESS("SUCCESS: COST RULES + TAKVIN PURCHASE V59 CHECK PASSED"))
