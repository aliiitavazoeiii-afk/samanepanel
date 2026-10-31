"""Transactional regression for V106 person-account payments + three-part tailor deliveries."""
from datetime import date
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from core import business_tools_v62 as v62
from core import material_report_v23 as v23
from core.dateutils import format_jalali
from core.models import (
    AppSetting,
    Brand,
    BusinessPayment,
    ExcelManualRow,
    InventoryModelCost,
    InventoryMovement,
    MaterialReportBlock,
    MaterialReportOutputApplied,
    StockBalance,
    TailorBalanceEntry,
)


def _digest(model):
    fields = [field.attname for field in model._meta.concrete_fields]
    h = sha256()
    for row in model.objects.order_by(model._meta.pk.attname).values_list(*fields):
        h.update(repr(tuple(row)).encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def _state():
    return {
        "manual_rows": _digest(ExcelManualRow),
        "payments": _digest(BusinessPayment),
        "blocks": _digest(MaterialReportBlock),
        "output_applied": _digest(MaterialReportOutputApplied),
        "stock": _digest(StockBalance),
        "model_cost": _digest(InventoryModelCost),
        "movements": _digest(InventoryMovement),
        "tailor": _digest(TailorBalanceEntry),
        "settings": _digest(AppSetting),
    }


class Command(BaseCommand):
    help = "Transactional rollback regression for V106."

    def handle(self, *args, **kwargs):
        before = _state()

        with transaction.atomic():
            person = ExcelManualRow.objects.create(
                section=ExcelManualRow.PERSONS,
                title="V106 TEST PERSON",
                amount=100_000,
                sort_order=999_999,
                note="rollback-only V106 regression",
            )
            payee = v62.person_payee_key(person.id)
            choices = dict(v62.person_payee_choices())
            if choices.get(payee) != person.title:
                raise RuntimeError("Person account did not appear in payment choices")

            source_before = int(v62.source_balance(v62.SOURCE_MELAT))
            parsed = v62._parse_payment_post(
                {
                    "date": format_jalali(date.today()),
                    "payee": payee,
                    "amount": "40000",
                    "note": "V106 rollback payment",
                    "source_account": v62.SOURCE_MELAT,
                }
            )
            payment = BusinessPayment.objects.create(
                date=parsed["date"],
                payee=parsed["payee"],
                source_account=parsed["source_account"],
                amount=parsed["paid"],
                note=parsed["note"],
            )
            v62._apply_full(payment, parsed)
            person.refresh_from_db()
            if int(person.amount or 0) != 60_000:
                raise RuntimeError(f"Person balance after payment is {person.amount}, expected 60000")
            if int(v62.source_balance(v62.SOURCE_MELAT)) != source_before - 40_000:
                raise RuntimeError("Payment source was not reduced by person payment")

            # Editing must validate AFTER the old payment is reversed. This catches
            # the important 40 -> 70 case where the current visible balance is only 60.
            parsed_edit = v62._parse_payment_post(
                {
                    "date": format_jalali(date.today()),
                    "payee": payee,
                    "amount": "70000",
                    "note": "V106 rollback edited payment",
                    "source_account": v62.SOURCE_MELAT,
                }
            )
            v62._reverse_full(payment)
            v62._save_payment_fields(payment, parsed_edit)
            v62._apply_full(payment, parsed_edit)
            person.refresh_from_db()
            if int(person.amount or 0) != 30_000:
                raise RuntimeError("Edited person payment did not reapply against restored balance")

            v62._reverse_full(payment)
            person.refresh_from_db()
            if int(person.amount or 0) != 100_000:
                raise RuntimeError("Person balance was not restored on reverse")
            if int(v62.source_balance(v62.SOURCE_MELAT)) != source_before:
                raise RuntimeError("Payment source was not restored on reverse")
            payment.delete()

            brand = Brand.objects.filter(name="دارما", active=True).first()
            if not brand:
                raise RuntimeError("Darma brand missing for V106 delivery regression")
            request = SimpleNamespace(
                POST={
                    "out_black_xl_1": "50",
                    "out_black_xl_2": "70",
                    "out_black_xl_3": "50",
                }
            )
            output = v23._parse_output(request, brand, ["black"])
            values = output["black"]
            if values.get("xl") != "170":
                raise RuntimeError(f"Three delivery parts did not total 170: {values.get('xl')}")
            if v23._delivery_parts(values, "xl") != ["50", "70", "50"]:
                raise RuntimeError("Three delivery part values were not preserved")
            if v23._delivery_parts({"xl": "170"}, "xl") != ["170", "", ""]:
                raise RuntimeError("Legacy single delivery did not map safely into box 1")

            block = MaterialReportBlock.objects.create(
                date=date.today(),
                title="V106 ROLLBACK DELIVERY",
                brand=brand,
                input_data=v23._blank_input_data(),
                output_data=output,
            )
            if v23._target_qty(block, "black", "xl") != 170:
                raise RuntimeError("Target quantity is not the sum of the three boxes")

            prod = v23._production_objects(block, "black", "xl")
            prod_brand, color, size, destination = prod[0], prod[1], prod[2], prod[3]
            stock_before = int(
                StockBalance.objects.filter(
                    brand=prod_brand,
                    color=color,
                    size=size,
                    location=destination,
                ).values_list("qty", flat=True).first()
                or 0
            )
            result = v23._sync_output(block)
            stock_after = int(
                StockBalance.objects.filter(
                    brand=prod_brand,
                    color=color,
                    size=size,
                    location=destination,
                ).values_list("qty", flat=True).first()
                or 0
            )
            if result["piece_delta"] != 170 or stock_after - stock_before != 170:
                raise RuntimeError("Sync Output did not add the 170 summed pieces to inventory")

            template = (Path(settings.BASE_DIR) / "templates/core/material_report_v36.html").read_text(encoding="utf-8")
            for marker in ("delivery-split", "part.name", "aria-label=\"تحویل نوبت"):
                if marker not in template:
                    raise RuntimeError(f"Three-box delivery UI marker missing: {marker}")

            transaction.set_rollback(True)

        after = _state()
        if before != after:
            raise RuntimeError("V106 rollback regression changed persistent business state")

        self.stdout.write("PERSON ACCOUNTS IN PAYMENT CHOICES = OK")
        self.stdout.write("PERSON PAYMENT DECREASES PERSON BALANCE = OK")
        self.stdout.write("PERSON PAYMENT EDIT REVERSE/REAPPLY = OK")
        self.stdout.write("PERSON PAYMENT REVERSE RESTORES BALANCE = OK")
        self.stdout.write("THREE DELIVERY BOXES 50+70+50 = 170 = OK")
        self.stdout.write("LEGACY SINGLE DELIVERY -> BOX 1 = OK")
        self.stdout.write("SYNC OUTPUT USES SUM AND ADDS INVENTORY = OK")
        self.stdout.write("NO PERSISTENT BUSINESS STATE WRITE = OK")
        self.stdout.write(self.style.SUCCESS("SUCCESS: PERSON PAYMENTS + THREE DELIVERIES V106 CHECK PASSED"))
