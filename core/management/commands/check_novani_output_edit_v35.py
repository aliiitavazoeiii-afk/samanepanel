from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum
from django.urls import resolve

from core import material_report_v20 as v20
from core import material_report_v22 as v22
from core.material_report_v14 import _tailor_row
from core.models import Brand, MaterialReportBlock, StockBalance


class Command(BaseCommand):
    help = "Transactional regression check for two-way Darma/Novani delivery sync and cut variance."

    def _qty(self, brand):
        return int(StockBalance.objects.filter(brand=brand).aggregate(v=Sum("qty"))["v"] or 0)

    def handle(self, *args, **options):
        if resolve("/material-report/").func.__module__ != "core.material_report_v22":
            raise CommandError("material-report route is not using v22")

        rate = int(v20._dozen_wage())
        if rate != 110000:
            raise CommandError(f"dozen wage must be 110000, found {rate}")

        novani = Brand.objects.get(name="Novani")
        darma = Brand.objects.get(name="دارما")
        novani_before = self._qty(novani)
        darma_before = self._qty(darma)
        tailor_obj = _tailor_row(create=False)
        tailor_before = int(tailor_obj.amount or 0) if tailor_obj else 0

        with transaction.atomic():
            # Novani: +12 then clear to zero. Stock and wage must round-trip exactly.
            nblock = MaterialReportBlock.objects.create(
                date=date.today(), title="__NOVANI_OUTPUT_V35_ROLLBACK_TEST__", brand=novani,
                input_data=v20._blank_input_data(), output_data=v20._blank_output_data_for_brand(novani),
            )
            nblock.input_data["black"]["cut"] = "20"
            nblock.input_data["white"]["cut"] = "30"
            nblock.input_data["navy"]["cut"] = "40"
            nblock.output_data["black"]["s"] = "12"
            nblock.save(update_fields=["input_data", "output_data", "updated_at"])
            nplus = v22._sync_output(nblock)
            if nplus["piece_delta"] != 12 or nplus["wage_change"] != 110000:
                raise CommandError(f"Novani positive sync mismatch: {nplus}")
            if self._qty(novani) != novani_before + 12 or self._qty(darma) != darma_before:
                raise CommandError("Novani sync leaked into wrong inventory")

            nview = v22._view_block_v35(nblock)
            black = next(x for x in nview["output_rows"] if x["model_key"] == "black")
            if black["cut_total"] != 20 or black["total"] != 12 or black["cut_diff"] != -8:
                raise CommandError(f"cut variance mismatch: {black}")

            # Reverse models are output-only rows and must never borrow black/white/navy cuts.
            for key in ("reverse_black", "reverse_white", "reverse_navy"):
                reverse_row = next(x for x in nview["output_rows"] if x["model_key"] == key)
                if reverse_row["cut_total"] != 0 or reverse_row["cut_diff"] != 0:
                    raise CommandError(f"reverse model borrowed a base-color cut: {key} -> {reverse_row}")

            nblock.output_data["black"]["s"] = ""
            nblock.save(update_fields=["output_data", "updated_at"])
            v22._validate_output_editable(nblock)
            nminus = v22._sync_output(nblock)
            if nminus["piece_delta"] != -12 or nminus["wage_change"] != -110000:
                raise CommandError(f"Novani negative sync mismatch: {nminus}")
            if self._qty(novani) != novani_before:
                raise CommandError("Novani negative sync did not restore inventory")

            # Darma: same two-way rule, but using KHORSHID + existing cost-blending/reversal path.
            dblock = MaterialReportBlock.objects.create(
                date=date.today(), title="__DARMA_OUTPUT_V35_ROLLBACK_TEST__", brand=darma,
                input_data=v20._blank_input_data(), output_data=v20._blank_output_data_for_brand(darma),
            )
            dblock.input_data["black"]["cut"] = "20"
            dblock.output_data["black"]["m"] = "12"
            dblock.save(update_fields=["input_data", "output_data", "updated_at"])
            dplus = v22._sync_output(dblock)
            if dplus["piece_delta"] != 12 or dplus["wage_change"] != 110000:
                raise CommandError(f"Darma positive sync mismatch: {dplus}")
            if self._qty(darma) != darma_before + 12 or self._qty(novani) != novani_before:
                raise CommandError("Darma sync leaked into wrong inventory")

            dblock.output_data["black"]["m"] = ""
            dblock.save(update_fields=["output_data", "updated_at"])
            v22._validate_output_editable(dblock)
            dminus = v22._sync_output(dblock)
            if dminus["piece_delta"] != -12 or dminus["wage_change"] != -110000:
                raise CommandError(f"Darma negative sync mismatch: {dminus}")
            if self._qty(darma) != darma_before:
                raise CommandError("Darma negative sync did not restore inventory")

            tailor_inside_obj = _tailor_row(create=False)
            tailor_inside = int(tailor_inside_obj.amount or 0) if tailor_inside_obj else 0
            if tailor_inside != tailor_before:
                raise CommandError("two-way wage round-trip did not restore tailor balance")

            transaction.set_rollback(True)

        novani_after = self._qty(novani)
        darma_after = self._qty(darma)
        tailor_after_obj = _tailor_row(create=False)
        tailor_after = int(tailor_after_obj.amount or 0) if tailor_after_obj else 0
        if (novani_after, darma_after, tailor_after) != (novani_before, darma_before, tailor_before):
            raise CommandError("rollback regression test left business data changed")

        self.stdout.write("BOTH BRAND OUTPUT V35 CHECK OK")
        self.stdout.write("Novani: increase/reduce/clear reverses stock+wage exactly")
        self.stdout.write("Darma: increase/reduce/clear reverses KHORSHID stock/value+wage exactly")
        self.stdout.write("Cut variance: cut=20 / delivered=12 -> shortage=8")
        self.stdout.write("Reverse black/white/navy: cut remains zero and never borrows base-color cut")
        self.stdout.write("Dozen wage: 110000 per 12 delivered pieces")
