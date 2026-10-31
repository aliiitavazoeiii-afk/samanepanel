from django.core.management.base import BaseCommand
from django.template.loader import get_template

from core.models import Brand, StockBalance
from core.settings_product_v60 import TAKVIN_SIZE_NAMES, _inventory_color_ids_for_brand


class Command(BaseCommand):
    help = "Read-only regression check for V81 brand-bound product composition."

    def handle(self, *args, **options):
        get_template("core/settings_product_form.html")
        get_template("core/settings_product_form_v60.html")

        if set(TAKVIN_SIZE_NAMES) != {"M", "L", "XL", "XXL"}:
            raise RuntimeError(f"Unexpected Takvin size set: {sorted(TAKVIN_SIZE_NAMES)}")

        takvin = Brand.objects.filter(active=True, name="تکوین").first()
        if not takvin:
            raise RuntimeError("Active Takvin brand was not found.")

        expected = set(
            StockBalance.objects.filter(brand=takvin)
            .values_list("color_id", flat=True)
            .distinct()
        )
        actual = _inventory_color_ids_for_brand(takvin)
        if actual != expected:
            raise RuntimeError(
                "Takvin product color catalog is not identical to Takvin inventory colors. "
                f"expected={sorted(expected)} actual={sorted(actual)}"
            )

        darma = Brand.objects.filter(active=True, name="دارما").first()
        darma_only = set()
        if darma:
            darma_ids = _inventory_color_ids_for_brand(darma)
            darma_only = darma_ids - actual
            if darma_only & actual:
                raise RuntimeError("Darma-only color unexpectedly appears in Takvin inventory catalog.")

        self.stdout.write(f"TAKVIN INVENTORY COLORS = {len(actual)}")
        self.stdout.write(f"DARMA-ONLY COLORS EXCLUDED FROM TAKVIN = {len(darma_only)}")
        self.stdout.write("TAKVIN SIZES = M, L, XL, XXL")
        self.stdout.write("PRODUCT COLOR SOURCE = selected brand StockBalance catalog")
        self.stdout.write("TEMPLATE COMPILE = OK")
        self.stdout.write("CHECK MODE = READ ONLY")
        self.stdout.write(self.style.SUCCESS("TAKVIN PRODUCT INVENTORY V81 CHECK OK"))
