"""Repair historical wrong-sign Pedram wholesale invoices exactly once.

Read-only by default. --apply requires an explicit operator action and backs
up before running in the V121 deploy. No inventory or SaleLine writes.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum

from core.business_tools_v14 import _tailor_row
from core.models import ExcelManualRow, WholesaleInvoice


def pending_repair():
    rows = list(
        WholesaleInvoice.objects.filter(
            customer__is_pedram=True, tailor_deducted_amount__gt=0
        ).order_by("pk")
        .values("id", "total_amount", "tailor_deducted_amount", "customer_id")
    )
    for row in rows:
        if int(row["total_amount"]) != int(row["tailor_deducted_amount"]):
            raise ValueError(
                f"Invoice {row['id']} marked inconsistent: stop to avoid wrong adjustment"
            )
    gross = sum(int(row["total_amount"]) for row in rows)
    return rows, gross


def repair(*, apply=False, expected_gross=None):
    with transaction.atomic():
        # Serialize against new invoice writers that lock Pedram buyer first.
        # Record corrections with the old (positive) 'offset' field, which is
        # then reset to zero, making a second execution a complete no-op.
        customers = list(
            WholesaleInvoice.objects.filter(
                customer__is_pedram=True,
                tailor_deducted_amount__gt=0
            ).values_list("customer_id", flat=True).distinct()
        )
        from core.models import WholesaleCustomer
        list(WholesaleCustomer.objects.select_for_update().filter(pk__in=customers).order_by("pk"))
        old = list(
            WholesaleInvoice.objects.select_for_update()
            .filter(customer__is_pedram=True, tailor_deducted_amount__gt=0)
            .order_by("pk")
        )
        for invoice in old:
            if invoice.total_amount != invoice.tailor_deducted_amount:
                raise ValueError(f"Invoice {invoice.pk} offset mismatch; refused")
        total = sum(int(invoice.total_amount) for invoice in old)
        if expected_gross is not None and total != int(expected_gross):
            raise ValueError(
                f"Expected correction gross {int(expected_gross)}, found {total}; "
                "no financial data was changed"
            )
        tailor = _tailor_row(create=False)
        if total and tailor is None:
            raise ValueError("Shared tailor account missing: refusing financial repair")
        before = int(tailor.amount or 0) if tailor else 0
        after = before + 2 * total
        if apply and old:
            row = ExcelManualRow.objects.select_for_update().get(pk=tailor.pk)
            if int(row.amount or 0) != before:
                raise ValueError("Concurrent tailor change, retry")
            row.amount = after
            row.save(update_fields=["amount", "updated_at"])
            WholesaleInvoice.objects.filter(pk__in=[x.pk for x in old]).update(
                tailor_deducted_amount=0
            )
        return {
            "invoice_ids": [invoice.pk for invoice in old],
            "gross": total,
            "account_before": before,
            "account_after": after,
            "correction": 2 * total,
            "applied": bool(apply),
        }


class Command(BaseCommand):
    help = "Audit or (with --apply) repair previously reversed Pedram wholesale invoices, once."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--expected-gross", type=int, default=None)

    def handle(self, *args, **options):
        try:
            result = repair(
                apply=options["apply"], expected_gross=options["expected_gross"]
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"PEDRAM_REPAIR_INVOICE_IDS={result['invoice_ids']}")
        self.stdout.write(f"PEDRAM_REPAIR_GROSS={result['gross']}")
        self.stdout.write(f"PEDRAM_REPAIR_ADJUSTMENT={result['correction']}")
        self.stdout.write(f"PEDRAM_TAILOR_BEFORE={result['account_before']}")
        self.stdout.write(f"PEDRAM_TAILOR_AFTER={result['account_after']}")
        self.stdout.write(
            self.style.SUCCESS(
                "SUCCESS: PEDRAM REPAIR APPLIED" if result["applied"]
                else "SUCCESS: PEDRAM REPAIR DRY RUN (NO WRITES)"
            )
        )
