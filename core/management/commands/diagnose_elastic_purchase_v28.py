from collections import defaultdict
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError

from core.material_flow import ELASTIC, WAREHOUSE, q
from core.material_purchase_v14 import ledger_for_payment, purchase_data_for_payment
from core.models import BusinessPayment, RawMaterialStock


def _fmt_qty(value):
    value = q(value)
    text = format(value.normalize(), "f") if value else "0"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _signature(payment, data):
    return (
        payment.date.isoformat(),
        payment.payee,
        int(payment.amount or 0),
        str(data.get("m") or ""),
        str(data.get("q16") or "0"),
        int(data.get("p16") or 0),
        str(data.get("q25") or "0"),
        int(data.get("p25") or 0),
    )


class Command(BaseCommand):
    help = "Read-only audit of latest elastic payment, purchase ledger, and warehouse elastic stock."

    def add_arguments(self, parser):
        parser.add_argument("--payment-id", type=int, default=0)
        parser.add_argument("--limit", type=int, default=12)

    def handle(self, *args, **options):
        payment_id = int(options.get("payment_id") or 0)
        limit = max(1, min(int(options.get("limit") or 12), 50))

        candidates = []
        qs = BusinessPayment.objects.filter(payee="elastic").order_by("-created_at", "-id")
        if payment_id:
            qs = qs.filter(id=payment_id)

        for payment in qs[:limit]:
            data = purchase_data_for_payment(payment)
            if data and data.get("k") == "elastic":
                candidates.append((payment, data))

        if not candidates:
            raise CommandError("No elastic material purchase payment found.")

        latest, latest_data = candidates[0]
        material_key = str(latest_data.get("m") or "")

        self.stdout.write("=== LATEST ELASTIC PURCHASE ===")
        self.stdout.write(
            f"payment_id={latest.id} created_at={latest.created_at.isoformat()} date={latest.date} "
            f"amount={int(latest.amount or 0)} material_key={material_key!r}"
        )
        self.stdout.write(
            f"ledger q16={_fmt_qty(latest_data.get('q16'))} p16={int(latest_data.get('p16') or 0)} "
            f"q25={_fmt_qty(latest_data.get('q25'))} p25={int(latest_data.get('p25') or 0)}"
        )
        ledger = ledger_for_payment(latest)
        self.stdout.write(f"purchase_ledger={'YES' if ledger else 'NO'}")

        self.stdout.write("\n=== CURRENT WAREHOUSE STOCK FOR SAME COLOR ===")
        totals = defaultdict(lambda: {"qty": Decimal("0"), "value": Decimal("0"), "rows": 0})
        rows = RawMaterialStock.objects.filter(
            active=True,
            kind=ELASTIC,
            location=WAREHOUSE,
            material_key=material_key,
        ).order_by("variant", "id")
        for row in rows:
            variant = str(row.variant or "")
            qty = q(row.quantity)
            totals[variant]["qty"] += qty
            totals[variant]["value"] += qty * Decimal(int(row.unit_price or 0))
            totals[variant]["rows"] += 1
            self.stdout.write(
                f"row_id={row.id} variant={variant!r} qty={_fmt_qty(qty)} "
                f"unit_price={int(row.unit_price or 0)} note={row.note!r}"
            )
        for variant in ("16", "25"):
            cell = totals[variant]
            self.stdout.write(
                f"TOTAL variant={variant}: qty={_fmt_qty(cell['qty'])} rows={cell['rows']} "
                f"value={int(cell['value'])}"
            )

        self.stdout.write("\n=== RECENT ELASTIC PURCHASES ===")
        signature_groups = defaultdict(list)
        for payment, data in candidates:
            signature_groups[_signature(payment, data)].append(payment)
            self.stdout.write(
                f"payment_id={payment.id} created_at={payment.created_at.isoformat()} amount={int(payment.amount or 0)} "
                f"key={data.get('m')!r} q16={_fmt_qty(data.get('q16'))} q25={_fmt_qty(data.get('q25'))}"
            )

        duplicate_groups = [items for items in signature_groups.values() if len(items) > 1]
        self.stdout.write("\n=== DUPLICATE CANDIDATES ===")
        if not duplicate_groups:
            self.stdout.write("NONE")
        else:
            for items in duplicate_groups:
                ids = ",".join(str(p.id) for p in items)
                times = ",".join(p.created_at.isoformat() for p in items)
                self.stdout.write(f"same purchase payload: payment_ids={ids} created_at={times}")

        expected16 = q(latest_data.get("q16"))
        expected25 = q(latest_data.get("q25"))
        self.stdout.write("\n=== INTERPRETATION ===")
        self.stdout.write(
            f"latest purchase itself adds only: elastic16={_fmt_qty(expected16)} kg, "
            f"elastic25={_fmt_qty(expected25)} kg"
        )
        if duplicate_groups:
            self.stdout.write(self.style.WARNING(
                "Duplicate payment payload(s) exist. Do not manually halve stock before duplicate finance/stock effects are reversed together."
            ))
        else:
            self.stdout.write(
                "No identical recent BusinessPayment duplicate found. If stock is higher than expected, it may include prior stock or another purchase/transfer history."
            )

        self.stdout.write(self.style.SUCCESS("ELASTIC PURCHASE V28 DIAGNOSTIC OK (READ ONLY)"))
