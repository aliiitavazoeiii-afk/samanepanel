from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.daily_order_import_v8 import ParsedOrderRow
from core.daily_order_import_v12 import resolve_rows_v12
from core.final_services import sync_sale_inventory
from core.models import ProductCode, ProductSize, SaleDay, SaleLine, StockBalance, StockLocation
from core.special_darma_products_v66 import (
    IGNORED_DARMA_TITLE_MODELS,
    SPECIAL_DARMA_PRODUCTS,
    UNMAPPED_DARMA_TITLE_MODELS,
)
from core.title_product_resolver_v27 import resolve_product_from_title
from core.variant_sale_v12 import (
    is_variable_color_product_code,
    resolve_variable_product_color,
    sync_variant_inventory,
)


class Command(BaseCommand):
    help = "Regression for user-confirmed V66 Darma special packs and mass-06 variable color."

    def handle(self, *args, **options):
        errors = []

        expected = {
            "mass-03": (10, {"کرم": 10}),
            "D-WP": (2, {"سفید": 1, "صورتی": 1}),
            "D-WN": (2, {"سفید": 1, "سرمه ای": 1}),
            "D-WK": (2, {"سفید": 1, "کرم": 1}),
            "D-WB": (2, {"سفید": 1, "مشکی": 1}),
            "D-PN": (2, {"صورتی": 1, "سرمه ای": 1}),
            "D-KM": (2, {"مشکی": 1, "کرم": 1}),
        }

        for code, (pack_qty, composition) in expected.items():
            product = ProductCode.objects.filter(brand__name="دارما", code=code, active=True).first()
            if not product:
                errors.append(f"missing active Darma product: {code}")
                continue
            if int(product.pack_qty or 0) != pack_qty:
                errors.append(f"{code} pack={product.pack_qty}, expected {pack_qty}")
            actual = {row.color.name: int(row.qty) for row in product.composition.select_related("color")}
            if actual != composition:
                errors.append(f"{code} composition={actual}, expected {composition}")

        mass06 = ProductCode.objects.filter(brand__name="دارما", code="mass-06", active=True).first()
        if not mass06:
            errors.append("missing active Darma product: mass-06")
        else:
            if int(mass06.pack_qty or 0) != 10:
                errors.append(f"mass-06 pack={mass06.pack_qty}, expected 10")
            if mass06.composition.exists():
                errors.append("mass-06 must have no fixed ProductComposition")
            if not is_variable_color_product_code("mass-06"):
                errors.append("mass-06 is not registered as variable-color product")

        samples = [
            ("شورت زنانه دارما مدل mass-06 مجموعه 10 عددی | M | سفید | گارانتی", "سفید"),
            ("شورت زنانه دارما مدل mass-06 مجموعه 10 عددی | L | مشکی | گارانتی", "مشکی"),
            ("شورت زنانه دارما مدل mass-06 مجموعه 10 عددی | XL | کالباسی | گارانتی", "صورتی"),
            ("شورت زنانه دارما مدل mass-06 مجموعه 10 عددی | XXL | سرمه ای | گارانتی", "سرمه ای"),
            ("شورت زنانه دارما مدل mass-06 مجموعه 10 عددی | 3XL | قرمز | گارانتی", "قرمز"),
            ("شورت زنانه دارما مدل mass-06 مجموعه 10 عددی | 4XL | زرد | گارانتی", "زرد"),
        ]
        for title, expected_color in samples:
            product = resolve_product_from_title(title)
            if not product or product.code != "mass-06":
                errors.append(f"mass-06 title resolver failed: {title}")
                continue
            actual_color = resolve_variable_product_color(product.code, title)
            if actual_color != expected_color:
                errors.append(f"mass-06 color {actual_color!r} != {expected_color!r}: {title}")

        for code in sorted(IGNORED_DARMA_TITLE_MODELS | UNMAPPED_DARMA_TITLE_MODELS):
            title = f"شورت زنانه دارما مدل {code} مجموعه 3 عددی | M | چند رنگ"
            if resolve_product_from_title(title) is not None:
                errors.append(f"ignored/unmapped model unexpectedly resolves: {code}")

        # Active import must preserve the color dimension for mass-06 in pack units.
        parsed = [
            ParsedOrderRow(
                source_row=1,
                seller_code="",
                title="شورت زنانه دارما مدل mass-06 مجموعه 10 عددی | M | زرد | گارانتی",
                quantity=2,
                status="دریافت شده",
            )
        ]
        resolved, row_errors = resolve_rows_v12(parsed)
        if row_errors:
            errors.extend(row_errors)
        elif len(resolved) != 1 or resolved[0].color_name != "زرد" or resolved[0].quantity != 2:
            errors.append(f"mass-06 import row mismatch: {resolved}")

        if not errors and mass06:
            ps = ProductSize.objects.filter(product=mass06, size__name="M", active=True).select_related("size").first()
            if not ps:
                errors.append("mass-06 / M ProductSize missing")
            else:
                before = int(
                    StockBalance.objects.filter(
                        brand=mass06.brand,
                        size=ps.size,
                        color__name="زرد",
                        location__key=StockLocation.HOME,
                    ).values_list("qty", flat=True).first()
                    or 0
                )
                with transaction.atomic():
                    day, _ = SaleDay.objects.get_or_create(date=date(2099, 12, 29))
                    line, _ = SaleLine.objects.get_or_create(
                        day=day,
                        product_size=ps,
                        defaults={"quantity": 0, "sale_price": 1},
                    )
                    line.quantity = 1
                    if int(line.sale_price or 0) <= 0:
                        line.sale_price = 1
                    line.save(update_fields=["quantity", "sale_price"])
                    sync_variant_inventory(line, {"زرد": 1})
                    after = int(
                        StockBalance.objects.filter(
                            brand=mass06.brand,
                            size=ps.size,
                            color__name="زرد",
                            location__key=StockLocation.HOME,
                        ).values_list("qty", flat=True).first()
                        or 0
                    )
                    if before - after != 10:
                        errors.append(f"mass-06 inventory delta={before-after}, expected 10")
                    transaction.set_rollback(True)

        dwp = ProductCode.objects.filter(brand__name="دارما", code="D-WP", active=True).first()
        if not errors and dwp:
            ps = ProductSize.objects.filter(product=dwp, size__name="M", active=True).select_related("size").first()
            if not ps:
                errors.append("D-WP / M ProductSize missing")
            else:
                before = {
                    color: int(
                        StockBalance.objects.filter(
                            brand=dwp.brand,
                            size=ps.size,
                            color__name=color,
                            location__key=StockLocation.HOME,
                        ).values_list("qty", flat=True).first()
                        or 0
                    )
                    for color in ("سفید", "صورتی")
                }
                with transaction.atomic():
                    day, _ = SaleDay.objects.get_or_create(date=date(2099, 12, 30))
                    line, _ = SaleLine.objects.get_or_create(
                        day=day,
                        product_size=ps,
                        defaults={"quantity": 0, "sale_price": 1},
                    )
                    line.quantity = 1
                    if int(line.sale_price or 0) <= 0:
                        line.sale_price = 1
                    line.save(update_fields=["quantity", "sale_price"])
                    sync_sale_inventory(line)
                    after = {
                        color: int(
                            StockBalance.objects.filter(
                                brand=dwp.brand,
                                size=ps.size,
                                color__name=color,
                                location__key=StockLocation.HOME,
                            ).values_list("qty", flat=True).first()
                            or 0
                        )
                        for color in ("سفید", "صورتی")
                    }
                    if before["سفید"] - after["سفید"] != 1:
                        errors.append("D-WP white inventory delta is not 1")
                    if before["صورتی"] - after["صورتی"] != 1:
                        errors.append("D-WP pink inventory delta is not 1")
                    transaction.set_rollback(True)

        if errors:
            for error in errors:
                self.stderr.write(self.style.ERROR(error))
            raise CommandError("SPECIAL DARMA PRODUCTS V66 CHECK FAILED")

        self.stdout.write("mass-03 = 10 x cream")
        self.stdout.write("mass-06 = variable single-color pack10 from title; kalbasi -> pink")
        self.stdout.write("D-WP/WN/WK/WB/PN/KM = fixed two-color packs")
        self.stdout.write("KID-220 / BLK-01 / 1111 / s1 / mass-12 remain ignored")
        self.stdout.write("BNR remains unmapped/fail-closed")
        self.stdout.write("ROLLBACK INVENTORY TESTS = mass-06 -10 units; D-WP -1/-1")
        self.stdout.write("NO DIGIKALA WRITE PATH ADDED")
        self.stdout.write(self.style.SUCCESS("SPECIAL DARMA PRODUCTS V66 CHECK OK"))
