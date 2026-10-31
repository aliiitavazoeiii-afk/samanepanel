from django.core.management.base import BaseCommand, CommandError

from core.darma_pricing import DEFAULT_GROUP_PRICES, SIZE_NAMES, get_group_prices
from core.models import ProductCode, ProductSize
from core.variant_sale_v12 import SELLER_COLOR_CODES, resolve_variant_color


class Command(BaseCommand):
    help = "Verify Darma s3 variable-color product/import rules."

    def handle(self, *args, **options):
        errors = []
        if 1 not in DEFAULT_GROUP_PRICES:
            errors.append("pack-1 pricing row is missing")

        product = ProductCode.objects.filter(brand__name="دارما", code="s3", active=True).first()
        if not product:
            errors.append("Darma s3 product is missing")
        else:
            if int(product.pack_qty or 0) != 1:
                errors.append(f"s3 pack_qty={product.pack_qty}, expected 1")
            if product.composition.exists():
                errors.append("s3 must not have a fixed ProductComposition")
            active_sizes = set(
                ProductSize.objects.filter(product=product, active=True).values_list("size__name", flat=True)
            )
            missing_sizes = set(SIZE_NAMES) - active_sizes
            if missing_sizes:
                errors.append(f"s3 missing active sizes: {sorted(missing_sizes)}")

        expected_codes = {"s2": "کرم", "s3": "مشکی", "S3": "صورتی", "s5": "سرمه ای"}
        if SELLER_COLOR_CODES != expected_codes:
            errors.append(f"seller color codes are wrong: {SELLER_COLOR_CODES}")

        samples = [
            ("شورت زنانه دارما مدل s3 | XXL | کرم | گارانتی", "s2", "کرم"),
            ("شورت زنانه دارما مدل s3 | 3XL | مشکی | گارانتی", "s3", "مشکی"),
            ("شورت زنانه دارما مدل s3 | XL | صورتی | گارانتی", "S3", "صورتی"),
            ("شورت زنانه دارما مدل s3 | M | سرمه‌ای | گارانتی", "s5", "سرمه ای"),
            ("شورت زنانه دارما مدل s3 | L | سفید | گارانتی", "", "سفید"),
        ]
        for title, seller_code, expected in samples:
            actual = resolve_variant_color(title, seller_code)
            if actual != expected:
                errors.append(f"variant color parse {seller_code}: {actual!r} != {expected!r}")

        prices = get_group_prices(1)
        zero_sizes = [size for size, value in prices.items() if int(value or 0) <= 0]
        if zero_sizes:
            self.stdout.write(
                self.style.WARNING(
                    "S3 PRICE REQUIRED BEFORE IMPORT: " + ", ".join(zero_sizes)
                )
            )
        else:
            self.stdout.write(self.style.SUCCESS("S3 SINGLE-ITEM PRICES ARE SET"))

        if errors:
            for error in errors:
                self.stderr.write(self.style.ERROR(error))
            raise CommandError("S3 variant v12 preflight failed")

        self.stdout.write(self.style.SUCCESS("S3 VARIABLE-COLOR V12 OK"))
