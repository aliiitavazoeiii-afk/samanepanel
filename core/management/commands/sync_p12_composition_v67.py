from django.core.management.base import BaseCommand
from django.db import transaction

from core.brand_colors import norm
from core.models import Brand, Color, ProductCode, ProductComposition


EXPECTED = {
    "مشکی": 2,
    "سفید": 2,
    "سرمه ای": 2,
    "صورتی": 2,
    "کرم": 2,
    "طوسی": 2,
}


def _color(name):
    wanted = norm(name)
    for color in Color.objects.filter(active=True).order_by("id"):
        if norm(color.name) == wanted:
            return color
    raise RuntimeError(f"active color not found: {name}")


class Command(BaseCommand):
    help = "Update only Darma p12 composition to the user-confirmed V67 colors; preserve prices and historical sales."

    @transaction.atomic
    def handle(self, *args, **options):
        brand = Brand.objects.get(name="دارما")
        product = ProductCode.objects.select_for_update().get(brand=brand, code="p12", active=True)

        if int(product.pack_qty or 0) != 12:
            raise RuntimeError(f"p12 pack_qty={product.pack_qty}, expected 12")

        before = {
            row.color.name: int(row.qty)
            for row in product.composition.select_related("color").order_by("color_id")
        }

        ProductComposition.objects.filter(product=product).delete()
        for color_name, qty in EXPECTED.items():
            ProductComposition.objects.create(
                product=product,
                color=_color(color_name),
                qty=int(qty),
            )

        after = {
            row.color.name: int(row.qty)
            for row in product.composition.select_related("color").order_by("color_id")
        }

        if after != EXPECTED:
            raise RuntimeError(f"p12 composition mismatch after sync: {after}")

        self.stdout.write(f"BEFORE = {before}")
        self.stdout.write(f"AFTER  = {after}")
        self.stdout.write("PRICES CHANGED = 0")
        self.stdout.write("HISTORICAL SALE ROWS CHANGED = 0")
        self.stdout.write(self.style.SUCCESS("P12 COMPOSITION V67 SYNCED"))
