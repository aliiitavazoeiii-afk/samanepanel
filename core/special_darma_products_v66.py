from __future__ import annotations

from django.db import transaction

from .brand_colors import norm
from .darma_cost_v55 import darma_cost_for
from .darma_pricing import SIZE_NAMES
from .models import Brand, Color, ProductCode, ProductComposition, ProductSize, Size


SPECIAL_DARMA_PRODUCTS = {
    "mass-03": {
        "pack_qty": 10,
        "composition": {"کرم": 10},
        "note": "[special-darma-v66] پک ۱۰تایی کرم ثابت",
    },
    "mass-06": {
        "pack_qty": 10,
        "composition": None,
        "variable_colors": ("سفید", "مشکی", "صورتی", "سرمه ای", "قرمز", "زرد"),
        "note": "[variant-color-v66] پک ۱۰تایی تک‌رنگ؛ رنگ از عنوان دیجی‌کالا",
    },
    "D-WP": {
        "pack_qty": 2,
        "composition": {"سفید": 1, "صورتی": 1},
        "note": "[special-darma-v66] W=سفید P=صورتی",
    },
    "D-WN": {
        "pack_qty": 2,
        "composition": {"سفید": 1, "سرمه ای": 1},
        "note": "[special-darma-v66] W=سفید N=سرمه‌ای",
    },
    "D-WK": {
        "pack_qty": 2,
        "composition": {"سفید": 1, "کرم": 1},
        "note": "[special-darma-v66] W=سفید K=کرم",
    },
    "D-WB": {
        "pack_qty": 2,
        "composition": {"سفید": 1, "مشکی": 1},
        "note": "[special-darma-v66] W=سفید B=مشکی",
    },
    "D-PN": {
        "pack_qty": 2,
        "composition": {"صورتی": 1, "سرمه ای": 1},
        "note": "[special-darma-v66] P=صورتی N=سرمه‌ای",
    },
    "D-KM": {
        "pack_qty": 2,
        "composition": {"مشکی": 1, "کرم": 1},
        "note": "[special-darma-v66] M=مشکی K=کرم",
    },
}

IGNORED_DARMA_TITLE_MODELS = frozenset({"KID-220", "BLK-01", "1111", "s1", "mass-12"})
UNMAPPED_DARMA_TITLE_MODELS = frozenset({"BNR"})


def _color(name: str) -> Color:
    wanted = norm(name)
    for color in Color.objects.filter(active=True).order_by("id"):
        if norm(color.name) == wanted:
            return color
    raise ValueError(f"رنگ فعال دارما برای «{name}» پیدا نشد.")


def is_special_darma_product_code(code: str) -> bool:
    return str(code or "") in SPECIAL_DARMA_PRODUCTS


def variable_color_codes() -> frozenset[str]:
    return frozenset(
        code for code, spec in SPECIAL_DARMA_PRODUCTS.items()
        if spec.get("composition") is None
    )


def variable_color_pack_qty(code: str) -> int | None:
    spec = SPECIAL_DARMA_PRODUCTS.get(str(code or ""))
    if not spec or spec.get("composition") is not None:
        return None
    return int(spec["pack_qty"])


def variable_color_names(code: str) -> tuple[str, ...]:
    spec = SPECIAL_DARMA_PRODUCTS.get(str(code or ""))
    if not spec or spec.get("composition") is not None:
        return ()
    return tuple(spec.get("variable_colors") or ())


@transaction.atomic
def sync_special_darma_products():
    brand = Brand.objects.get(name="دارما")
    sizes = {row.name: row for row in Size.objects.filter(name__in=SIZE_NAMES)}
    current_cost = int(darma_cost_for())
    summary = []

    for code, spec in SPECIAL_DARMA_PRODUCTS.items():
        pack_qty = int(spec["pack_qty"])
        product, created = ProductCode.objects.get_or_create(
            brand=brand,
            code=code,
            defaults={
                "pack_qty": pack_qty,
                "active": True,
                "note": str(spec.get("note") or ""),
            },
        )
        product.pack_qty = pack_qty
        product.active = True
        product.note = str(spec.get("note") or "")
        product.save(update_fields=["pack_qty", "active", "note"])

        ProductComposition.objects.filter(product=product).delete()
        composition = spec.get("composition")
        if composition is not None:
            for color_name, qty in composition.items():
                ProductComposition.objects.create(
                    product=product,
                    color=_color(color_name),
                    qty=int(qty),
                )

        size_rows = 0
        for size_name in SIZE_NAMES:
            size = sizes.get(size_name)
            if size is None:
                continue
            ps, ps_created = ProductSize.objects.get_or_create(
                product=product,
                size=size,
                defaults={
                    "default_sale_price": 0,
                    "unit_cost": current_cost,
                    "active": True,
                },
            )
            update_fields = []
            if not ps.active:
                ps.active = True
                update_fields.append("active")
            if int(ps.unit_cost or 0) != current_cost:
                ps.unit_cost = current_cost
                update_fields.append("unit_cost")
            if update_fields:
                ps.save(update_fields=update_fields)
            size_rows += 1

        summary.append(
            {
                "code": code,
                "created": created,
                "pack_qty": pack_qty,
                "variable": composition is None,
                "sizes": size_rows,
            }
        )

    return summary
