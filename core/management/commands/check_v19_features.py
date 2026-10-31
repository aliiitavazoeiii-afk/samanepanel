from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.urls import resolve, reverse

from core.anbaresh_catalog_v19 import ANBARESH_UNIT_COST, sync_anbaresh_catalog
from core.models import (
    Brand,
    InventoryModelCost,
    MaterialReportBlock,
    ProductCode,
    ProductSize,
    StockBalance,
    StockLocation,
)


class Command(BaseCommand):
    help = "Verify sale-only Anbaresh, Novani inventory and brand-aware material reports."

    def handle(self, *args, **options):
        errors = []
        sync_anbaresh_catalog()

        darma = Brand.objects.filter(name="دارما", active=True).first()
        anbaresh = Brand.objects.filter(name="انبارش", active=True).first()
        novani = Brand.objects.filter(name="Novani", active=True).first()
        if not darma:
            errors.append("Darma brand is missing/inactive")
        if not anbaresh:
            errors.append("Anbaresh brand is missing/inactive")
        if not novani:
            errors.append("Novani brand is missing/inactive")

        route_expectations = {
            "sale_brand": "core.sale_brand_v19",
            "inventory": "core.inventory_v19",
            "inventory_add_color_model": "core.inventory_v19",
            "material_report": "core.material_report_v19",
            "material_block_save": "core.material_report_v19",
            "material_block_apply": "core.material_report_v19",
            "material_block_apply_output": "core.material_report_v19",
        }
        for route, expected in route_expectations.items():
            args = [1] if route.startswith("material_block_") or route == "sale_brand" else []
            actual = resolve(reverse(route, args=args)).func.__module__
            if actual != expected:
                errors.append(f"{route}: expected {expected}, got {actual}")
            else:
                self.stdout.write(f"route OK: {route} -> {actual}")

        if anbaresh:
            stock_rows = StockBalance.objects.filter(brand=anbaresh)
            stock_qty = sum(int(x or 0) for x in stock_rows.values_list("qty", flat=True))
            if stock_rows.exists() or stock_qty:
                errors.append(f"Anbaresh must have no stock rows; rows={stock_rows.count()} qty={stock_qty}")
            if InventoryModelCost.objects.filter(brand=anbaresh).exists():
                errors.append("Anbaresh must have no InventoryModelCost rows")

        if darma and anbaresh:
            darma_products = {
                row.code: row
                for row in ProductCode.objects.filter(brand=darma, active=True).prefetch_related("sizes")
            }
            anbaresh_products = {
                row.code: row
                for row in ProductCode.objects.filter(brand=anbaresh, active=True).prefetch_related("sizes")
            }
            missing_codes = sorted(set(darma_products) - set(anbaresh_products))
            extra_codes = sorted(set(anbaresh_products) - set(darma_products))
            if missing_codes:
                errors.append("Anbaresh missing Darma codes: " + ", ".join(missing_codes))
            if extra_codes:
                errors.append("Anbaresh has unexpected active codes: " + ", ".join(extra_codes))
            for code, source in darma_products.items():
                target = anbaresh_products.get(code)
                if not target:
                    continue
                if int(target.pack_qty or 0) != int(source.pack_qty or 0):
                    errors.append(f"Anbaresh {code}: pack_qty mismatch")
                source_sizes = {ps.size_id: ps for ps in source.sizes.all() if ps.active}
                target_sizes = {ps.size_id: ps for ps in target.sizes.all() if ps.active}
                if set(source_sizes) != set(target_sizes):
                    errors.append(f"Anbaresh {code}: active size set mismatch")
                    continue
                for size_id, source_ps in source_sizes.items():
                    target_ps = target_sizes[size_id]
                    if int(target_ps.default_sale_price or 0) != int(source_ps.default_sale_price or 0):
                        errors.append(f"Anbaresh {code}/{target_ps.size.name}: default sale price mismatch")
                    if int(target_ps.unit_cost or 0) != ANBARESH_UNIT_COST:
                        errors.append(f"Anbaresh {code}/{target_ps.size.name}: unit cost must be {ANBARESH_UNIT_COST}")
            self.stdout.write(f"ANBARESH CATALOG CODES = {len(anbaresh_products)}")

        if novani:
            home = StockLocation.objects.filter(key=StockLocation.HOME).first()
            kh = StockLocation.objects.filter(key=StockLocation.KHORSHID).first()
            if not home:
                errors.append("HOME stock location missing")
            if kh and StockBalance.objects.filter(brand=novani, location=kh).exists():
                errors.append("Novani must not have KHORSHID stock rows")
            novani_rows = StockBalance.objects.filter(brand=novani)
            if not novani_rows.exists():
                errors.append("Novani has no inventory rows")
            bad_costs = InventoryModelCost.objects.filter(brand=novani).filter(Q(unit_cost=0) | ~Q(unit_cost=61000))
            if bad_costs.exists():
                errors.append(f"Novani has {bad_costs.count()} cost rows not equal to 61000")
            self.stdout.write(
                f"NOVANI STOCK ROWS = {novani_rows.count()} / QTY = {sum(int(x or 0) for x in novani_rows.values_list('qty', flat=True))}"
            )

        missing_brand_reports = MaterialReportBlock.objects.filter(brand__isnull=True).count()
        if missing_brand_reports:
            errors.append(f"MaterialReportBlock rows without brand: {missing_brand_reports}")
        invalid_brand_reports = MaterialReportBlock.objects.exclude(brand__name__in=["دارما", "Novani"]).count()
        if invalid_brand_reports:
            errors.append(f"MaterialReportBlock rows with unsupported brand: {invalid_brand_reports}")

        if errors:
            for error in errors:
                self.stderr.write(self.style.ERROR(error))
            raise CommandError("V19 feature preflight failed")

        self.stdout.write(self.style.SUCCESS("V19 ANBARESH + NOVANI + MATERIAL BRAND FLOW OK"))
