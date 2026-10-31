from django.core.management.base import BaseCommand, CommandError
from django.db.models import Sum

from core.brand_colors import norm
from core.models import Brand, Color, Size, StockBalance, StockLocation

EXPECTED = {
    StockLocation.HOME: 4585,
    StockLocation.KHORSHID: 8890,
}
KEYS = [
    (StockLocation.KHORSHID, "کرم", "XXL", 400),
    (StockLocation.KHORSHID, "قرمز", "XXL", 0),
    (StockLocation.HOME, "کرم", "3XL", 77),
    (StockLocation.HOME, "طوسی", "4XL", 0),
]

class Command(BaseCommand):
    help = "Read-only verification for Darma day-3 physical stock target."

    def handle(self, *args, **options):
        brand = Brand.objects.get(name="دارما")
        locations = {x.key:x for x in StockLocation.objects.filter(key__in=EXPECTED.keys())}
        sizes = {x.name:x for x in Size.objects.all()}
        colors = list(Color.objects.filter(stockbalance__brand=brand).distinct())

        def get_color(name):
            matches = [c for c in colors if norm(c.name) == norm(name)]
            if len(matches) != 1:
                raise CommandError(f"color {name} ambiguous/missing: {[c.name for c in matches]}")
            return matches[0]

        totals = {}
        for key, expected in EXPECTED.items():
            actual = int(StockBalance.objects.filter(brand=brand,location=locations[key]).aggregate(v=Sum("qty"))["v"] or 0)
            totals[key] = actual
            self.stdout.write(f"{key} total = {actual} expected={expected}")
            if actual != expected:
                raise CommandError(f"{key} total mismatch")

        for loc,cname,sname,expected in KEYS:
            actual = int(StockBalance.objects.filter(brand=brand,location=locations[loc],color=get_color(cname),size=sizes[sname]).aggregate(v=Sum("qty"))["v"] or 0)
            self.stdout.write(f"{loc}/{cname}/{sname} = {actual} expected={expected}")
            if actual != expected:
                raise CommandError(f"key cell mismatch: {loc}/{cname}/{sname}")

        total = totals[StockLocation.HOME] + totals[StockLocation.KHORSHID]
        if total != 13475:
            raise CommandError(f"combined total mismatch: {total}")
        self.stdout.write(self.style.SUCCESS("DARMA DAY3 PHYSICAL V32 CHECK OK"))
