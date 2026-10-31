from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Brand, Color, InventoryMovement, Size, StockBalance, StockLocation


class Command(BaseCommand):
    help = "Repair Darma Tosi/XXL Khorshid -50 by moving 50 units from Home to Khorshid without changing total stock."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        apply = bool(options.get("apply"))
        brand = Brand.objects.get(name="دارما")
        size = Size.objects.get(name="XXL")
        color = Color.objects.get(name="طوسی")
        home = StockLocation.objects.get(key=StockLocation.HOME)
        kh = StockLocation.objects.get(key=StockLocation.KHORSHID)

        home_row, _ = StockBalance.objects.get_or_create(
            brand=brand, size=size, color=color, location=home, defaults={"qty": 0}
        )
        kh_row, _ = StockBalance.objects.get_or_create(
            brand=brand, size=size, color=color, location=kh, defaults={"qty": 0}
        )

        home_qty = int(home_row.qty or 0)
        kh_qty = int(kh_row.qty or 0)
        total_before = home_qty + kh_qty

        self.stdout.write("=== KHORSHID NEGATIVE REPAIR V15 ===")
        self.stdout.write(f"MODE        = {'APPLY' if apply else 'DRY RUN'}")
        self.stdout.write(f"TARGET      = دارما / طوسی / XXL")
        self.stdout.write(f"HOME BEFORE = {home_qty}")
        self.stdout.write(f"KH BEFORE   = {kh_qty}")
        self.stdout.write(f"TOTAL       = {total_before}")

        if kh_qty >= 0:
            self.stdout.write(self.style.SUCCESS("KHORSHID IS NOT NEGATIVE; NOTHING TO DO"))
            return

        move_qty = -kh_qty
        if home_qty < move_qty:
            raise CommandError(
                f"Cannot repair safely: Home has {home_qty}, but {move_qty} units are required."
            )

        self.stdout.write(f"MOVE HOME -> KHORSHID = {move_qty}")
        self.stdout.write(f"HOME AFTER  = {home_qty - move_qty}")
        self.stdout.write("KH AFTER    = 0")
        self.stdout.write(f"TOTAL AFTER = {total_before}")

        if not apply:
            self.stdout.write(self.style.WARNING("DRY RUN ONLY; NO STOCK CHANGED"))
            return

        with transaction.atomic():
            home_row = StockBalance.objects.select_for_update().get(pk=home_row.pk)
            kh_row = StockBalance.objects.select_for_update().get(pk=kh_row.pk)
            current_home = int(home_row.qty or 0)
            current_kh = int(kh_row.qty or 0)
            if current_kh >= 0:
                self.stdout.write(self.style.SUCCESS("KHORSHID ALREADY REPAIRED; NOTHING TO DO"))
                return
            current_move = -current_kh
            if current_home < current_move:
                raise CommandError("Stock changed since dry-run; transaction rolled back.")
            total_locked = current_home + current_kh

            home_row.qty = current_home - current_move
            kh_row.qty = 0
            home_row.save(update_fields=["qty"])
            kh_row.save(update_fields=["qty"])

            ref = "repair-negative-khorshid-v15"
            InventoryMovement.objects.create(
                movement_type=InventoryMovement.TRANSFER,
                brand=brand,
                size=size,
                color=color,
                location=home,
                delta=-current_move,
                reference=ref,
            )
            InventoryMovement.objects.create(
                movement_type=InventoryMovement.TRANSFER,
                brand=brand,
                size=size,
                color=color,
                location=kh,
                delta=current_move,
                reference=ref,
            )

            if int(home_row.qty or 0) + int(kh_row.qty or 0) != total_locked:
                raise CommandError("Total stock changed during repair; transaction rolled back.")

        self.stdout.write(self.style.SUCCESS("KHORSHID NEGATIVE V15 REPAIRED; TOTAL STOCK UNCHANGED"))
