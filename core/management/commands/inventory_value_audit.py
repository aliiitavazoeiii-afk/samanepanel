from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db.models import Sum

from core.models import InventoryModelCost, StockBalance


class Command(BaseCommand):
    help = "Audit finished inventory valuation and list stock rows with missing/zero unit cost."

    def handle(self, *args, **options):
        cost_map = {
            (r.brand_id, r.color_id, r.size_id): int(r.unit_cost or 0)
            for r in InventoryModelCost.objects.select_related("brand", "color", "size").all()
        }

        grouped = defaultdict(lambda: {"qty": 0, "value": 0})
        missing = []
        total_qty = 0
        total_value = 0

        rows = (
            StockBalance.objects.values(
                "brand_id", "brand__name", "color_id", "color__name", "size_id", "size__name"
            )
            .annotate(qty=Sum("qty"))
            .order_by("brand__name", "size__sort_order", "color__name")
        )

        for row in rows:
            qty = int(row["qty"] or 0)
            if qty == 0:
                continue
            key = (row["brand_id"], row["color_id"], row["size_id"])
            unit_cost = int(cost_map.get(key, 0) or 0)
            value = qty * unit_cost
            bucket = grouped[(row["brand__name"], row["size__name"])]
            bucket["qty"] += qty
            bucket["value"] += value
            total_qty += qty
            total_value += value
            if unit_cost <= 0 and qty != 0:
                missing.append(
                    (
                        row["brand__name"], row["size__name"], row["color__name"], qty
                    )
                )

        self.stdout.write("=== FINISHED INVENTORY VALUE AUDIT ===")
        for (brand, size), values in grouped.items():
            self.stdout.write(
                f"{brand:10} | {size:5} | QTY={values['qty']:8} | VALUE={values['value']:14}"
            )
        self.stdout.write("--------------------------------------")
        self.stdout.write(f"TOTAL QTY   = {total_qty}")
        self.stdout.write(f"TOTAL VALUE = {total_value}")
        self.stdout.write(f"MISSING COST ROWS = {len(missing)}")
        if missing:
            self.stdout.write("=== STOCK WITH MISSING/ZERO COST ===")
            for brand, size, color, qty in missing:
                self.stdout.write(f"{brand} | {size} | {color} | QTY={qty}")
        else:
            self.stdout.write(self.style.SUCCESS("NO STOCK ROW HAS MISSING/ZERO COST"))
