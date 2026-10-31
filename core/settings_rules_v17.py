from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .darma_cost_v55 import (
    LEGACY_FALLBACK_KEY,
    RULE_PREFIX as DARMA_RULE_PREFIX,
    apply_darma_cost_rule,
    darma_cost_for,
    delete_darma_cost_rule,
    list_darma_cost_rules,
)
from .dateutils import format_jalali, parse_jalali_date
from .models import AppSetting, TakvinCostRule
from .novani_cost_v59 import (
    RULE_PREFIX as NOVANI_RULE_PREFIX,
    apply_novani_cost_rule,
    delete_novani_cost_rule,
    list_novani_cost_rules,
    novani_cost_for,
)
from .sale_price_v60 import RULE_PREFIX as SALE_PRICE_RULE_PREFIX
from .takvin_pricing_v17 import TAKVIN_SIZES, create_rule_set, current_takvin_costs


def _money(value):
    try:
        return int(str(value or "0").replace("٬", "").replace(",", "").replace(" ", ""))
    except Exception:
        return 0


@login_required
def settings_rules(request):
    # Controlled dated rules have their own UIs. Hide their internal AppSetting
    # rows from the generic raw table so users cannot accidentally bypass those
    # workflows or create a second visible source of truth.
    settings = list(
        AppSetting.objects.exclude(key__startswith=DARMA_RULE_PREFIX)
        .exclude(key__startswith=NOVANI_RULE_PREFIX)
        .exclude(key__startswith=SALE_PRICE_RULE_PREFIX)
        .exclude(key=LEGACY_FALLBACK_KEY)
        .order_by("id")
    )

    if request.method == "POST":
        action = request.POST.get("action", "base_settings")
        try:
            if action == "darma_cost_rule":
                effective_from = parse_jalali_date(request.POST.get("effective_from") or "")
                unit_cost = _money(request.POST.get("darma_unit_cost"))
                _, updated = apply_darma_cost_rule(effective_from, unit_cost)
                messages.success(
                    request,
                    f"بهای تمام‌شده هر شورت دارما از تاریخ {format_jalali(effective_from)} روی {unit_cost:,} تومان ذخیره شد. "
                    f"{updated['sale_snapshots']} Snapshot فروش و {updated['dia_rows']} ردیف Dia از همان تاریخ به بعد با قوانین تاریخ‌دار هماهنگ شدند. "
                    "فروش‌های قبل از تاریخ شروع تغییر نکردند و ارزش موجودی فعلی فقط وقتی آن تاریخ برسد با نرخ جدید محاسبه می‌شود.",
                )
            elif action == "darma_delete_rule":
                effective_from = parse_jalali_date(request.POST.get("effective_from") or "")
                deleted, updated = delete_darma_cost_rule(effective_from)
                if deleted:
                    messages.success(
                        request,
                        f"قانون بهای دارما از تاریخ {format_jalali(effective_from)} حذف شد؛ "
                        f"{updated['sale_snapshots']} Snapshot و {updated['dia_rows']} ردیف Dia با قوانین باقی‌مانده بازتنظیم شدند.",
                    )
                else:
                    messages.info(request, "برای این تاریخ قانون بهای دارما پیدا نشد.")
            elif action == "novani_cost_rule":
                effective_from = parse_jalali_date(request.POST.get("effective_from") or "")
                unit_cost = _money(request.POST.get("novani_unit_cost"))
                _, updated = apply_novani_cost_rule(effective_from, unit_cost)
                messages.success(
                    request,
                    f"بهای تمام‌شده هر شورت Novani از تاریخ {format_jalali(effective_from)} روی {unit_cost:,} تومان ذخیره شد. "
                    f"{updated['sale_snapshots']} Snapshot فروش Novani از همان تاریخ به بعد هماهنگ شد. "
                    "فروش‌های قبل از تاریخ شروع تغییر نکردند و موجودی Novani از روز مؤثرشدن قانون با نرخ جدید ارزش‌گذاری می‌شود.",
                )
            elif action == "novani_delete_rule":
                effective_from = parse_jalali_date(request.POST.get("effective_from") or "")
                deleted, updated = delete_novani_cost_rule(effective_from)
                if deleted:
                    messages.success(
                        request,
                        f"قانون بهای Novani از تاریخ {format_jalali(effective_from)} حذف شد؛ "
                        f"{updated['sale_snapshots']} Snapshot فروش Novani با قوانین باقی‌مانده بازتنظیم شد.",
                    )
                else:
                    messages.info(request, "برای این تاریخ قانون بهای Novani پیدا نشد.")
            elif action == "takvin_cost_rule":
                effective_from = parse_jalali_date(request.POST.get("effective_from") or "")
                prices = {size: _money(request.POST.get(f"takvin_{size}")) for size in TAKVIN_SIZES}
                create_rule_set(effective_from, prices)
                messages.success(
                    request,
                    f"قیمت‌های تکوین از تاریخ {format_jalali(effective_from)} ذخیره شد. فروش‌های قبل از این تاریخ تغییر نمی‌کنند.",
                )
            elif action == "takvin_delete_rule_set":
                effective_from = parse_jalali_date(request.POST.get("effective_from") or "")
                deleted, _ = TakvinCostRule.objects.filter(effective_from=effective_from).delete()
                if deleted:
                    messages.success(request, f"قیمت‌های تکوین از تاریخ {format_jalali(effective_from)} حذف شد.")
                else:
                    messages.info(request, "برای این تاریخ قانونی پیدا نشد.")
            else:
                for item in settings:
                    if f"setting_{item.id}" in request.POST:
                        item.value = (request.POST.get(f"setting_{item.id}") or "").strip()
                        item.save(update_fields=["value", "updated_at"])
                messages.success(request, "تنظیمات محاسباتی ذخیره شد.")
        except Exception as exc:
            messages.error(request, str(exc))
        return redirect("settings_rules")

    current = current_takvin_costs()
    grouped = {}
    for rule in TakvinCostRule.objects.select_related("size").order_by("-effective_from", "size__sort_order"):
        key = rule.effective_from
        grouped.setdefault(key, {"date": rule.effective_from, "jalali": format_jalali(rule.effective_from), "prices": {}})
        grouped[key]["prices"][rule.size.name] = int(rule.unit_cost)

    darma_history = [
        {
            "date": row["effective_from"],
            "jalali": format_jalali(row["effective_from"]),
            "unit_cost": int(row["unit_cost"]),
            "is_baseline": bool(row.get("is_baseline")),
        }
        for row in list_darma_cost_rules()
    ]
    novani_history = [
        {
            "date": row["effective_from"],
            "jalali": format_jalali(row["effective_from"]),
            "unit_cost": int(row["unit_cost"]),
            "is_baseline": bool(row.get("is_baseline")),
        }
        for row in list_novani_cost_rules()
    ]

    history = list(grouped.values())
    return render(
        request,
        "core/settings_rules_v17.html",
        {
            "settings": settings,
            "darma_current": int(darma_cost_for()),
            "darma_history": darma_history,
            "novani_current": int(novani_cost_for()),
            "novani_history": novani_history,
            "takvin_sizes": TAKVIN_SIZES,
            "takvin_current": current,
            "takvin_history": history,
        },
    )
