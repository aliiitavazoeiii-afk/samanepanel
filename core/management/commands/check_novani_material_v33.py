from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum
from django.urls import resolve, reverse

from core.inventory_v20 import _sizes_for_brand
from core.material_report_v20 import NOVANI_OUTPUT_SIZES, _output_sizes_for_brand
from core import material_report_v21
from core.models import (
    Brand,
    ExcelManualRow,
    MaterialReportBlock,
    Size,
    StockBalance,
    StockLocation,
)

EXPECTED_NOVANI = ["S", "M", "L", "XL", "XXL", "3XL"]
EXPECTED_DARMA = ["M", "L", "XL", "XXL", "3XL", "4XL"]
EXPECTED_TAKVIN = ["M", "L", "XL", "XXL"]


def _brand_qty(brand):
    return int(StockBalance.objects.filter(brand=brand).aggregate(v=Sum("qty"))["v"] or 0)


def _persons_total():
    return int(
        ExcelManualRow.objects.filter(active=True, section=ExcelManualRow.PERSONS)
        .aggregate(v=Sum("amount"))["v"] or 0
    )


class Command(BaseCommand):
    help = "Verify Novani material-report sizes and inventory isolation. Transactional self-test rolls back."

    def handle(self, *args, **options):
        if not Size.objects.filter(name="S").exists():
            raise CommandError("Size S is missing; migration was not applied")

        novani = Brand.objects.get(name="Novani")
        darma = Brand.objects.get(name="دارما")
        takvin = Brand.objects.get(name="تکوین")

        if [x.name for x in _sizes_for_brand(novani)] != EXPECTED_NOVANI:
            raise CommandError("Novani inventory sizes mismatch")
        if [x.name for x in _sizes_for_brand(darma)] != EXPECTED_DARMA:
            raise CommandError("Darma inventory sizes changed unexpectedly")
        if [x.name for x in _sizes_for_brand(takvin)] != EXPECTED_TAKVIN:
            raise CommandError("Takvin inventory sizes changed unexpectedly")

        if [label for _key, label in _output_sizes_for_brand(novani)] != EXPECTED_NOVANI:
            raise CommandError("Novani material-report sizes mismatch")
        if [label for _key, label in _output_sizes_for_brand(darma)] != EXPECTED_DARMA:
            raise CommandError("Darma material-report sizes changed unexpectedly")
        if list(NOVANI_OUTPUT_SIZES) != [
            ("s", "S"), ("m", "M"), ("l", "L"), ("xl", "XL"), ("xxl", "XXL"), ("3xl", "3XL")
        ]:
            raise CommandError("Novani size constants mismatch")

        home = StockLocation.objects.get(key=StockLocation.HOME)
        s = Size.objects.get(name="S")
        novani_s_rows = StockBalance.objects.filter(brand=novani, size=s, location=home).count()
        darma_s_qty = int(StockBalance.objects.filter(brand=darma, size=s).aggregate(v=Sum("qty"))["v"] or 0)
        takvin_s_qty = int(StockBalance.objects.filter(brand=takvin, size=s).aggregate(v=Sum("qty"))["v"] or 0)
        if novani_s_rows <= 0:
            raise CommandError("Novani S stock rows were not seeded")
        if darma_s_qty != 0 or takvin_s_qty != 0:
            raise CommandError(f"S stock leaked to another brand: Darma={darma_s_qty}, Takvin={takvin_s_qty}")

        resolved = resolve(reverse("material_block_apply_output", args=[1]))
        if resolved.func.__module__ != "core.material_report_v21":
            raise CommandError(f"Apply-output route is not isolated v21: {resolved.func.__module__}")

        # Transactional proof: apply one temporary Novani S/black output, assert that
        # only Novani qty changes, then roll the entire self-test back.
        darma_before = _brand_qty(darma)
        takvin_before = _brand_qty(takvin)
        novani_before = _brand_qty(novani)
        persons_before = _persons_total()

        with transaction.atomic():
            sid = transaction.savepoint()
            block = MaterialReportBlock.objects.create(
                date=date.today(),
                title="V33 isolation self-test",
                brand=novani,
                input_data={},
                output_data={"black": {"s": "1", "delivery_date": ""}},
                note="",
            )
            delta, wage, _details = material_report_v21._apply_output_delta(block)
            if delta != 1 or wage != 0:
                raise CommandError(f"Novani test delta/wage mismatch: delta={delta}, wage={wage}")
            if _brand_qty(novani) != novani_before + 1:
                raise CommandError("Novani test output did not increase Novani by exactly 1")
            if _brand_qty(darma) != darma_before:
                raise CommandError("Novani test changed Darma stock")
            if _brand_qty(takvin) != takvin_before:
                raise CommandError("Novani test changed Takvin stock")
            if _persons_total() != persons_before:
                raise CommandError("Novani test changed persons/tailor balance")
            transaction.savepoint_rollback(sid)

        if _brand_qty(novani) != novani_before or _brand_qty(darma) != darma_before or _persons_total() != persons_before:
            raise CommandError("V33 self-test rollback did not restore database state")

        self.stdout.write(f"Novani sizes: {EXPECTED_NOVANI}")
        self.stdout.write(f"Darma sizes unchanged: {EXPECTED_DARMA}")
        self.stdout.write(f"Takvin sizes unchanged: {EXPECTED_TAKVIN}")
        self.stdout.write(f"Novani S rows: {novani_s_rows}")
        self.stdout.write("Isolation self-test: Novani +1 only; Darma/Takvin/persons unchanged; rolled back")
        self.stdout.write("NOVANI MATERIAL V33 CHECK OK")
