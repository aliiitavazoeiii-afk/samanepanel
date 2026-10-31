from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from .excel_views import RAW_COLORS, _decimal, _int
from .material_flow import (
    DEPOT,
    WAREHOUSE,
    add_warehouse_stock,
    delete_elastic_group,
    delete_fabric_stock,
    transfer_elastic_to_tailor,
    transfer_fabric_to_tailor,
    update_elastic_group,
    update_fabric_stock,
)
from .models import Color, ExcelManualRow, ExcelManualSetting, RawMaterialStock


LEGACY_LABELS = dict(RAW_COLORS)


def _material_title(key):
    if key in LEGACY_LABELS:
        return LEGACY_LABELS[key]
    if key.startswith("color:"):
        try:
            color_id = int(key.split(":", 1)[1])
        except (TypeError, ValueError):
            color_id = 0
        name = Color.objects.filter(id=color_id, active=True).values_list("name", flat=True).first()
        if name:
            return name
    return key or "نامشخص"


@login_required
@require_POST
def manual_report_action(request):
    action = request.POST.get("action")
    try:
        if action == "setting":
            key = request.POST.get("key")
            labels = {"takvin_debt": "بدهی تکوین", "digikala_receivable": "طلب دیجی‌کالا"}
            if key not in labels:
                raise ValueError("فیلد ناشناخته است.")
            obj, _ = ExcelManualSetting.objects.get_or_create(key=key, defaults={"label": labels[key]})
            obj.value = _int(request.POST.get("value"))
            obj.label = labels[key]
            obj.save(update_fields=["value", "label", "updated_at"])

        elif action in {"save_row", "add_row", "delete_row"}:
            allowed = {ExcelManualRow.ACCOUNTS, ExcelManualRow.PERSONS, ExcelManualRow.ASSETS}
            if action == "save_row":
                row = get_object_or_404(ExcelManualRow, id=request.POST.get("id"), section__in=allowed)
                row.title = (request.POST.get("title") or row.title).strip()
                row.amount = _int(request.POST.get("amount"))
                row.note = (request.POST.get("note") or "").strip()
                row.save()
            elif action == "add_row":
                section = request.POST.get("section")
                if section not in allowed:
                    raise ValueError("این بخش ورود دستی ندارد.")
                order = ExcelManualRow.objects.filter(section=section).aggregate(v=Sum("sort_order"))["v"] or 0
                ExcelManualRow.objects.create(
                    section=section,
                    title=(request.POST.get("title") or "ردیف جدید").strip(),
                    sort_order=order + 1,
                )
            else:
                ExcelManualRow.objects.filter(id=request.POST.get("id"), section__in=allowed).delete()

        elif action == "fabric_add":
            key = request.POST.get("material_key") or ""
            location = request.POST.get("location") or WAREHOUSE
            if location not in {WAREHOUSE, DEPOT}:
                raise ValueError("محل ثبت پارچه معتبر نیست.")
            add_warehouse_stock(
                kind=RawMaterialStock.FABRIC,
                material_key=key,
                title=_material_title(key),
                quantity=request.POST.get("quantity"),
                unit_price=_int(request.POST.get("unit_price")),
                unit="کیلو",
                note=(request.POST.get("note") or "").strip(),
                location=location,
            )

        elif action == "fabric_transfer":
            transfer_fabric_to_tailor(request.POST.get("source_id"), request.POST.get("quantity"))

        elif action == "fabric_update":
            update_fabric_stock(
                request.POST.get("id"),
                quantity=request.POST.get("quantity"),
                unit_price=_int(request.POST.get("unit_price")),
                note=(request.POST.get("note") or "").strip(),
            )

        elif action == "fabric_delete":
            delete_fabric_stock(request.POST.get("id"))

        elif action == "elastic_add":
            key = request.POST.get("material_key") or ""
            if not key:
                raise ValueError("رنگ کش را انتخاب کن.")
            title = _material_title(key)
            qty16 = _decimal(request.POST.get("qty16"))
            qty25 = _decimal(request.POST.get("qty25"))
            if qty16 > 0:
                add_warehouse_stock(
                    kind=RawMaterialStock.ELASTIC, material_key=key, title=title,
                    quantity=qty16, unit_price=_int(request.POST.get("price16")),
                    variant="16", unit="کیلو",
                )
            if qty25 > 0:
                add_warehouse_stock(
                    kind=RawMaterialStock.ELASTIC, material_key=key, title=title,
                    quantity=qty25, unit_price=_int(request.POST.get("price25")),
                    variant="25", unit="کیلو",
                )
            if qty16 <= 0 and qty25 <= 0:
                raise ValueError("مقدار کش 16 یا 25 را وارد کن.")

        elif action == "elastic_transfer":
            key = request.POST.get("material_key") or ""
            if not key:
                raise ValueError("رنگ کش را انتخاب کن.")
            transfer_elastic_to_tailor(
                key, _material_title(key), request.POST.get("qty16"), request.POST.get("qty25")
            )

        elif action == "elastic_update":
            key = request.POST.get("material_key") or ""
            location = request.POST.get("location") or WAREHOUSE
            if not key:
                raise ValueError("رنگ کش معتبر نیست.")
            update_elastic_group(
                location=location,
                material_key=key,
                title=_material_title(key),
                qty16=request.POST.get("qty16"),
                price16=_int(request.POST.get("price16")),
                qty25=request.POST.get("qty25"),
                price25=_int(request.POST.get("price25")),
            )

        elif action == "elastic_delete":
            key = request.POST.get("material_key") or ""
            location = request.POST.get("location") or WAREHOUSE
            if not key:
                raise ValueError("رنگ کش معتبر نیست.")
            delete_elastic_group(location=location, material_key=key, title=_material_title(key))

        else:
            raise ValueError("عملیات نامعتبر است.")

        messages.success(request, "ذخیره شد.")
    except Exception as exc:
        messages.error(request, str(exc))
    return redirect("report")
