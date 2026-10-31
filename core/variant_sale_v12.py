from collections import defaultdict

from django.db import transaction
from django.db.models import Sum

from .brand_colors import norm
from .darma_pricing import SIZE_NAMES, get_group_prices
from .special_darma_products_v66 import variable_color_codes, variable_color_names, variable_color_pack_qty
from .models import (
    AppSetting, Brand, Color, InventoryMovement, ProductCode, ProductSize,
    SaleAllocation, SaleLine, SaleShortage, Size, StockBalance, StockLocation,
)

VARIANT_PRODUCT_CODE = "s3"
VARIABLE_COLOR_PRODUCT_CODES = frozenset({VARIANT_PRODUCT_CODE}) | variable_color_codes()

# Exact Digikala seller-code semantics from the user's daily-order workflow.
# These are intentionally case-sensitive: s3=black, S3=pink.
SELLER_COLOR_CODES = {
    "s2": "کرم",
    "s3": "مشکی",
    "S3": "صورتی",
    "s5": "سرمه ای",
}

# Title is authoritative for variable-color s3. White has no confirmed seller-code
# alias yet, but it is fully supported whenever the Digikala title says سفید.
TITLE_COLORS = ["مشکی", "کرم", "صورتی", "سرمه ای", "سفید"]
MASS06_TITLE_COLOR_ALIASES = {"کالباسی": "صورتی"}


def _color_for_name(name):
    wanted = norm(name)
    for color in Color.objects.filter(active=True).order_by("id"):
        if norm(color.name) == wanted:
            return color
    raise ValueError(f"رنگ دارما «{name}» در موجودی تعریف نشده است.")


def _title_color_token(title, allowed_colors, aliases=None):
    aliases = aliases or {}
    parts = [part.strip() for part in str(title or "").split("|")]
    for part in parts:
        normalized = norm(part)
        for alias, canonical in aliases.items():
            if normalized == norm(alias):
                return canonical
        for color_name in allowed_colors:
            if normalized == norm(color_name):
                return color_name
    return None


def resolve_variant_color(title, seller_code=""):
    # Backward-compatible s3 resolver. Title stays authoritative.
    title_color = _title_color_token(title, TITLE_COLORS)
    if title_color:
        return title_color
    raw_code = str(seller_code or "").strip()
    return SELLER_COLOR_CODES.get(raw_code)


def is_variable_color_product_code(code):
    return str(code or "") in VARIABLE_COLOR_PRODUCT_CODES


def resolve_variable_product_color(product_code, title):
    code = str(product_code or "")
    if code == VARIANT_PRODUCT_CODE:
        return resolve_variant_color(title, "")
    allowed = variable_color_names(code)
    if not allowed:
        return None
    aliases = MASS06_TITLE_COLOR_ALIASES if code == "mass-06" else {}
    return _title_color_token(title, allowed, aliases=aliases)


@transaction.atomic
def ensure_variant_product():
    brand = Brand.objects.get(name="دارما")
    product, _ = ProductCode.objects.get_or_create(
        brand=brand,
        code=VARIANT_PRODUCT_CODE,
        defaults={"pack_qty": 1, "active": True, "note": "[variant-color]"},
    )
    product.pack_qty = 1
    product.active = True
    product.note = "[variant-color] رنگ هر فروش از عنوان فایل دیجی‌کالا"
    product.save(update_fields=["pack_qty", "active", "note"])
    # Fixed composition must stay empty for this product.
    product.composition.all().delete()

    prices = get_group_prices(1)
    sizes = {s.name: s for s in Size.objects.filter(name__in=SIZE_NAMES)}
    for size_name in SIZE_NAMES:
        size = sizes.get(size_name)
        if not size:
            continue
        ProductSize.objects.update_or_create(
            product=product,
            size=size,
            defaults={
                "default_sale_price": int(prices.get(size_name, 0) or 0),
                "unit_cost": 61000,
                "active": True,
            },
        )
    return product


def _stock_total_by_brand():
    return {
        row["brand_id"]: int(row["qty"] or 0)
        for row in StockBalance.objects.values("brand_id").annotate(qty=Sum("qty"))
    }


def sold_units_by_brand(lines):
    result = defaultdict(int)
    for line in lines:
        result[line.product_size.product.brand_id] += int(line.quantity or 0) * int(line.product_size.product.pack_qty or 0)
    return dict(result)


def assert_stock_invariant(before_stock, after_stock, old_sold, new_sold):
    brand_ids = set(before_stock) | set(after_stock) | set(old_sold) | set(new_sold)
    errors = []
    for brand_id in brand_ids:
        actual_decrease = int(before_stock.get(brand_id, 0)) - int(after_stock.get(brand_id, 0))
        expected_decrease = int(new_sold.get(brand_id, 0)) - int(old_sold.get(brand_id, 0))
        if actual_decrease != expected_decrease:
            brand_name = Brand.objects.filter(id=brand_id).values_list("name", flat=True).first() or str(brand_id)
            errors.append(
                f"{brand_name}: تغییر واقعی موجودی {actual_decrease:+d} ولی تغییر مورد انتظار فروش {expected_decrease:+d}"
            )
    if errors:
        raise ValueError("کنترل موجودی فروش ناموفق بود؛ کل Import برگشت داده شد. " + " | ".join(errors))


@transaction.atomic
def sync_variant_inventory(line, color_quantities):
    line = (
        SaleLine.objects.select_for_update()
        .select_related("product_size__product__brand", "product_size__size")
        .get(pk=line.pk)
    )
    product = line.product_size.product
    if product.brand.name != "دارما" or not is_variable_color_product_code(product.code):
        raise ValueError("این تابع فقط برای محصولات دارما با رنگ متغیر از عنوان است.")

    brand = product.brand
    size = line.product_size.size
    home = StockLocation.objects.get(key=StockLocation.HOME)
    ref = f"sale:{line.id}"

    # Return the previous allocation first; this makes re-upload idempotent.
    for alloc in list(line.allocations.select_related("color", "location").all()):
        bal, _ = StockBalance.objects.get_or_create(
            brand=brand, size=size, color=alloc.color, location=alloc.location, defaults={"qty": 0}
        )
        bal = StockBalance.objects.select_for_update().get(pk=bal.pk)
        bal.qty += int(alloc.qty)
        bal.save(update_fields=["qty"])
        InventoryMovement.objects.create(
            movement_type=InventoryMovement.ADJUST,
            brand=brand, size=size, color=alloc.color, location=alloc.location,
            delta=int(alloc.qty), reference=f"{ref}:variant-recalc",
        )
    line.allocations.all().delete()
    line.shortages.all().delete()

    desired_total = sum(int(qty or 0) for qty in color_quantities.values())
    if desired_total != int(line.quantity or 0):
        raise ValueError(
            f"جمع پک‌های رنگی {product.code} ({desired_total}) با تعداد فروش ({int(line.quantity or 0)}) برابر نیست."
        )
    pack_qty = int(product.pack_qty or variable_color_pack_qty(product.code) or 1)
    if line.quantity <= 0:
        line.inventory_applied_quantity = 0
        line.save(update_fields=["inventory_applied_quantity"])
        return {"shortages": [], "transferred": 0}

    transferred = 0
    shortages = []
    for color_name, qty in color_quantities.items():
        needed = int(qty or 0) * pack_qty
        if needed <= 0:
            continue
        color = _color_for_name(color_name)
        home_row, _ = StockBalance.objects.get_or_create(
            brand=brand, size=size, color=color, location=home, defaults={"qty": 0}
        )
        home_row = StockBalance.objects.select_for_update().get(pk=home_row.pk)

        # V46 business rule: every sale is deducted from HOME only, even below zero.
        # KHORSHID changes only when the user records an explicit physical transfer.
        available = max(0, int(home_row.qty or 0))
        home_row.qty -= needed
        home_row.save(update_fields=["qty"])
        SaleAllocation.objects.create(
            sale_line=line, color=color, location=home, qty=needed, is_replacement=False
        )
        InventoryMovement.objects.create(
            movement_type=InventoryMovement.SALE,
            brand=brand, size=size, color=color, location=home,
            delta=-needed, reference=f"{ref}:variant",
        )
        if available < needed:
            shortage = SaleShortage.objects.create(
                sale_line=line, source_color=color, qty=needed - available, resolved=False
            )
            shortages.append(shortage)

    line.inventory_applied_quantity = line.quantity
    line.save(update_fields=["inventory_applied_quantity"])
    return {"shortages": shortages, "transferred": transferred}