from django.core.management.base import BaseCommand, CommandError

from core.daily_order_import_v8 import SELLER_CODE_ALIASES, SIZE_ALIASES
from core.models import ProductCode, ProductSize


class Command(BaseCommand):
    help = "Verify daily Digikala Excel import prerequisites."

    def handle(self, *args, **options):
        errors = []

        expected_aliases = {
            "pack5": ("دارما", "pack 5"),
            "rah110": ("دارما", "rah-110"),
            "rah220": ("دارما", "rah-220"),
            "220": ("دارما", "D 220"),
            "pack6": ("دارما", "06"),
        }
        for key, expected in expected_aliases.items():
            if SELLER_CODE_ALIASES.get(key) != expected:
                errors.append(f"alias {key} is not {expected}")

        expected_sizes = {
            "36-38": "M", "38-40": "L", "40-42": "XL",
            "42-44": "XXL", "44-46": "3XL", "46-48": "4XL",
        }
        for key, expected in expected_sizes.items():
            if SIZE_ALIASES.get(key) != expected:
                errors.append(f"size alias {key} is not {expected}")

        for brand, code, size in [
            ("دارما", "pack 5", "M"),
            ("دارما", "D 220", "XXL"),
            ("دارما", "rah-110", "XL"),
            ("دارما", "rah-220", "L"),
            ("تکوین", "4444", "XL"),
            ("تکوین", "2222", "L"),
        ]:
            if not ProductSize.objects.filter(
                product__brand__name=brand,
                product__code=code,
                size__name=size,
                active=True,
                product__active=True,
            ).exists():
                errors.append(f"missing active product-size: {brand} / {code} / {size}")

        if ProductCode.objects.filter(brand__name="دارما", code="rah").exists():
            errors.append("removed Darma code rah exists")
        if ProductCode.objects.filter(brand__name="دارما", code="blk").exists():
            errors.append("removed Darma code blk exists")

        if errors:
            for error in errors:
                self.stderr.write(self.style.ERROR(error))
            raise CommandError("Daily order import v8 preflight failed")

        self.stdout.write(self.style.SUCCESS("DAILY ORDER IMPORT V8 OK"))
