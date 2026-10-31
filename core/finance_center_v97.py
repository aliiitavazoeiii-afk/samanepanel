from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .capital_history_v87 import current_account_breakdown
from .finance_excel_v9 import digikala_ledger_total, digikala_receivable_total
from .finance_overview_v104 import finance_kpis
from .models import BusinessPayment, ExcelManualRow, ExcelManualSetting
from .report_v10 import manual_report_action as report_manual_report_action
from .business_tools_v62 import person_payee_key


def _finance_account_context():
    """Canonical context for the dedicated Finance/Accounts page.

    It reads the exact ExcelManualRow / ExcelManualSetting sources historically
    used by the comprehensive report. No account data is copied or migrated.
    """
    manual_rows = ExcelManualRow.objects.filter(active=True)
    accounts_rows = list(
        manual_rows.filter(section=ExcelManualRow.ACCOUNTS).order_by("sort_order", "id")
    )
    person_rows = list(
        manual_rows.filter(section=ExcelManualRow.PERSONS).order_by("sort_order", "id")
    )
    settings = {obj.key: obj for obj in ExcelManualSetting.objects.all()}
    takvin_debt = int(settings.get("takvin_debt").value or 0) if settings.get("takvin_debt") else 0
    digikala_base = (
        int(settings.get("digikala_receivable").value or 0)
        if settings.get("digikala_receivable")
        else 0
    )
    digikala_ledger = int(digikala_ledger_total())
    digikala_receivable = int(digikala_receivable_total())

    account_breakdown = current_account_breakdown()
    accounts_total = int(account_breakdown["accounts_total"])
    dia_gallery_receivable = int(account_breakdown["dia_gallery_receivable"])

    return {
        "accounts_rows": accounts_rows,
        "person_rows": person_rows,
        "accounts_total": accounts_total,
        "takvin_debt": takvin_debt,
        "digikala_receivable": digikala_receivable,
        "digikala_base_receivable": digikala_base,
        "digikala_ledger_total": digikala_ledger,
        "dia_gallery_receivable": dia_gallery_receivable,
    }


@login_required
def finance_home(request):
    # V104: the hub keeps exactly three navigation cards and shows the same six
    # read-only balances as Payments above them, from one shared source.
    return render(request, "core/finance_center_v97.html", finance_kpis())


@login_required
def accounts(request):
    return render(request, "core/finance_accounts_v97.html", _finance_account_context())


@login_required
@require_POST
def accounts_action(request):
    if request.POST.get("action") == "delete_row":
        row = ExcelManualRow.objects.filter(id=request.POST.get("id")).first()
        if (
            row
            and row.section == ExcelManualRow.PERSONS
            and BusinessPayment.objects.filter(payee=person_payee_key(row.id)).exists()
        ):
            messages.error(
                request,
                "این حساب شخص در سابقه پرداخت‌ها استفاده شده و برای حفظ امکان ویرایش/حذف پرداخت قابل حذف نیست.",
            )
            return redirect("finance_accounts")

    # Reuse the exact report-side account mutation semantics, including:
    # - Digikala desired-total -> base conversion
    # - protected system-managed «خودم» row
    # - generic manual account/person row validation
    # Only the post-save redirect changes to the new Finance/Accounts page.
    report_manual_report_action(request)
    return redirect("finance_accounts")
