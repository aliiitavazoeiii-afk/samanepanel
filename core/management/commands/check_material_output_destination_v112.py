"""Transactional V112: one destination for all new output, no double count or old-stock relocation."""
from datetime import date
from hashlib import sha256
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from core import material_report_v23 as v23
from core.models import (
    AppSetting, Brand, InventoryModelCost, InventoryMovement, MaterialReportBlock,
    MaterialReportOutputApplied, MaterialReportOutputLocation, StockBalance,
    StockLocation, TailorBalanceEntry,
)


def _digest(model):
    fields = [field.attname for field in model._meta.concrete_fields]
    h = sha256()
    for row in model.objects.order_by(model._meta.pk.attname).values_list(*fields):
        h.update(repr(tuple(row)).encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def _state():
    return {model.__name__: _digest(model) for model in (
        AppSetting, InventoryModelCost, InventoryMovement, MaterialReportBlock,
        MaterialReportOutputApplied, MaterialReportOutputLocation, StockBalance,
        TailorBalanceEntry,
    )}


def _stock(brand, color, size, location):
    return int(StockBalance.objects.filter(
        brand=brand, color=color, size=size, location=location
    ).values_list("qty", flat=True).first() or 0)


def _set_target(block, key, size_key, quantity):
    data = dict(block.output_data or {})
    row = dict(data.get(key) or {})
    row[size_key] = str(quantity)
    data[key] = row
    block.output_data = data
    block.save(update_fields=["output_data"])


class Command(BaseCommand):
    help = "V112: transactional destination selection, old allocations, per-location stock and idempotent sync."

    def handle(self, *args, **kwargs):
        before = _state()
        darma = Brand.objects.get(name="دارما")
        home = StockLocation.objects.get(key=StockLocation.HOME)
        khorshid = StockLocation.objects.get(key=StockLocation.KHORSHID)

        if v23._output_destination(darma, "home")[0].id != home.id:
            raise RuntimeError("Home destination resolver failed")
        if v23._output_destination(darma, "khorshid")[0].id != khorshid.id:
            raise RuntimeError("Khorshid destination resolver failed")
        for forbidden in ("unknown", "tailor", ""):
            try:
                if forbidden == "":
                    # Internal legacy call is allowed to default to Khorshid.
                    if v23._output_destination(darma)[0].id != khorshid.id:
                        raise RuntimeError("Legacy Darma destination changed")
                    continue
                v23._output_destination(darma, forbidden)
            except ValueError:
                continue
            raise RuntimeError(f"Invalid destination was accepted: {forbidden}")

        with transaction.atomic():
            try:
                black = v23.v20._find_color("مشکی")
                pink = v23.v20._find_color("صورتی")
                m = v23.Size.objects.get(name="M")
                xl = v23.Size.objects.get(name="XL")
                initial = {
                    (color.id, size.id, loc.id): _stock(darma, color, size, loc)
                    for color, size in ((black, m), (pink, xl))
                    for loc in (home, khorshid)
                }
                block = MaterialReportBlock.objects.create(
                    date=date.today(),
                    title="V112 rollout probe (rolled back)",
                    brand=darma,
                    input_data={"_meta": {"active_material_keys": ["black", "pink"]}},
                    output_data={
                        "black": {"m": "50"},
                        "pink": {"xl": "25"},
                    },
                )
                before_movements = InventoryMovement.objects.filter(
                    reference=f"material-report:{block.id}:output-sync-v112"
                ).count()
                result1 = v23._sync_output(block, "home")
                if result1["piece_delta"] != 75:
                    raise RuntimeError(f"First home batch should apply 75, got {result1['piece_delta']}")
                if _stock(darma, black, m, home) != initial[(black.id, m.id, home.id)] + 50:
                    raise RuntimeError("Home black +50 not applied")
                if _stock(darma, pink, xl, home) != initial[(pink.id, xl.id, home.id)] + 25:
                    raise RuntimeError("Home pink +25 not applied")
                for color, size in ((black, m), (pink, xl)):
                    if _stock(darma, color, size, khorshid) != initial[(color.id, size.id, khorshid.id)]:
                        raise RuntimeError("Old Khorshid stock was altered by Home delivery")

                # Same click again must be idempotent even with a DIFFERENT
                # selected warehouse: selection must not transfer old pieces.
                result2 = v23._sync_output(block, "khorshid")
                if result2["piece_delta"] != 0:
                    raise RuntimeError("Repeated sync counted existing deliveries again")

                _set_target(block, "black", "m", 80)
                _set_target(block, "pink", "xl", 35)
                result3 = v23._sync_output(block, "khorshid")
                if result3["piece_delta"] != 40:
                    raise RuntimeError("New Khorshid batch should add +30 black and +10 pink")
                if _stock(darma, black, m, home) != initial[(black.id, m.id, home.id)] + 50:
                    raise RuntimeError("Home black was moved to Khorshid")
                if _stock(darma, pink, xl, home) != initial[(pink.id, xl.id, home.id)] + 25:
                    raise RuntimeError("Home pink was moved to Khorshid")
                if _stock(darma, black, m, khorshid) != initial[(black.id, m.id, khorshid.id)] + 30:
                    raise RuntimeError("Khorshid black +30 was not applied")
                if _stock(darma, pink, xl, khorshid) != initial[(pink.id, xl.id, khorshid.id)] + 10:
                    raise RuntimeError("Khorshid pink +10 was not applied")

                counts = {
                    (
                        allocation.applied.model_key,
                        allocation.applied.size_key,
                        allocation.location.key,
                    ): int(allocation.quantity)
                    for allocation in MaterialReportOutputLocation.objects.filter(
                        applied__block=block
                    ).select_related("applied", "location")
                }
                for key, expected in {
                    ("black", "m", "home"): 50,
                    ("black", "m", "khorshid"): 30,
                    ("pink", "xl", "home"): 25,
                    ("pink", "xl", "khorshid"): 10,
                }.items():
                    if counts.get(key) != expected:
                        raise RuntimeError(f"Allocation mismatch {key}: {counts.get(key)} vs {expected}")

                movements = InventoryMovement.objects.filter(
                    reference=f"material-report:{block.id}:output-sync-v112"
                ).count()
                if movements != before_movements + 4:
                    raise RuntimeError("There must be exactly four stock movements across both batches")
                if v23._sync_output(block, "home")["piece_delta"] != 0:
                    raise RuntimeError("Third repeated sync not idempotent")
                if InventoryMovement.objects.filter(
                    reference=f"material-report:{block.id}:output-sync-v112"
                ).count() != movements:
                    raise RuntimeError("Repeat sync created a duplicate production movement")

                # A decrease is reversed only from a tracked real warehouse.
                _set_target(block, "black", "m", 70)
                reduction = v23._sync_output(block, "khorshid")
                if reduction["piece_delta"] != -10:
                    raise RuntimeError("Tracked Khorshid reduction did not apply -10")
                if _stock(darma, black, m, home) != initial[(black.id, m.id, home.id)] + 50:
                    raise RuntimeError("Reduction touched unrelated Home stock")
                if _stock(darma, black, m, khorshid) != initial[(black.id, m.id, khorshid.id)] + 20:
                    raise RuntimeError("Reduction ignored tracked Khorshid stock")

                # Existing pre-V112 applied totals have no location rows.
                # They must be classified as legacy Khorshid without applying
                # *any* new inventory or movement.
                legacy = MaterialReportBlock.objects.create(
                    date=date.today(),
                    brand=darma,
                    title="V112 legacy allocation probe",
                    input_data={"_meta": {"active_material_keys": ["black"]}},
                    output_data={"black": {"m": "20"}},
                )
                old = MaterialReportOutputApplied.objects.create(
                    block=legacy, model_key="black", size_key="m", quantity=20
                )
                movements_before = InventoryMovement.objects.count()
                stock_before = _stock(darma, black, m, khorshid)
                v23._output_location_rows(old, darma)
                alloc = MaterialReportOutputLocation.objects.get(applied=old)
                if alloc.location_id != khorshid.id or alloc.quantity != 20:
                    raise RuntimeError("Legacy output was not classified as historical Khorshid")
                if InventoryMovement.objects.count() != movements_before or _stock(darma, black, m, khorshid) != stock_before:
                    raise RuntimeError("Legacy classification incorrectly modified stock")
            finally:
                transaction.set_rollback(True)

        if before != _state():
            raise RuntimeError("V112 test changed persistent stock/cost/wage/output state")

        source = (Path(settings.BASE_DIR) / "templates/core/material_report_v36.html").read_text(encoding="utf-8")
        for marker in (
            "delivery-destination-dialog", 'name="delivery_destination"',
            'value="home"', 'value="khorshid"',
            "همگام‌سازی تحویل و موجودی",
            "مزد خیاط خودکار محاسبه می‌شود",
        ):
            if marker not in source:
                raise RuntimeError(f"Warehouse selection dialog missing: {marker}")

        self.stdout.write("ONE CONFIRMATION = HOME OR KHORSHID")
        self.stdout.write("MULTI-COLOR HOME BATCH = +75")
        self.stdout.write("SECOND KHORSHID BATCH = +40, OLD HOME STOCK UNCHANGED")
        self.stdout.write("REPEATED SYNC = ZERO DELTA / ZERO DUPLICATE MOVEMENTS")
        self.stdout.write("WAREHOUSE ALLOCATIONS = PER MODEL + SIZE + LOCATION")
        self.stdout.write("LEGACY APPLIED OUTPUT = CLASSIFIED WITHOUT STOCK CHANGES")
        self.stdout.write("SINGLE-WAREHOUSE REDUCTION = TRACKED AND REVERSIBLE")
        self.stdout.write("TAILOR WAGE = EXISTING AUTOMATIC CALCULATION")
        self.stdout.write("ALL TEST WRITES = ROLLED BACK")
        self.stdout.write(self.style.SUCCESS(
            "SUCCESS: TAILOR DELIVERY WAREHOUSE V112 CHECK PASSED"
        ))
