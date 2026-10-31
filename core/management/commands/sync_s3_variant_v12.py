from django.core.management.base import BaseCommand

from core.variant_sale_v12 import ensure_variant_product


class Command(BaseCommand):
    help = "Create/update Darma single-item s3 as a customer-selectable color product."

    def handle(self, *args, **options):
        product = ensure_variant_product()
        prices = {
            ps.size.name: int(ps.default_sale_price or 0)
            for ps in product.sizes.select_related("size").filter(active=True)
        }
        self.stdout.write(f"S3 PRODUCT ID = {product.id}")
        self.stdout.write(f"S3 PACK QTY   = {product.pack_qty}")
        self.stdout.write("S3 PRICES     = " + ", ".join(f"{k}:{v}" for k, v in prices.items()))
        self.stdout.write(self.style.SUCCESS("S3 VARIABLE-COLOR PRODUCT V12 OK"))
