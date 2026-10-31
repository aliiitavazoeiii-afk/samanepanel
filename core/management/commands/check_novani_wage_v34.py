from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum

from core import material_report_v20 as v20
from core import material_report_v21 as v21
from core.material_report_v14 import _tailor_row
from core.models import Brand, MaterialReportBlock, StockBalance

EXPECTED_DOZEN_WAGE = 110000


class Command(BaseCommand):
    help = "Transactional regression check: Novani output changes only Novani stock + tailor wage."

    def handle(self, *args, **options):
        novani = Brand.objects.get(name="Novani")
        darma = Brand.objects.get(name="دارما")

        darma_before = int(StockBalance.objects.filter(brand=darma).aggregate(v=Sum("qty"))["v"] or 0)
        novani_before = int(StockBalance.objects.filter(brand=novani).aggregate(v=Sum("qty"))["v"] or 0)
        tailor_obj = _tailor_row(create=False)
        tailor_before = int(tailor_obj.amount or 0) if tailor_obj else 0
        rate = int(v20._dozen_wage())
        if rate != EXPECTED_DOZEN_WAGE:
            raise CommandError(f"dozen wage mismatch: expected {EXPECTED_DOZEN_WAGE}, found {rate}")
        expected_wage = int(v20._wage_for_pieces(12, rate))

        with transaction.atomic():
            block = MaterialReportBlock.objects.create(
                date=date.today(),
                title="__NOVANI_WAGE_V34_ROLLBACK_TEST__",
                brand=novani,
                input_data=v20._blank_input_data(),
                output_data=v20._blank_output_data_for_brand(novani),
            )
            data = block.output_data
            first_model = v20.OUTPUT_MODELS[0][0]
            data[first_model]["s"] = "12"
            block.output_data = data
            block.save(update_fields=["output_data", "updated_at"])

            delta, wage, _details = v21._apply_output_delta(block)
            if delta != 12:
                raise CommandError(f"Novani delta mismatch: expected 12, got {delta}")
            if wage != expected_wage:
                raise CommandError(f"Novani wage mismatch: expected {expected_wage}, got {wage}")

            darma_inside = int(StockBalance.objects.filter(brand=darma).aggregate(v=Sum("qty"))["v"] or 0)
            novani_inside = int(StockBalance.objects.filter(brand=novani).aggregate(v=Sum("qty"))["v"] or 0)
            tailor_inside_obj = _tailor_row(create=False)
            tailor_inside = int(tailor_inside_obj.amount or 0) if tailor_inside_obj else 0

            if darma_inside != darma_before:
                raise CommandError(f"Darma stock leaked: {darma_before} -> {darma_inside}")
            if novani_inside != novani_before + 12:
                raise CommandError(f"Novani stock mismatch: expected {novani_before + 12}, got {novani_inside}")
            if tailor_inside != tailor_before - expected_wage:
                raise CommandError(
                    f"Tailor wage mismatch: expected {tailor_before - expected_wage}, got {tailor_inside}"
                )

            transaction.set_rollback(True)

        darma_after = int(StockBalance.objects.filter(brand=darma).aggregate(v=Sum("qty"))["v"] or 0)
        novani_after = int(StockBalance.objects.filter(brand=novani).aggregate(v=Sum("qty"))["v"] or 0)
        tailor_after_obj = _tailor_row(create=False)
        tailor_after = int(tailor_after_obj.amount or 0) if tailor_after_obj else 0

        if (darma_after, novani_after, tailor_after) != (darma_before, novani_before, tailor_before):
            raise CommandError("rollback test left business data changed")

        self.stdout.write(f"DOZEN_WAGE={rate}")
        self.stdout.write(f"12_PIECE_WAGE={expected_wage}")
        self.stdout.write("Novani: +12 stock, tailor -wage, Darma unchanged (transaction rolled back)")
        self.stdout.write("NOVANI WAGE V34 CHECK OK")
