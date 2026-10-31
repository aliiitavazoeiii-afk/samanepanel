import json
from decimal import Decimal, ROUND_HALF_UP

from .material_flow import COLOR_LABELS, ELASTIC, FABRIC, WAREHOUSE, add_warehouse_stock, q
from .material_payment_colors_v124 import payment_material_label

PREFIX = "[mp13]"


def _money(value):
    try:
        return max(0, int(str(value or 0).replace("٬", "").replace(",", "").replace(" ", "")))
    except Exception:
        return 0


def _round(value):
    return int(Decimal(value or 0).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _label(material_key):
    # V124: the exact same permitted options as the rendered payment form.
    # Historic material keys remain valid; dynamic 'color:<id>' must match
    # an actual active Darma inventory color to prevent orphan purchase stock.
    return payment_material_label(material_key)


def _posted_material_key(payee, post):
    # Some historical/payment templates contain one material_key select for
    # fabric and another for elastic inside the same form. QueryDict.get()
    # returns the last one, which can silently pick the hidden field. Choose
    # the field by material type instead: fabric is first, elastic is last.
    values = post.getlist("material_key") if hasattr(post, "getlist") else []
    values = [str(v or "").strip() for v in values if str(v or "").strip()]
    if values:
        return values[0] if payee == "fabric" else values[-1]
    return (post.get("material_key") or "").strip()


def build_purchase_from_post(payee, post):
    material_key = _posted_material_key(payee, post)
    title = _label(material_key)
    user_note = (post.get("note") or "").strip()[:70]

    if payee == "fabric":
        qty = q(post.get("fabric_qty"))
        price = _money(post.get("fabric_price"))
        if qty <= 0:
            raise ValueError("وزن پارچه باید بیشتر از صفر باشد.")
        if price <= 0:
            raise ValueError("فی هر کیلو پارچه باید بیشتر از صفر باشد.")
        fabric_name = (post.get("fabric_name") or "").strip()[:50]
        stock_title = fabric_name or title
        amount = _round(qty * Decimal(price))
        data = {
            "k": "fabric",
            "m": material_key,
            "t": stock_title,
            "q": str(qty),
            "p": price,
            "n": user_note,
        }
        return amount, data

    if payee == "elastic":
        qty16 = max(q(post.get("elastic16_qty")), Decimal("0"))
        qty25 = max(q(post.get("elastic25_qty")), Decimal("0"))
        price16 = _money(post.get("elastic16_price"))
        price25 = _money(post.get("elastic25_price"))
        if qty16 <= 0 and qty25 <= 0:
            raise ValueError("حداقل وزن کش 16 یا کش 25 را وارد کن.")
        if qty16 > 0 and price16 <= 0:
            raise ValueError("فی کش 16 را وارد کن.")
        if qty25 > 0 and price25 <= 0:
            raise ValueError("فی کش 25 را وارد کن.")
        amount = _round(qty16 * Decimal(price16) + qty25 * Decimal(price25))
        data = {
            "k": "elastic",
            "m": material_key,
            "t": title,
            "q16": str(qty16),
            "p16": price16,
            "q25": str(qty25),
            "p25": price25,
            "n": user_note,
        }
        return amount, data

    raise ValueError("این پرداخت خرید مواد اولیه نیست.")


def encode_purchase_note(data):
    text = PREFIX + json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    if len(text) > 250:
        data = dict(data)
        data["n"] = ""
        text = PREFIX + json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return text[:250]


def parse_purchase_note(note):
    text = str(note or "")
    if not text.startswith(PREFIX):
        return None
    try:
        return json.loads(text[len(PREFIX):])
    except Exception:
        return None


def apply_purchase_stock(payment, data):
    kind = data.get("k")
    material_key = data.get("m") or ""
    title = data.get("t") or _label(material_key)
    stock_note = f"خرید از پرداخت #{payment.id}"

    if kind == "fabric":
        return [
            add_warehouse_stock(
                kind=FABRIC,
                material_key=material_key,
                title=title,
                quantity=data.get("q"),
                unit_price=int(data.get("p") or 0),
                unit="کیلو",
                note=stock_note,
                location=WAREHOUSE,
            )
        ]

    if kind == "elastic":
        rows = []
        qty16 = q(data.get("q16"))
        qty25 = q(data.get("q25"))
        if qty16 > 0:
            rows.append(
                add_warehouse_stock(
                    kind=ELASTIC,
                    material_key=material_key,
                    title=title,
                    quantity=qty16,
                    unit_price=int(data.get("p16") or 0),
                    variant="16",
                    unit="کیلو",
                    note=stock_note,
                    location=WAREHOUSE,
                )
            )
        if qty25 > 0:
            rows.append(
                add_warehouse_stock(
                    kind=ELASTIC,
                    material_key=material_key,
                    title=title,
                    quantity=qty25,
                    unit_price=int(data.get("p25") or 0),
                    variant="25",
                    unit="کیلو",
                    note=stock_note,
                    location=WAREHOUSE,
                )
            )
        return rows

    raise ValueError("نوع خرید مواد اولیه معتبر نیست.")


def purchase_summary(data):
    if not data:
        return ""
    title = data.get("t") or COLOR_LABELS.get(data.get("m"), "")
    if data.get("k") == "fabric":
        return f"{title} · {data.get('q', '0')} کیلو × {int(data.get('p') or 0):,}"
    if data.get("k") == "elastic":
        parts = []
        if q(data.get("q16")) > 0:
            parts.append(f"16: {data.get('q16')} کیلو × {int(data.get('p16') or 0):,}")
        if q(data.get("q25")) > 0:
            parts.append(f"25: {data.get('q25')} کیلو × {int(data.get('p25') or 0):,}")
        return f"{title} · " + " | ".join(parts)
    return ""
