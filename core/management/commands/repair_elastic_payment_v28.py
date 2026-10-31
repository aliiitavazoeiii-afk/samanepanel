from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.material_flow import ELASTIC, WAREHOUSE, q
from core.material_purchase_v14 import purchase_data_for_payment
from core.models import BusinessPayment, RawMaterialStock


def _fmt(value):
    value = q(value)
    text = format(value.normalize(), "f") if value else "0"
    return text.rstrip("0").rstrip(".") if "." in text else text


class Command(BaseCommand):
    help = "Guarded repair of one elastic payment aggregate stock; dry-run by default."

    def add_arguments(self, parser):
        parser.add_argument("--payment-id", type=int, required=True)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        payment_id = int(options["payment_id"])
        apply = bool(options["apply"])

        payment = BusinessPayment.objects.filter(id=payment_id, payee="elastic").first()
        if payment is None:
            raise CommandError(f"Elastic payment #{payment_id} not found.")
        data = purchase_data_for_payment(payment)
        if not data or data.get("k") != "elastic":
            raise CommandError(f"Payment #{payment_id} has no elastic purchase ledger.")

        material_key = str(data.get("m") or "")
        title = str(data.get("t") or material_key)
        desired = {
            "16": (q(data.get("q16")), int(data.get("p16") or 0)),
            "25": (q(data.get("q25")), int(data.get("p25") or 0)),
        }
        if not material_key:
            raise CommandError("Elastic purchase has empty material_key.")
        if not any(qty > 0 for qty, _ in desired.values()):
            raise CommandError("Elastic purchase has no positive quantity.")

        self.stdout.write(f"payment_id={payment.id} amount={int(payment.amount or 0)} material_key={material_key!r}")
        self.stdout.write("PURCHASE LEDGER:")
        for variant in ("16", "25"):
            qty, price = desired[variant]
            self.stdout.write(f"  variant={variant} qty={_fmt(qty)} unit_price={price}")

        current = {}
        for variant in ("16", "25"):
            rows = list(RawMaterialStock.objects.filter(
                active=True,
                kind=ELASTIC,
                location=WAREHOUSE,
                material_key=material_key,
                variant=variant,
            ).order_by("id"))
            total_qty = sum((q(row.quantity) for row in rows), Decimal("0"))
            total_value = sum((q(row.quantity) * Decimal(int(row.unit_price or 0)) for row in rows), Decimal("0"))
            current[variant] = (rows, total_qty, total_value)
            self.stdout.write(
                f"CURRENT variant={variant}: qty={_fmt(total_qty)} rows={','.join(str(r.id) for r in rows) or 'NONE'} value={int(total_value)}"
            )

        self.stdout.write("TARGET FOR THIS PAYMENT:")
        for variant in ("16", "25"):
            qty, price = desired[variant]
            self.stdout.write(f"  variant={variant}: qty={_fmt(qty)} value={int(qty * Decimal(price))}")

        if not apply:
            self.stdout.write(self.style.WARNING("DRY RUN ONLY — no data changed. Re-run with --apply to repair stock to this payment ledger."))
            return

        with transaction.atomic():
            payment = BusinessPayment.objects.select_for_update().get(id=payment_id, payee="elastic")
            live_data = purchase_data_for_payment(payment)
            if not live_data or live_data.get("k") != "elastic":
                raise CommandError("Purchase ledger changed; aborting.")
            live_key = str(live_data.get("m") or "")
            if live_key != material_key:
                raise CommandError("Material key changed since dry-run; aborting.")

            for variant in ("16", "25"):
                target_qty = q(live_data.get(f"q{variant}"))
                target_price = int(live_data.get(f"p{variant}") or 0)
                rows = list(RawMaterialStock.objects.select_for_update().filter(
                    active=True,
                    kind=ELASTIC,
                    location=WAREHOUSE,
                    material_key=material_key,
                    variant=variant,
                ).order_by("id"))
                for row in rows:
                    row.delete()
                if target_qty > 0:
                    RawMaterialStock.objects.create(
                        kind=ELASTIC,
                        location=WAREHOUSE,
                        material_key=material_key,
                        variant=variant,
                        title=title,
                        quantity=target_qty,
                        unit_price=target_price,
                        unit="کیلو",
                        note=f"ترمیم موجودی از پرداخت #{payment.id}",
                        active=True,
                    )

        self.stdout.write(self.style.SUCCESS(
            f"SUCCESS: elastic stock for payment #{payment_id} repaired to ledger quantities only; finance/payment unchanged."
        ))
