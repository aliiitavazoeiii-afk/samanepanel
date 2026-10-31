from datetime import date
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.template.loader import get_template

from core import business_receipts_v64 as receipts
from core import business_tools_v21 as v21
from core.dia_gallery_v45 import _dia_account, dia_gallery_receivable_total
from core.finance_excel_v9 import digikala_receivable_total
from core.models import AccountEntry, DigikalaSettlement
from core.payment_source_v63 import SOURCE_MOFID, source_balance


class Command(BaseCommand):
    help = "V64 regression: Digikala/Dia receipts always credit Mellat and debit only their own receivable."

    def handle(self, *args, **options):
        try:
            get_template("core/payments_v62.html")
        except Exception as exc:
            raise CommandError(f"V64 payments template failed to compile: {exc}") from exc

        source_checks = {
            "core/models_final.py": (
                'SOURCE_DIGIKALA = "digikala"',
                'SOURCE_DIA_GALLERY = "dia_gallery"',
                'source = models.CharField',
            ),
            "core/business_receipts_v64.py": (
                "SOURCE_DIA_GALLERY",
                "apply_receipt",
                "reverse_receipt",
                "موجودی ملت",
            ),
            "templates/core/payments_v22.html": (
                'name="source"',
                "Dia Gallery",
                "واریز به",
            ),
            "core/static/core/payments_source_v63.js": (
                "پرداخت از",
                ">ملت<",
                ">مفید<",
            ),
            "core/urls.py": (
                "business_receipts_v64.receipt_add",
                "business_receipts_v64.receipt_update",
                "business_receipts_v64.receipt_delete",
            ),
        }
        for relative, markers in source_checks.items():
            text = (Path(settings.BASE_DIR) / relative).read_text(encoding="utf-8")
            for marker in markers:
                if marker not in text:
                    raise CommandError(f"V64 source marker missing: {relative}: {marker}")

        field = DigikalaSettlement._meta.get_field("source")
        if field.default != receipts.SOURCE_DIGIKALA:
            raise CommandError("V64 historical receipts no longer default to Digikala")
        choices = dict(field.choices)
        if set(choices) != {receipts.SOURCE_DIGIKALA, receipts.SOURCE_DIA_GALLERY}:
            raise CommandError(f"V64 receipt sources are not exactly Digikala/Dia: {choices}")

        count_before = DigikalaSettlement.objects.count()
        mellat_before_outer = int(v21.mellat_balance())
        mofid_before_outer = int(source_balance(SOURCE_MOFID))
        digi_before_outer = int(digikala_receivable_total())
        dia_before_outer = int(dia_gallery_receivable_total())

        with transaction.atomic():
            # Seed temporary receivables inside rollback scope.
            digi_account = v21._digikala_account()
            dia_account = _dia_account(create=True)
            seed = 9_000_000
            AccountEntry.objects.create(
                date=date.today(),
                account=digi_account,
                delta=seed,
                title="[v64] temporary Digikala receivable",
                reference="v64-regression:digikala-seed",
                entry_type="v64_regression",
            )
            AccountEntry.objects.create(
                date=date.today(),
                account=dia_account,
                delta=seed,
                title="[v64] temporary Dia receivable",
                reference="v64-regression:dia-seed",
                entry_type="v64_regression",
            )

            # Digikala receipt: only Digikala receivable goes down, Mellat goes up, Mofid untouched.
            amount_digi = 1_234_000
            m0 = int(v21.mellat_balance())
            f0 = int(source_balance(SOURCE_MOFID))
            d0 = int(digikala_receivable_total())
            g0 = int(dia_gallery_receivable_total())
            r1 = DigikalaSettlement.objects.create(
                source=receipts.SOURCE_DIGIKALA,
                date=date.today(),
                amount=amount_digi,
                note="v64 digikala regression",
            )
            receipts.apply_receipt(r1)
            if int(v21.mellat_balance()) != m0 + amount_digi:
                raise CommandError("V64 Digikala receipt did not increase Mellat exactly")
            if int(source_balance(SOURCE_MOFID)) != f0:
                raise CommandError("V64 Digikala receipt changed Mofid")
            if int(digikala_receivable_total()) != d0 - amount_digi:
                raise CommandError("V64 Digikala receipt did not reduce Digikala receivable exactly")
            if int(dia_gallery_receivable_total()) != g0:
                raise CommandError("V64 Digikala receipt changed Dia receivable")
            receipts.reverse_receipt(r1)
            if int(v21.mellat_balance()) != m0 or int(digikala_receivable_total()) != d0:
                raise CommandError("V64 Digikala receipt reverse did not restore both sides")
            r1.delete()

            # Dia receipt: only Dia receivable goes down, Mellat goes up, Mofid untouched.
            amount_dia = 2_345_000
            m1 = int(v21.mellat_balance())
            f1 = int(source_balance(SOURCE_MOFID))
            d1 = int(digikala_receivable_total())
            g1 = int(dia_gallery_receivable_total())
            r2 = DigikalaSettlement.objects.create(
                source=receipts.SOURCE_DIA_GALLERY,
                date=date.today(),
                amount=amount_dia,
                note="v64 dia regression",
            )
            receipts.apply_receipt(r2)
            if int(v21.mellat_balance()) != m1 + amount_dia:
                raise CommandError("V64 Dia receipt did not increase Mellat exactly")
            if int(source_balance(SOURCE_MOFID)) != f1:
                raise CommandError("V64 Dia receipt changed Mofid")
            if int(dia_gallery_receivable_total()) != g1 - amount_dia:
                raise CommandError("V64 Dia receipt did not reduce Dia receivable exactly")
            if int(digikala_receivable_total()) != d1:
                raise CommandError("V64 Dia receipt changed Digikala receivable")
            receipts.reverse_receipt(r2)
            if int(v21.mellat_balance()) != m1 or int(dia_gallery_receivable_total()) != g1:
                raise CommandError("V64 Dia receipt reverse did not restore both sides")
            r2.delete()

            transaction.set_rollback(True)

        if DigikalaSettlement.objects.count() != count_before:
            raise CommandError("V64 regression left receipt rows changed")
        if int(v21.mellat_balance()) != mellat_before_outer:
            raise CommandError("V64 regression left Mellat changed")
        if int(source_balance(SOURCE_MOFID)) != mofid_before_outer:
            raise CommandError("V64 regression left Mofid changed")
        if int(digikala_receivable_total()) != digi_before_outer:
            raise CommandError("V64 regression left Digikala receivable changed")
        if int(dia_gallery_receivable_total()) != dia_before_outer:
            raise CommandError("V64 regression left Dia receivable changed")

        self.stdout.write("RECEIPT SOURCES: Digikala / Dia Gallery only")
        self.stdout.write("DIGIKALA RECEIPT: Digikala receivable decreases; Mellat increases; Mofid unchanged")
        self.stdout.write("DIA RECEIPT: Dia receivable decreases; Mellat increases; Mofid unchanged")
        self.stdout.write("PAYMENT SOURCE UI: Mellat / Mofid remains V63")
        self.stdout.write("NO TEST DATA CHANGED")
        self.stdout.write(self.style.SUCCESS("SUCCESS: MULTI RECEIPTS V64 CHECK PASSED"))
