from django.core.management.base import BaseCommand

from core.models import ProductCode, SaleDay, SaleLine, StockBalance


class Command(BaseCommand):
    help = "Read-only diagnostic for D 220 vs rah-220 allocations on the latest sale day."

    def handle(self, *args, **options):
        day = SaleDay.objects.order_by("-date", "-id").first()
        if not day:
            self.stdout.write("NO SALE DAY")
            return

        self.stdout.write(f"DAY={day.date} id={day.id}")
        self.stdout.write("=== CATALOG COMPOSITIONS ===")
        for code in ("D 220", "rah-220"):
            product = ProductCode.objects.filter(brand__name="دارما", code=code).first()
            if not product:
                self.stdout.write(f"{code}: MISSING")
                continue
            comps = [
                f"{row.color.name}x{int(row.qty)}"
                for row in product.composition.select_related("color").order_by("color__name")
            ]
            self.stdout.write(f"{code}: pack={product.pack_qty} composition=" + ", ".join(comps))

        self.stdout.write("=== LATEST-DAY 4XL SALE LINES ===")
        lines = (
            SaleLine.objects.filter(
                day=day,
                product_size__product__brand__name="دارما",
                product_size__product__code__in=("D 220", "rah-220"),
                product_size__size__name="4XL",
            )
            .select_related("product_size__product", "product_size__size")
            .prefetch_related("allocations__color", "allocations__location")
            .order_by("product_size__product__code", "id")
        )
        if not lines:
            self.stdout.write("NO D220/RAH220 4XL SALE LINES")
        for line in lines:
            self.stdout.write(
                f"line={line.id} code={line.product_size.product.code} qty={int(line.quantity or 0)} "
                f"applied={int(line.inventory_applied_quantity or 0)}"
            )
            allocations = list(line.allocations.all())
            if not allocations:
                self.stdout.write("  allocations: NONE")
            for alloc in allocations:
                self.stdout.write(
                    f"  alloc color={alloc.color.name} location={alloc.location.key} "
                    f"qty={int(alloc.qty or 0)} replacement={bool(alloc.is_replacement)}"
                )

        self.stdout.write("=== RAH-RAH TOSI 4XL STOCK ===")
        rows = (
            StockBalance.objects.filter(
                brand__name="دارما",
                size__name="4XL",
                color__name__in=("راه راه طوسی", "راه‌راه طوسی"),
            )
            .select_related("location", "color")
            .order_by("location__key")
        )
        total = 0
        if not rows:
            self.stdout.write("NO MATCHING STOCK ROW")
        for row in rows:
            total += int(row.qty or 0)
            self.stdout.write(f"{row.location.key}: {row.color.name}={int(row.qty or 0)}")
        self.stdout.write(f"TOTAL={total}")
        self.stdout.write("DIAGNOSTIC ONLY: NO DATA CHANGED")
