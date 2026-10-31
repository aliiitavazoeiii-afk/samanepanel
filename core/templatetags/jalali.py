from decimal import Decimal, InvalidOperation

from django import template

from core.dateutils import format_jalali

register = template.Library()


@register.filter(name="jalali")
def jalali(value):
    return format_jalali(value)


@register.filter(name="groupnum")
def groupnum(value):
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return value
    sign = "-" if number < 0 else ""
    s = str(abs(number))
    parts = []
    while s:
        parts.append(s[-3:])
        s = s[:-3]
    return sign + "٬".join(reversed(parts))


@register.filter(name="qtynum")
def qtynum(value):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return value
    text = format(number, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


@register.filter(name="absnum")
def absnum(value):
    try:
        return abs(int(value or 0))
    except (TypeError, ValueError):
        return value


@register.filter(name="pct1")
def pct1(value):
    try:
        return f"{float(value):.1f}"
    except (TypeError, ValueError):
        return value


@register.filter(name="ratio_pct")
def ratio_pct(value, denominator):
    try:
        den = float(denominator)
        if den == 0:
            return 0
        return float(value) * 100 / den
    except (TypeError, ValueError, ZeroDivisionError):
        return 0


@register.simple_tag
def material_color_choices():
    from core.brand_colors import darma_material_choices
    return darma_material_choices()
