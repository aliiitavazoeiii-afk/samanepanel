from django.core.management.base import BaseCommand

from core.special_darma_products_v66 import sync_special_darma_products


class Command(BaseCommand):
    help = "Create/update user-confirmed special active Darma product codes for V66."

    def handle(self, *args, **options):
        rows = sync_special_darma_products()
        for row in rows:
            mode = "VARIABLE" if row["variable"] else "FIXED"
            created = "created" if row["created"] else "updated"
            self.stdout.write(
                f"{row['code']} | {created} | pack={row['pack_qty']} | {mode} | sizes={row['sizes']}"
            )
        self.stdout.write("IGNORED/UNMAPPED MODELS WERE NOT CREATED")
        self.stdout.write(self.style.SUCCESS("SPECIAL DARMA PRODUCTS V66 SYNCED"))
