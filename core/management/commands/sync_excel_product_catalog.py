from django.core.management.base import BaseCommand
from django.db import transaction

from core.darma_pricing import apply_all_group_prices
from core.models import ProductCode
from core.product_catalog import sync_catalog


REMOVED_DARMA_CODES = ["rah", "blk"]


class BaseCatalogRemovalError(RuntimeError):
    pass


class Command(BaseCommand):
    help = "Create/update Darma and Takvin product codes and fixed color compositions from the legacy Excel catalog."

    @transaction.atomic
    def handle(self, *args, **options):
        summary = sync_catalog()

        # User-confirmed cleanup: these legacy Darma codes must not exist anymore.
        for code in REMOVED_DARMA_CODES:
            qs = ProductCode.objects.filter(brand__name="دارما", code=code)
            if qs.exists():
                try:
                    qs.delete()
                except Exception as exc:
                    raise BaseCatalogRemovalError(
                        f"Could not completely delete Darma code {code}: {exc}"
                    ) from exc

        remaining = list(
            ProductCode.objects.filter(brand__name="دارما", code__in=REMOVED_DARMA_CODES)
            .values_list("code", flat=True)
        )
        if remaining:
            raise BaseCatalogRemovalError(f"Removed Darma codes still exist: {remaining}")

        # Group pricing is the final source of truth for Darma 3/4/5/6 packs.
        pricing_summary = apply_all_group_prices()

        for brand_name, data in summary.items():
            self.stdout.write(
                f"{brand_name}: total={data['total']} created={data['created']} updated={data['updated']}"
            )
        for pack_qty, data in pricing_summary.items():
            self.stdout.write(
                f"Darma pack {pack_qty}: products={data['products']} price_rows={data['rows']}"
            )

        self.stdout.write(self.style.SUCCESS("Excel product catalog synced"))
        self.stdout.write(self.style.SUCCESS("Removed Darma codes deleted: rah, blk"))
        self.stdout.write(self.style.SUCCESS("Darma group prices applied"))
