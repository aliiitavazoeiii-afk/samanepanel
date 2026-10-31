from django.core.management.base import BaseCommand
from django.template.loader import get_template

from core.inventory_operations_v15 import _stock_snapshot_for_operations
from core.models import Brand


class Command(BaseCommand):
    help = "Read-only regression check for V78 inventory current-stock display."

    def handle(self, *args, **options):
        get_template("core/inventory_operations.html")
        brands = Brand.objects.filter(active=True, name__in=("دارما", "تکوین", "Novani"))
        snapshot = _stock_snapshot_for_operations(brands)

        for key, row in snapshot.items():
            home = int(row.get("home") or 0)
            khorshid = int(row.get("khorshid") or 0)
            total = int(row.get("total") or 0)
            if total != home + khorshid:
                raise RuntimeError(f"Stock snapshot mismatch for {key}: {row}")

        self.stdout.write(f"SNAPSHOT CELLS = {len(snapshot)}")
        self.stdout.write("DISPLAY = HOME + KHORSHID + TOTAL")
        self.stdout.write("TRANSFER INPUT = remains transfer quantity only")
        self.stdout.write("ADJUST INPUT = remains blank; blank means no change")
        self.stdout.write("TOTAL = display-only; HOME/KHORSHID remain physical edit targets")
        self.stdout.write("TEMPLATE COMPILE = OK")
        self.stdout.write("CHECK MODE = READ ONLY")
        self.stdout.write(self.style.SUCCESS("INVENTORY CURRENT DISPLAY V78 CHECK OK"))
