from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .dateutils import format_jalali, parse_jalali_date
from .excel_views import (
    OUTPUT_MODELS,
    OUTPUT_SIZES,
    RAW_COLORS,
    RAW_FIELDS,
    _blank_input_data,
    _blank_output_data,
    _material_block_view,
    _today_jalali,
)
from .material_receipt_sync import reverse_report_consumption, sync_report_consumption
from .models import MaterialReportBlock


@login_required
def material_report(request):
    if request.method == "POST":
        try:
            block = MaterialReportBlock.objects.create(
                date=parse_jalali_date(request.POST.get("date") or _today_jalali()),
                title=(request.POST.get("title") or "").strip(),
                input_data=_blank_input_data(),
                output_data=_blank_output_data(),
            )
            messages.success(request, "صورت جدید مواد اولیه ساخته شد.")
            return redirect(f"/material-report/#block-{block.id}")
        except Exception as exc:
            messages.error(request, str(exc))
            return redirect("material_report")

    blocks = [_material_block_view(obj) for obj in MaterialReportBlock.objects.all()[:40]]
    return render(
        request,
        "core/material_report.html",
        {
            "blocks": blocks,
            "raw_colors": RAW_COLORS,
            "output_sizes": OUTPUT_SIZES,
            "today_j": _today_jalali(),
        },
    )


@login_required
@require_POST
def material_block_save(request, block_id):
    block = get_object_or_404(MaterialReportBlock, id=block_id)
    try:
        with transaction.atomic():
            block.date = parse_jalali_date(request.POST.get("date") or format_jalali(block.date))
            block.title = (request.POST.get("title") or "").strip()
            try:
                raw_wage = (request.POST.get("delivery_wage") or "0").replace("٬", "").replace(" ", "")
                block.delivery_wage = int(raw_wage or 0)
            except ValueError:
                block.delivery_wage = 0
            block.note = (request.POST.get("note") or "").strip()

            input_data = {}
            for color_key, _ in RAW_COLORS:
                input_data[color_key] = {}
                for field_key, _, _ in RAW_FIELDS:
                    input_data[color_key][field_key] = (request.POST.get(f"in_{color_key}_{field_key}") or "").strip()

            output_data = {}
            for model_key, _ in OUTPUT_MODELS:
                output_data[model_key] = {}
                for size_key, _ in OUTPUT_SIZES:
                    output_data[model_key][size_key] = (request.POST.get(f"out_{model_key}_{size_key}") or "").strip()
                output_data[model_key]["delivery_date"] = (request.POST.get(f"delivery_{model_key}") or "").strip()

            block.input_data = input_data
            block.output_data = output_data
            block.save()
            sync_report_consumption(block)

        if block.stock_consumptions.exists():
            messages.success(request, "گزارش ذخیره شد و مصرف پارچه/کش از موجودی نزد خیاط اعمال شد.")
        else:
            messages.success(request, "گزارش ذخیره شد. تا وقتی محصول تحویلی ثبت نشود، موجودی نزد خیاط کم نمی‌شود.")
    except Exception as exc:
        messages.error(request, f"ذخیره انجام نشد: {exc}")
    return redirect(f"/material-report/#block-{block.id}")


@login_required
@require_POST
def material_block_delete(request, block_id):
    block = get_object_or_404(MaterialReportBlock, id=block_id)
    try:
        with transaction.atomic():
            reverse_report_consumption(block)
            block.delete()
        messages.success(request, "صورت مواد اولیه حذف شد و مصرف ثبت‌شده آن به موجودی نزد خیاط برگشت.")
    except Exception as exc:
        messages.error(request, str(exc))
    return redirect("material_report")
