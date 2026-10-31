from decimal import Decimal

from django.db import transaction

from .material_flow import COLOR_LABELS, ELASTIC, FABRIC, _consume_rows, q
from .models import MaterialReportConsumption


def desired_consumption(block):
    """Desired raw-material consumption for the block, independent of finished receipts.

    Consumption is posted only when the user explicitly presses the material-apply button.
    Existing MaterialReportConsumption rows make re-apply idempotent/delta-based.
    """
    desired = {}
    for key in COLOR_LABELS:
        values = (block.input_data or {}).get(key, {}) or {}
        fabric = max(q(values.get("weight")), Decimal("0"))
        if fabric:
            desired[(FABRIC, key, "")] = fabric

        delivered16 = q(values.get("elastic16"))
        delivered25 = q(values.get("elastic25"))
        remain16_raw = values.get("remain16")
        remain25_raw = values.get("remain25")
        used16 = delivered16 - q(remain16_raw) if remain16_raw not in (None, "") else delivered16
        used25 = delivered25 - q(remain25_raw) if remain25_raw not in (None, "") else delivered25
        used16 = max(used16, Decimal("0"))
        used25 = max(used25, Decimal("0"))
        if used16:
            desired[(ELASTIC, key, "16")] = used16
        if used25:
            desired[(ELASTIC, key, "25")] = used25
    return desired


@transaction.atomic
def sync_report_consumption(block):
    desired = desired_consumption(block)
    existing = {
        (row.kind, row.material_key, row.variant): row
        for row in MaterialReportConsumption.objects.select_for_update().filter(block=block)
    }
    for key in set(desired) | set(existing):
        old = q(existing[key].quantity) if key in existing else Decimal("0")
        new = q(desired.get(key, 0))
        _consume_rows(key[0], key[1], key[2], new - old)
        if new == 0:
            if key in existing:
                existing[key].delete()
        elif key in existing:
            existing[key].quantity = new
            existing[key].save(update_fields=["quantity"])
        else:
            MaterialReportConsumption.objects.create(
                block=block, kind=key[0], material_key=key[1], variant=key[2], quantity=new
            )


@transaction.atomic
def reverse_report_consumption(block):
    for row in list(MaterialReportConsumption.objects.select_for_update().filter(block=block)):
        _consume_rows(row.kind, row.material_key, row.variant, -q(row.quantity))
    MaterialReportConsumption.objects.filter(block=block).delete()
