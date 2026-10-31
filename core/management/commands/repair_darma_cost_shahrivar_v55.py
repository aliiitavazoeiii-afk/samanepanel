from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.darma_cost_v55 import darma_cost_for, ensure_darma_cost_baseline
from core.dateutils import parse_jalali_date
from core.finance import digikala_fee_for_unit
from core.models import DiaGallerySale, SaleLine, SaleSnapshot


TARGET_JALALI_DATES = ("1405/06/12", "1405/06/14")
DARMA_BACKED_BRANDS = ("دارما", "انبارش")


class Command(BaseCommand):
    help = "Repair only Darma-backed COGS snapshots on 1405/06/12 and 1405/06/14."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply the repair. Without this flag the command is dry-run only.",
        )

    def handle(self, *args, **options):
        apply = bool(options["apply"])
        dates = [parse_jalali_date(value) for value in TARGET_JALALI_DATES]

        # An explicit apply also establishes the user's confirmed 61,000 baseline
        # before planning, so target costs are deterministic. Dry-run remains
        # strictly read-only; the deploy script seeds the baseline before dry-run.
        if apply:
            ensure_darma_cost_baseline()

        lines = list(
            SaleLine.objects.filter(
                day__date__in=dates,
                quantity__gt=0,
                product_size__product__brand__name__in=DARMA_BACKED_BRANDS,
            )
            .select_related("day", "product_size__product__brand", "product_size__size")
            .order_by("day__date", "id")
        )
        dia_lines = list(
            DiaGallerySale.objects.filter(day__date__in=dates, quantity__gt=0)
            .select_related("day", "size", "color")
            .order_by("day__date", "id")
        )

        if not lines and not dia_lines:
            raise CommandError("No Darma-backed sales found on 1405/06/12 or 1405/06/14; repair aborted.")

        planned = []
        old_cogs = 0
        new_cogs = 0

        for line in lines:
            target_cost = int(darma_cost_for(line.day.date))
            snap = SaleSnapshot.objects.filter(sale_line=line).first()
            pack_qty = int((snap.pack_qty if snap else 0) or line.product_size.product.pack_qty or 0)
            old_unit = int((snap.unit_cost if snap else 0) or line.product_size.unit_cost or 0)
            shorts = int(line.quantity or 0) * pack_qty
            old_cogs += shorts * old_unit
            new_cogs += shorts * target_cost
            if old_unit != target_cost or snap is None:
                planned.append(("sale", line, snap, old_unit, target_cost, pack_qty))

        for line in dia_lines:
            target_cost = int(darma_cost_for(line.day.date))
            old_unit = int(line.unit_cost or 0)
            qty = int(line.quantity or 0)
            old_cogs += qty * old_unit
            new_cogs += qty * target_cost
            if old_unit != target_cost:
                planned.append(("dia", line, None, old_unit, target_cost, 1))

        self.stdout.write("DARMA COST REPAIR V55")
        self.stdout.write(f"DATES={','.join(TARGET_JALALI_DATES)}")
        self.stdout.write(f"SALE_LINES={len(lines)} DIA_LINES={len(dia_lines)}")
        self.stdout.write(f"ROWS_TO_CHANGE={len(planned)}")
        self.stdout.write(f"OLD_TARGET_COGS={old_cogs}")
        self.stdout.write(f"NEW_TARGET_COGS={new_cogs}")
        self.stdout.write(f"REPORT_PROFIT_DELTA={old_cogs - new_cogs}")

        for kind, line, snap, old_unit, target_cost, pack_qty in planned:
            if kind == "sale":
                self.stdout.write(
                    f"SALE id={line.id} date={line.day.date} brand={line.product_size.product.brand.name} "
                    f"code={line.product_size.product.code} old={old_unit} new={target_cost}"
                )
            else:
                self.stdout.write(
                    f"DIA id={line.id} date={line.day.date} {line.color.name}/{line.size.name} "
                    f"old={old_unit} new={target_cost}"
                )

        if not apply:
            self.stdout.write(self.style.WARNING("DRY RUN ONLY — no row or setting changed. Re-run with --apply."))
            return

        with transaction.atomic():
            for kind, line, snap, old_unit, target_cost, pack_qty in planned:
                if kind == "sale":
                    if snap is None:
                        snap = SaleSnapshot.objects.create(
                            sale_line=line,
                            unit_cost=target_cost,
                            pack_qty=pack_qty,
                            digikala_fee_unit=digikala_fee_for_unit(int(line.sale_price or 0)),
                        )
                    else:
                        snap.unit_cost = target_cost
                        snap.save(update_fields=["unit_cost", "updated_at"])
                else:
                    line.unit_cost = target_cost
                    line.save(update_fields=["unit_cost", "updated_at"])

            for line in lines:
                snap = SaleSnapshot.objects.filter(sale_line=line).first()
                if snap is None or int(snap.unit_cost or 0) != int(darma_cost_for(line.day.date)):
                    raise CommandError(f"Post-repair SaleSnapshot verification failed for sale_line={line.id}")
            for line in dia_lines:
                line.refresh_from_db(fields=["unit_cost"])
                if int(line.unit_cost or 0) != int(darma_cost_for(line.day.date)):
                    raise CommandError(f"Post-repair Dia verification failed for dia_line={line.id}")

        self.stdout.write(self.style.SUCCESS("SUCCESS: DARMA COST SHAHRIVAR V55 REPAIR APPLIED"))
        self.stdout.write("Only SaleSnapshot.unit_cost and DiaGallerySale.unit_cost on 1405/06/12 + 1405/06/14 were repaired.")
        self.stdout.write("Inventory quantities, Digikala receivable, accounts, sale prices and fees were not changed.")
