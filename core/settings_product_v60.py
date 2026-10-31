from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render

from .brand_colors import colors_for_brand
from .dateutils import format_jalali, parse_jalali_date
from .models import Brand, Color, ProductCode, ProductComposition, ProductSize, Size
from .sale_price_v60 import MANAGED_BRANDS, next_sale_price_rule, sale_price_for, set_sale_price_rule
from .special_darma_products_v66 import variable_color_pack_qty
from .takvin_pricing_v17 import takvin_cost_for
from .variant_sale_v12 import is_variable_color_product_code


INVENTORY_COMPOSITION_BRANDS = {"دارما", "تکوین"}
TAKVIN_SIZE_NAMES = {"M", "L", "XL", "XXL"}


def _to_int(value, default=0):
    try:
        if value in (None, ""):
            return int(default or 0)
        return int(str(value).replace("٬", "").replace(",", "").replace(" ", "").strip())
    except (TypeError, ValueError):
        return int(default or 0)


def _default_effective_date():
    return date.today() + timedelta(days=1)


def _inventory_color_ids_for_brand(brand):
    if not brand or brand.name not in INVENTORY_COMPOSITION_BRANDS:
        return set()
    return set(colors_for_brand(brand).values_list("id", flat=True))


@login_required
@transaction.atomic
def settings_product_form(request, product_id=None):
    product = get_object_or_404(ProductCode, id=product_id) if product_id else None
    brands = Brand.objects.filter(active=True)
    colors = list(Color.objects.filter(active=True).order_by("id"))
    sizes = list(Size.objects.all().order_by("sort_order", "id"))
    existing_comp = {}
    existing_sizes = {}
    if product:
        existing_comp = {c.color_id: c.qty for c in product.composition.all()}
        existing_sizes = {
            ps.size_id: ps
            for ps in product.sizes.select_related("size", "product__brand").all()
        }

    form_brand_id = product.brand_id if product else (brands.first().id if brands.exists() else None)
    form_code = product.code if product else ""
    form_title = product.title if product else ""
    form_pack_qty = product.pack_qty if product else 1
    form_note = product.note if product else ""
    form_active = product.active if product else True

    future_dates = []
    if request.method != "POST":
        for ps in existing_sizes.values():
            nxt = next_sale_price_rule(ps)
            if nxt:
                future_dates.append(nxt["effective_from"])
    form_effective = min(future_dates) if future_dates else _default_effective_date()

    if request.method == "POST":
        form_brand_id = _to_int(request.POST.get("brand"))
        form_code = (request.POST.get("code") or "").strip()
        form_title = (request.POST.get("title") or "").strip()
        form_pack_qty = max(1, _to_int(request.POST.get("pack_qty"), 1))
        form_note = (request.POST.get("note") or "").strip()
        form_active = bool(request.POST.get("active"))
        brand = get_object_or_404(Brand, id=form_brand_id)

        errors = []
        try:
            form_effective = parse_jalali_date(
                request.POST.get("sale_price_effective_from")
                or format_jalali(_default_effective_date())
            )
        except ValueError as exc:
            form_effective = _default_effective_date()
            errors.append(str(exc))

        allowed_inventory_color_ids = _inventory_color_ids_for_brand(brand)
        comp = {}
        comp_total = 0
        invalid_colors = []
        for color in colors:
            qty = max(0, _to_int(request.POST.get(f"color_{color.id}")))
            if not qty:
                continue
            if (
                brand.name in INVENTORY_COMPOSITION_BRANDS
                and color.id not in allowed_inventory_color_ids
            ):
                invalid_colors.append(color.name)
                continue
            comp[color.id] = qty
            comp_total += qty

        if invalid_colors:
            errors.append(
                f"این رنگ‌ها در موجودی {brand.name} تعریف نشده‌اند و نمی‌توانند در ترکیب کد باشند: "
                + "، ".join(invalid_colors)
            )

        enabled_sizes = [size for size in sizes if request.POST.get(f"size_{size.id}")]
        if brand.name == "تکوین":
            enabled_sizes = [size for size in enabled_sizes if size.name in TAKVIN_SIZE_NAMES]

        if not form_code:
            errors.append("کد محصول را وارد کن.")
        if not form_title:
            errors.append("عنوان محصول را وارد کن.")
        if len(form_title) > 160:
            errors.append("عنوان محصول نباید بیشتر از ۱۶۰ کاراکتر باشد.")
        variable_color = brand.name == "دارما" and is_variable_color_product_code(form_code)
        if variable_color:
            expected_pack = int(variable_color_pack_qty(form_code) or 1)
            if form_pack_qty != expected_pack:
                errors.append(
                    f"تعداد پک {form_code} باید دقیقاً {expected_pack} باشد."
                )
            if comp_total != 0:
                errors.append(
                    f"{form_code} محصول رنگ‌متغیر است؛ ترکیب ثابت رنگ نباید ثبت شود."
                )
        elif comp_total != form_pack_qty:
            errors.append(
                f"جمع تعداد رنگ‌ها باید دقیقاً {form_pack_qty} باشد؛ الان {comp_total} است."
            )
        if not enabled_sizes:
            errors.append("حداقل یک سایز را برای این کد فعال کن.")
        if brand.name in MANAGED_BRANDS and form_effective < date.today():
            errors.append(
                "تاریخ شروع قیمت فروش نمی‌تواند قبل از امروز باشد؛ "
                "فروش تاریخی هرگز با تغییر قیمت پایه بازنویسی نمی‌شود."
            )

        for size in enabled_sizes:
            if max(0, _to_int(request.POST.get(f"sale_price_{size.id}"))) <= 0:
                errors.append(f"قیمت فروش سایز {size.name} باید بیشتر از صفر باشد.")

        duplicate = ProductCode.objects.filter(brand=brand, code=form_code)
        if product:
            duplicate = duplicate.exclude(id=product.id)
        if duplicate.exists():
            errors.append("این کد برای این برند قبلاً ثبت شده است.")

        if not errors:
            if not product:
                product = ProductCode()
            product.brand = brand
            product.code = form_code
            product.title = form_title
            product.pack_qty = form_pack_qty
            product.note = form_note
            product.active = form_active
            product.save()

            ProductComposition.objects.filter(product=product).delete()
            for color_id, qty in comp.items():
                ProductComposition.objects.create(product=product, color_id=color_id, qty=qty)

            selected_ids = {sz.id for sz in enabled_sizes}
            ProductSize.objects.filter(product=product).exclude(size_id__in=selected_ids).update(active=False)

            scheduled = 0
            for size in enabled_sizes:
                entered_price = max(0, _to_int(request.POST.get(f"sale_price_{size.id}")))
                entered_cost = max(0, _to_int(request.POST.get(f"unit_cost_{size.id}")))
                if brand.name == "تکوین":
                    entered_cost = int(takvin_cost_for(size))

                ps = ProductSize.objects.filter(product=product, size=size).first()
                if ps is None:
                    # A brand-new size has no previous selling price to preserve.
                    ps = ProductSize.objects.create(
                        product=product,
                        size=size,
                        default_sale_price=entered_price,
                        unit_cost=entered_cost,
                        active=True,
                    )
                else:
                    ps.active = True
                    ps.unit_cost = entered_cost
                    if brand.name not in MANAGED_BRANDS:
                        ps.default_sale_price = entered_price
                        ps.save(update_fields=["default_sale_price", "unit_cost", "active"])
                    else:
                        # For Darma/Takvin the legacy default remains the pre-V60
                        # fallback. The entered price is stored only as a dated rule,
                        # so a tomorrow rule can never leak into today's unsaved sale.
                        ps.save(update_fields=["unit_cost", "active"])

                if brand.name in MANAGED_BRANDS:
                    set_sale_price_rule(ps, form_effective, entered_price)
                    scheduled += 1

            if brand.name == "تکوین":
                ProductSize.objects.filter(
                    product=product, size__name__in=["3XL", "4XL"]
                ).update(active=False)

            if brand.name in MANAGED_BRANDS:
                messages.success(
                    request,
                    f"کد {product.code} ذخیره شد؛ قیمت فروش {scheduled} سایز از تاریخ "
                    f"{format_jalali(form_effective)} اعمال می‌شود. فروش‌های ثبت‌شده قبلی "
                    "و قیمت روزهای قبل از تاریخ شروع دست‌نخورده می‌مانند.",
                )
            else:
                messages.success(request, f"کد {product.code} ذخیره شد.")
            return redirect("/settings/products/?section=colors")

        for err in errors:
            messages.error(request, err)

    brand_inventory_color_ids = {
        brand.id: _inventory_color_ids_for_brand(brand)
        for brand in brands
        if brand.name in INVENTORY_COMPOSITION_BRANDS
    }

    color_rows = []
    for color in colors:
        qty = (
            max(0, _to_int(request.POST.get(f"color_{color.id}")))
            if request.method == "POST"
            else existing_comp.get(color.id, 0)
        )
        visible_brand_ids = []
        for brand in brands:
            if brand.name not in INVENTORY_COMPOSITION_BRANDS:
                visible_brand_ids.append(str(brand.id))
                continue
            linked = color.id in brand_inventory_color_ids.get(brand.id, set())
            legacy_existing = bool(
                product
                and product.brand_id == brand.id
                and color.id in existing_comp
            )
            if linked or legacy_existing:
                visible_brand_ids.append(str(brand.id))
        color_rows.append(
            {
                "obj": color,
                "qty": qty,
                "brand_ids": ",".join(visible_brand_ids),
            }
        )

    size_rows = []
    selected_brand = Brand.objects.filter(id=form_brand_id).first()
    for size in sizes:
        ps = existing_sizes.get(size.id)
        if request.method == "POST":
            checked = bool(request.POST.get(f"size_{size.id}"))
            sale_price = max(0, _to_int(request.POST.get(f"sale_price_{size.id}")))
            unit_cost = max(0, _to_int(request.POST.get(f"unit_cost_{size.id}")))
        else:
            checked = bool(ps and ps.active)
            if ps and selected_brand and selected_brand.name in MANAGED_BRANDS:
                nxt = next_sale_price_rule(ps)
                sale_price = int(nxt["price"]) if nxt else int(sale_price_for(ps, date.today()))
            else:
                sale_price = int(ps.default_sale_price or 0) if ps else 0
            unit_cost = int(ps.unit_cost or 0) if ps else 0
        if selected_brand and selected_brand.name == "تکوین" and size.name not in TAKVIN_SIZE_NAMES:
            checked = False
        size_rows.append(
            {
                "obj": size,
                "checked": checked,
                "sale_price": sale_price,
                "unit_cost": unit_cost,
                "takvin_forbidden": bool(size.name not in TAKVIN_SIZE_NAMES),
            }
        )

    return render(
        request,
        "core/settings_product_form_v60.html",
        {
            "product": product,
            "brands": brands,
            "color_rows": color_rows,
            "size_rows": size_rows,
            "form_brand_id": form_brand_id,
            "form_code": form_code,
            "form_title": form_title,
            "form_pack_qty": form_pack_qty,
            "form_note": form_note,
            "form_active": form_active,
            "sale_price_effective_j": format_jalali(form_effective),
            "sale_price_managed_brands": MANAGED_BRANDS,
        },
    )
