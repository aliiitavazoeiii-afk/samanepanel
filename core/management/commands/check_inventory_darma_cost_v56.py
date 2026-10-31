from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum
from django.template.loader import get_template

from core.brand_colors import colors_for_brand
from core.darma_cost_v55 import darma_cost_for
from core.inventory_v20 import _inventory_unit_cost, _sizes_for_brand
from core.models import Brand, InventoryModelCost, StockBalance, StockLocation


class Command(BaseCommand):
    help = "Verify Darma inventory UI value uses only the centralized current Darma cost."

    def handle(self, *args, **options):
        try:
            get_template("core/inventory_v19.html")
        except Exception as exc:
            raise CommandError(f"inventory template compile failed: {exc}") from exc

        source = (Path(settings.BASE_DIR) / "templates" / "core" / "inventory_v19.html").read_text(encoding="utf-8")
        for marker in (
            "بهای تمام‌شده دارما فقط از",
            "darma_current_cost",
            "settings_rules",
        ):
            if marker not in source:
                raise CommandError(f"V56 inventory template marker missing: {marker}")

        darma = Brand.objects.get(name="دارما")
        current_cost = int(darma_cost_for())
        if current_cost <= 0:
            raise CommandError(f"invalid current Darma cost: {current_cost}")

        sizes = _sizes_for_brand(darma)
        colors = list(colors_for_brand(darma))
        page_qty = 0
        page_value = 0

        for color in colors:
            for size in sizes:
                qs = StockBalance.objects.filter(brand=darma, size=size, color=color)
                home = int(qs.filter(location__key=StockLocation.HOME).aggregate(v=Sum("qty"))["v"] or 0)
                kh = int(qs.filter(location__key=StockLocation.KHORSHID).aggregate(v=Sum("qty"))["v"] or 0)
                qty = home + kh
                unit_cost = int(_inventory_unit_cost(
                    darma,
                    size,
                    color,
                    cost_map={(color.id, size.id): 999_999_999},
                    darma_current_cost=current_cost,
                ))
                if unit_cost != current_cost:
                    raise CommandError(
                        f"Darma inventory cell escaped central cost: {color.name}/{size.name} "
                        f"unit={unit_cost} expected={current_cost}"
                    )
                page_qty += qty
                page_value += qty * unit_cost

        expected_value = page_qty * current_cost
        if page_value != expected_value:
            raise CommandError(f"Darma page value mismatch: {page_value} != {expected_value}")

        all_qty = int(StockBalance.objects.filter(brand=darma).aggregate(v=Sum("qty"))["v"] or 0)
        if page_qty != all_qty:
            raise CommandError(
                f"Darma inventory page hides stock rows: page_qty={page_qty} all_stock_qty={all_qty}"
            )

        # Prove a legacy InventoryModelCost edit cannot change Darma inventory value.
        legacy = InventoryModelCost.objects.filter(brand=darma).order_by("id").first()
        if legacy:
            with transaction.atomic():
                old = int(legacy.unit_cost or 0)
                legacy.unit_cost = old + 7_777_777
                legacy.save(update_fields=["unit_cost", "updated_at"])
                unit = int(_inventory_unit_cost(
                    darma,
                    legacy.size,
                    legacy.color,
                    cost_map={(legacy.color_id, legacy.size_id): int(legacy.unit_cost)},
                    darma_current_cost=current_cost,
                ))
                if unit != current_cost:
                    raise CommandError("legacy InventoryModelCost can still affect Darma inventory UI")
                transaction.set_rollback(True)

        self.stdout.write(f"DARMA_QTY={page_qty}")
        self.stdout.write(f"DARMA_UNIT_COST={current_cost}")
        self.stdout.write(f"DARMA_INVENTORY_PAGE_VALUE={page_value}")
        self.stdout.write("InventoryModelCost is ignored for Darma inventory-page valuation")
        self.stdout.write(self.style.SUCCESS("SUCCESS: DARMA INVENTORY PAGE COST V56 CHECK PASSED"))
