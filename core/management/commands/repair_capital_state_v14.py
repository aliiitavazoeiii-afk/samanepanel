from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.excel_views import OUTPUT_MODELS, OUTPUT_SIZES
from core.material_purchase_v14 import backfill_v13_ledger, ledger_for_payment
from core.models import (
    AppSetting,
    Brand,
    BusinessPayment,
    Color,
    InventoryModelCost,
    MaterialReportBlock,
    Size,
    StockBalance,
    StockLocation,
)

REPAIR_KEY = "capital_v14_legacy_repair_done"


def _int(value):
    try:
        return max(0, int(float(str(value or 0).replace("٬", "").replace(",", ""))))
    except Exception:
        return 0


def _norm(value):
    return (value or "").replace("ي", "ی").replace("ك", "ک").replace("‌", "").replace(" ", "").strip().lower()


def _find_color(label):
    wanted = _norm(label)
    for color in Color.objects.filter(active=True):
        if _norm(color.name) == wanted:
            return color
    return None


def _output_total(output_data):
    total = 0
    for model_key, _ in OUTPUT_MODELS:
        values = (output_data or {}).get(model_key, {}) or {}
        for size_key, _ in OUTPUT_SIZES:
            total += _int(values.get(size_key))
    return total


class Command(BaseCommand):
    help = "Repair v13 orphan finished stock and backfill durable material purchase ledgers."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        apply = bool(options.get("apply"))
        already_done = AppSetting.objects.filter(key=REPAIR_KEY, value="1").exists()
        self.stdout.write("=== CAPITAL STATE REPAIR V14 ===")
        self.stdout.write(f"MODE = {'APPLY' if apply else 'DRY RUN'}")
        self.stdout.write(f"ALREADY DONE = {already_done}")
        if already_done:
            self.stdout.write(self.style.SUCCESS("V14 LEGACY REPAIR ALREADY APPLIED; NOTHING TO DO"))
            return

        brand = Brand.objects.get(name="دارما")
        khorshid = StockLocation.objects.get(key=StockLocation.KHORSHID)
        orphan_blocks = []
        required = {}

        for block in MaterialReportBlock.objects.order_by("id"):
            # In v13 every save added output stock. If no consumption exists now,
            # that output is an orphan under the new explicit-apply semantics.
            if block.stock_consumptions.exists():
                continue
            total = _output_total(block.output_data or {})
            if total <= 0:
                continue
            orphan_blocks.append((block.id, str(block.date), block.title or "صورت مواد اولیه", total))
            for model_key, label in OUTPUT_MODELS:
                values = (block.output_data or {}).get(model_key, {}) or {}
                color = _find_color(label)
                if color is None:
                    raise CommandError(f"Color not found for legacy output: {label}")
                for size_key, size_name in OUTPUT_SIZES:
                    qty = _int(values.get(size_key))
                    if qty <= 0:
                        continue
                    size = Size.objects.get(name=size_name)
                    key = (color.id, size.id, label, size_name)
                    required[key] = required.get(key, 0) + qty

        self.stdout.write(f"ORPHAN UNAPPLIED BLOCKS = {len(orphan_blocks)}")
        for row in orphan_blocks:
            self.stdout.write(f"ORPHAN BLOCK: id={row[0]} date={row[1]} title={row[2]} shorts={row[3]}")

        conflicts = []
        orphan_value = 0
        for (color_id, size_id, label, size_name), qty in sorted(required.items(), key=lambda x: (x[0][2], x[0][3])):
            current = int(
                StockBalance.objects.filter(
                    brand=brand, color_id=color_id, size_id=size_id, location=khorshid
                ).values_list("qty", flat=True).first() or 0
            )
            unit_cost = int(
                InventoryModelCost.objects.filter(
                    brand=brand, color_id=color_id, size_id=size_id
                ).values_list("unit_cost", flat=True).first() or 0
            )
            orphan_value += qty * unit_cost
            self.stdout.write(
                f"LEGACY OUTPUT CHECK: {label}/{size_name} need_remove={qty} khorshid={current} cost={unit_cost} value={qty * unit_cost}"
            )
            if current < qty:
                conflicts.append(f"{label}/{size_name}: need {qty}, khorshid has {current}")
        self.stdout.write(f"ORPHAN FINISHED VALUE TO REMOVE = {orphan_value}")

        material_payments = BusinessPayment.objects.filter(payee__in=["fabric", "elastic"]).order_by("id")
        backfillable = 0
        unresolved = []
        for payment in material_payments:
            if ledger_for_payment(payment):
                continue
            from core.material_purchase_v13 import parse_purchase_note
            if parse_purchase_note(payment.note):
                backfillable += 1
            else:
                unresolved.append(payment.id)
        self.stdout.write(f"LEGACY MATERIAL LEDGERS TO BACKFILL = {backfillable}")
        if unresolved:
            self.stdout.write(self.style.WARNING(
                "UNLINKED OLD MATERIAL PAYMENTS (delete will be blocked): " + ", ".join(map(str, unresolved))
            ))

        if conflicts:
            for item in conflicts:
                self.stderr.write(self.style.ERROR("REPAIR CONFLICT: " + item))
            raise CommandError("Legacy orphan output cannot be safely removed; no changes made.")

        if not apply:
            self.stdout.write(self.style.WARNING("DRY RUN ONLY; run with --apply to repair."))
            return

        with transaction.atomic():
            for (color_id, size_id, _label, _size_name), qty in required.items():
                stock, _ = StockBalance.objects.select_for_update().get_or_create(
                    brand=brand,
                    color_id=color_id,
                    size_id=size_id,
                    location=khorshid,
                    defaults={"qty": 0},
                )
                if int(stock.qty or 0) < qty:
                    raise CommandError("Stock changed during repair; transaction rolled back.")
                stock.qty = int(stock.qty or 0) - qty
                stock.save(update_fields=["qty"])

            for payment in BusinessPayment.objects.select_for_update().filter(payee__in=["fabric", "elastic"]):
                if not ledger_for_payment(payment):
                    backfill_v13_ledger(payment)

            AppSetting.objects.update_or_create(
                key=REPAIR_KEY,
                defaults={"value": "1", "label": "Capital v14 legacy repair done"},
            )

        self.stdout.write(self.style.SUCCESS(
            f"CAPITAL V14 LEGACY REPAIR APPLIED; removed {orphan_value} toman orphan finished value from {len(orphan_blocks)} block(s)."
        ))
