from django.core.management.base import BaseCommand, CommandError

from core.brand_colors import norm
from core.digikala_zero_guard_v65 import _product_uses_color
from core.models import Color, ProductCode


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
    return None


class Command(BaseCommand):
    help = "Verify Darma p12 V67 composition and zero-guard color dependency."

    def handle(self, *args, **options):
        errors = []
        product = ProductCode.objects.filter(brand__name="دارما", code="p12", active=True).first()
        if not product:
            errors.append("active Darma p12 is missing")
        else:
            if int(product.pack_qty or 0) != 12:
                errors.append(f"p12 pack_qty={product.pack_qty}, expected 12")
            actual = {
                row.color.name: int(row.qty)
                for row in product.composition.select_related("color")
            }
            if actual != EXPECTED:
                errors.append(f"p12 composition={actual}, expected={EXPECTED}")

            for name in ("کرم", "طوسی"):
                color = _color(name)
                if not color or not _product_uses_color(product, "", color):
                    errors.append(f"p12 must depend on {name}")

            for name in ("قرمز", "زرد"):
                color = _color(name)
                if color and _product_uses_color(product, "", color):
                    errors.append(f"p12 must NOT depend on {name}")

        if errors:
            for error in errors:
                self.stderr.write(self.style.ERROR(error))
            raise CommandError("P12 COMPOSITION V67 CHECK FAILED")

        self.stdout.write("p12 = black2 white2 navy2 pink2 cream2 gray2")
        self.stdout.write("p12 red/yellow dependency = OFF")
        self.stdout.write("p12 cream/gray dependency = ON")
        self.stdout.write("NO DIGIKALA WRITE PATH ADDED")
        self.stdout.write(self.style.SUCCESS("P12 COMPOSITION V67 CHECK OK"))
