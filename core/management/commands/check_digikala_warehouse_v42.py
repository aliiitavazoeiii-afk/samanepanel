from django.core.management.base import BaseCommand, CommandError

from core.digikala_warehouse_v42 import get_free_warehouse_board


class Command(BaseCommand):
    help = "Validate the read-only Digikala V42 free-warehouse calculation."

    def add_arguments(self, parser):
        parser.add_argument("--live", action="store_true", help="Read the live Digikala API.")

    def handle(self, *args, **options):
        if not options["live"]:
            self.stdout.write("DIGIKALA WAREHOUSE V42 SOURCE CHECK OK")
            return

        board = get_free_warehouse_board(force=True)
        rows = board.get("rows") or []

        for row in rows:
            sellable = int(row.get("sellable_stock") or 0)
            reserved = int(row.get("reserved_stock") or 0)
            free = int(row.get("free_stock") or 0)
            if sellable < 0 or reserved < 0 or free < 0:
                raise CommandError("negative warehouse quantity detected")
            if reserved > sellable:
                raise CommandError("reserved stock exceeds sellable stock after per-row clamp")
            if free != sellable - reserved:
                raise CommandError("free stock identity mismatch")
            expected_status = "free" if free > 0 else "zero"
            if row.get("status") != expected_status:
                raise CommandError("warehouse row status mismatch")

        sellable_total = sum(int(row.get("sellable_stock") or 0) for row in rows)
        reserved_total = sum(int(row.get("reserved_stock") or 0) for row in rows)
        free_total = sum(int(row.get("free_stock") or 0) for row in rows)
        free_variants = sum(1 for row in rows if int(row.get("free_stock") or 0) > 0)

        if sellable_total != int(board.get("sellable_total") or 0):
            raise CommandError("sellable total mismatch")
        if reserved_total != int(board.get("reserved_total") or 0):
            raise CommandError("reserved total mismatch")
        if free_total != int(board.get("free_total") or 0):
            raise CommandError("free total mismatch")
        if free_variants != int(board.get("free_variant_count") or 0):
            raise CommandError("free variant count mismatch")

        self.stdout.write("DIGIKALA WAREHOUSE V42 LIVE READ OK")
        self.stdout.write(f"INVENTORY_ROWS={board.get('inventory_rows_scanned', 0)}")
        self.stdout.write(f"WAREHOUSE_VARIANTS={board.get('variant_count', 0)}")
        self.stdout.write(f"SELLABLE_DK={sellable_total}")
        self.stdout.write(f"RESERVED_DK={reserved_total}")
        self.stdout.write(f"FREE_DK={free_total}")
        self.stdout.write(f"FREE_VARIANTS={free_variants}")
        self.stdout.write(f"ZERO_FREE_VARIANTS={board.get('zero_variant_count', 0)}")
        self.stdout.write(f"RESERVE_OVER_STOCK={board.get('reserve_over_stock_total', 0)}")
        self.stdout.write("NO BUSINESS DATA CHANGED")
