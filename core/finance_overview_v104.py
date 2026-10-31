"""Shared read-only Finance overview KPI sources for V104.

These are the exact six balances already shown on Payments. Keeping them here
prevents the Finance hub and Payments page from drifting apart.
"""
from . import business_tools_v21 as v21
from .dia_gallery_v45 import dia_gallery_receivable_total
from .finance_excel_v9 import digikala_receivable_total
from .models import ExcelManualSetting
from .payment_source_v63 import SOURCE_MOFID, source_balance


def finance_kpis():
    debt = ExcelManualSetting.objects.filter(key="takvin_debt").values_list("value", flat=True).first()
    return {
        "mellat_balance": int(v21.mellat_balance() or 0),
        "mofid_balance": int(source_balance(SOURCE_MOFID) or 0),
        "digikala_receivable": int(digikala_receivable_total() or 0),
        "dia_gallery_receivable": int(dia_gallery_receivable_total() or 0),
        "tailor_balance": int(v21.tailor_balance() or 0),
        "takvin_debt": int(debt or 0),
    }
