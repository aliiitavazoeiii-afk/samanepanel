from __future__ import annotations

import os
import re
from collections import defaultdict
from dataclasses import dataclass
from io import BytesIO
from zipfile import BadZipFile, ZipFile
from xml.etree import ElementTree as ET

from django.db import transaction

from .finance import digikala_fee_for_unit
from .final_services import inventory_unit_cost, setting_decimal, sync_sale_inventory
from .models import (
    AccountEntry,
    ProductCode,
    ProductSize,
    SaleDay,
    SaleLine,
    SaleSnapshot,
)


MAIN_NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
OFFICE_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
BLOCKED_RETURN_FILENAMES = {"packageDeliveryReport_17851669002377.xlsx"}

PERSIAN_DIGITS = str.maketrans(
    {
        "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4",
        "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
        "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4",
        "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
    }
)

SIZE_ALIASES = {
    "m": "M", "36-38": "M", "36–38": "M",
    "l": "L", "38-40": "L", "38–40": "L",
    "xl": "XL", "40-42": "XL", "40–42": "XL",
    "xxl": "XXL", "42-44": "XXL", "42–44": "XXL",
    "3xl": "3XL", "xxxl": "3XL", "44-46": "3XL", "44–46": "3XL",
    "4xl": "4XL", "xxxxl": "4XL", "46-48": "4XL", "46–48": "4XL",
}

# Seller-code aliases seen in the user's Digikala delivery reports.
# 06 and pack6 are intentionally one Darma product.
SELLER_CODE_ALIASES = {
    "pack5": ("دارما", "pack 5"),
    "pack05": ("دارما", "pack 5"),
    "rah110": ("دارما", "rah-110"),
    "rah220": ("دارما", "rah-220"),
    "op": ("دارما", "op"),
    "opbnw": ("دارما", "op"),
    "110": ("دارما", "D 110"), "d110": ("دارما", "D 110"),
    "220": ("دارما", "D 220"), "d220": ("دارما", "D 220"),
    "330": ("دارما", "D 330"), "d330": ("دارما", "D 330"),
    "440": ("دارما", "D 440"), "d440": ("دارما", "D 440"),
    "550": ("دارما", "D 550"), "d550": ("دارما", "D 550"),
    "660": ("دارما", "D 660"), "d660": ("دارما", "D 660"),
    "770": ("دارما", "770"),
    "880": ("دارما", "880"),
    "990": ("دارما", "990"),
    "400": ("دارما", "400"),
    "06": ("دارما", "06"),
    "6": ("دارما", "06"),
    "pack6": ("دارما", "06"),
    "p12": ("دارما", "p12"),
    "pgw": ("دارما", "pgw"),
}

REQUIRED_HEADERS = {"عنوان", "تعداد ارسالی"}


class DailyOrderImportError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedOrderRow:
    source_row: int
    seller_code: str
    title: str
    quantity: int
    status: str


@dataclass(frozen=True)
class ResolvedOrderRow:
    source_row: int
    brand_name: str
    product_code: str
    size_name: str
    quantity: int


def _norm_text(value) -> str:
    return (
        str(value or "")
        .translate(PERSIAN_DIGITS)
        .replace("ي", "ی")
        .replace("ك", "ک")
        .replace("\u200c", " ")
        .strip()
    )


def _compact_code(value) -> str:
    return re.sub(r"[\s_\-]+", "", _norm_text(value)).lower()


def _safe_int(value, default=0) -> int:
    try:
        text = _norm_text(value).replace("٬", "").replace(",", "").strip()
        if not text:
            return default
        return int(float(text))
    except Exception:
        return default


def _column_index(cell_ref: str) -> int:
    match = re.match(r"([A-Z]+)", cell_ref or "")
    if not match:
        return 0
    value = 0
    for ch in match.group(1):
        value = value * 26 + ord(ch) - 64
    return value - 1


def _first_sheet_path(zf: ZipFile) -> str:
    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    sheet = workbook.find("a:sheets/a:sheet", MAIN_NS)
    if sheet is None:
        raise DailyOrderImportError("فایل اکسل هیچ Sheet قابل خواندنی ندارد.")
    rel_id = sheet.attrib.get(f"{{{OFFICE_REL_NS}}}id")
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    target = None
    for rel in rels:
        if rel.attrib.get("Id") == rel_id:
            target = rel.attrib.get("Target")
            break
    if not target:
        raise DailyOrderImportError("Sheet اول فایل اکسل پیدا نشد.")
    if target.startswith("/"):
        return target.lstrip("/")
    return "xl/" + target.lstrip("./")


def _read_first_sheet(file_bytes: bytes) -> list[list[str]]:
    try:
        with ZipFile(BytesIO(file_bytes)) as zf:
            shared_strings: list[str] = []
            if "xl/sharedStrings.xml" in zf.namelist():
                root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
                for si in root.findall("a:si", MAIN_NS):
                    shared_strings.append("".join((node.text or "") for node in si.findall(".//a:t", MAIN_NS)))

            sheet_path = _first_sheet_path(zf)
            root = ET.fromstring(zf.read(sheet_path))
            rows: list[list[str]] = []
            for row in root.findall(".//a:sheetData/a:row", MAIN_NS):
                values: dict[int, str] = {}
                for cell in row.findall("a:c", MAIN_NS):
                    index = _column_index(cell.attrib.get("r", "A1"))
                    cell_type = cell.attrib.get("t")
                    if cell_type == "inlineStr":
                        value = "".join((node.text or "") for node in cell.findall(".//a:t", MAIN_NS))
                    else:
                        value_node = cell.find("a:v", MAIN_NS)
                        raw = value_node.text if value_node is not None else ""
                        if cell_type == "s" and raw != "":
                            try:
                                value = shared_strings[int(raw)]
                            except Exception:
                                value = raw
                        else:
                            value = raw
                    values[index] = value
                if values:
                    last = max(values)
                    rows.append([values.get(i, "") for i in range(last + 1)])
            return rows
    except (BadZipFile, KeyError, ET.ParseError) as exc:
        raise DailyOrderImportError("فایل معتبر XLSX نیست یا ساختار آن قابل خواندن نیست.") from exc


def parse_delivery_report(file_bytes: bytes, filename: str = "") -> tuple[list[ParsedOrderRow], dict]:
    basename = os.path.basename(filename or "")
    if basename in BLOCKED_RETURN_FILENAMES:
        raise DailyOrderImportError("این فایل قبلاً به‌عنوان صورت مرجوعی مشخص شده و نباید وارد فروش روزانه شود.")
    if not file_bytes:
        raise DailyOrderImportError("فایل خالی است.")
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise DailyOrderImportError("حجم فایل بیشتر از ۱۰ مگابایت است.")

    rows = _read_first_sheet(file_bytes)
    if not rows:
        raise DailyOrderImportError("فایل هیچ ردیفی ندارد.")

    header_index = None
    headers: dict[str, int] = {}
    for idx, row in enumerate(rows[:10]):
        current = {_norm_text(value): col for col, value in enumerate(row) if _norm_text(value)}
        if REQUIRED_HEADERS.issubset(current):
            header_index = idx
            headers = current
            break
    if header_index is None:
        raise DailyOrderImportError("ستون‌های «عنوان» و «تعداد ارسالی» در فایل پیدا نشد.")

    result: list[ParsedOrderRow] = []
    ignored = 0
    raw_qty = 0
    for row_number, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
        def value(name: str) -> str:
            col = headers.get(name)
            if col is None or col >= len(row):
                return ""
            return _norm_text(row[col])

        quantity = max(0, _safe_int(value("تعداد ارسالی")))
        status = value("وضعیت")
        title = value("عنوان")
        seller_code = value("کد فروشنده")
        if quantity <= 0:
            ignored += 1
            continue
        # Delivery report should count rows actually received. Blank status is accepted
        # for older exports that omitted the status column entirely.
        if status and "دریافت" not in status:
            ignored += 1
            continue
        result.append(
            ParsedOrderRow(
                source_row=row_number,
                seller_code=seller_code,
                title=title,
                quantity=quantity,
                status=status,
            )
        )
        raw_qty += quantity

    if not result:
        raise DailyOrderImportError("هیچ ردیف دریافت‌شده با تعداد ارسالی بیشتر از صفر در فایل پیدا نشد.")
    return result, {"source_rows": len(result), "ignored_rows": ignored, "raw_quantity": raw_qty}


def _title_model_candidate(title: str) -> str:
    match = re.search(r"مدل\s+(.+?)\s+مجموعه", _norm_text(title), re.IGNORECASE)
    if not match:
        return ""
    candidate = match.group(1).strip()
    candidate = re.sub(r"^نخی\s+", "", candidate, flags=re.IGNORECASE)
    return candidate


def _resolve_size(title: str) -> str | None:
    for part in str(title or "").split("|"):
        key = _norm_text(part).lower().replace(" ", "")
        if key in SIZE_ALIASES:
            return SIZE_ALIASES[key]
    return None


def _product_maps():
    products = list(ProductCode.objects.select_related("brand").filter(active=True))
    by_key: dict[str, list[ProductCode]] = defaultdict(list)
    for product in products:
        by_key[_compact_code(product.code)].append(product)
    return by_key


def _resolve_product(seller_code: str, title: str, by_key) -> ProductCode | None:
    # Do not collapse unknown seller color codes such as s3/S3; exact raw values are
    # preserved. We only compact known product aliases and actual configured codes.
    seller_key = _compact_code(seller_code)
    alias = SELLER_CODE_ALIASES.get(seller_key)
    if alias:
        brand_name, code = alias
        return ProductCode.objects.filter(brand__name=brand_name, code=code, active=True).first()
    if seller_key and len(by_key.get(seller_key, [])) == 1:
        return by_key[seller_key][0]

    candidate = _title_model_candidate(title)
    candidate_key = _compact_code(candidate)
    alias = SELLER_CODE_ALIASES.get(candidate_key)
    if alias:
        brand_name, code = alias
        return ProductCode.objects.filter(brand__name=brand_name, code=code, active=True).first()

    candidates = by_key.get(candidate_key, [])
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        preferred_brand = "تکوین" if "تکوین" in title else "دارما" if "دارما" in title else ""
        if preferred_brand:
            for product in candidates:
                if product.brand.name == preferred_brand:
                    return product
    return None


def resolve_rows(parsed_rows: list[ParsedOrderRow]) -> tuple[list[ResolvedOrderRow], list[str]]:
    by_key = _product_maps()
    resolved: list[ResolvedOrderRow] = []
    errors: list[str] = []
    for row in parsed_rows:
        product = _resolve_product(row.seller_code, row.title, by_key)
        size_name = _resolve_size(row.title)
        if product is None:
            shown_code = row.seller_code or _title_model_candidate(row.title) or "بدون کد"
            errors.append(f"ردیف {row.source_row}: کد «{shown_code}» به محصول سایت وصل نشد.")
            continue
        if not size_name:
            errors.append(f"ردیف {row.source_row}: سایز از عنوان «{row.title}» تشخیص داده نشد.")
            continue
        ps = ProductSize.objects.filter(product=product, size__name=size_name, active=True).select_related("size").first()
        if ps is None:
            errors.append(f"ردیف {row.source_row}: {product.brand.name} / {product.code} / {size_name} در سایت فعال نیست.")
            continue
        resolved.append(
            ResolvedOrderRow(
                source_row=row.source_row,
                brand_name=product.brand.name,
                product_code=product.code,
                size_name=size_name,
                quantity=row.quantity,
            )
        )
    return resolved, errors


def aggregate_rows(rows: list[ResolvedOrderRow]) -> dict[tuple[str, str, str], int]:
    grouped: dict[tuple[str, str, str], int] = defaultdict(int)
    for row in rows:
        grouped[(row.brand_name, row.product_code, row.size_name)] += int(row.quantity)
    return dict(grouped)


def preview_delivery_report(file_bytes: bytes, filename: str = "") -> dict:
    parsed, meta = parse_delivery_report(file_bytes, filename)
    resolved, errors = resolve_rows(parsed)
    grouped = aggregate_rows(resolved)
    rows = [
        {"brand": brand, "code": code, "size": size, "quantity": qty}
        for (brand, code, size), qty in sorted(grouped.items(), key=lambda x: (x[0][0], x[0][2], x[0][1]))
    ]
    return {
        **meta,
        "filename": os.path.basename(filename or ""),
        "rows": rows,
        "errors": errors,
        "grouped_lines": len(rows),
        "total_quantity": sum(row["quantity"] for row in rows),
    }


def _snapshot_line(line: SaleLine, ps: ProductSize, price: int):
    snap, _ = SaleSnapshot.objects.get_or_create(sale_line=line)
    snap.pack_qty = int(ps.product.pack_qty or 0)
    if ps.unit_cost:
        snap.unit_cost = int(ps.unit_cost)
    elif ps.product.brand.name == "دارما":
        snap.unit_cost = int(setting_decimal("darma_accounting_unit_cost", 61000))
    else:
        snap.unit_cost = int(inventory_unit_cost(ps.product.brand, ps.size))
    snap.digikala_fee_unit = digikala_fee_for_unit(price)
    snap.save()


@transaction.atomic
def apply_delivery_report(day: SaleDay, file_bytes: bytes, filename: str = "") -> dict:
    preview = preview_delivery_report(file_bytes, filename)
    if preview["errors"]:
        raise DailyOrderImportError("\n".join(preview["errors"]))

    grouped = {
        (row["brand"], row["code"], row["size"]): int(row["quantity"])
        for row in preview["rows"]
    }

    targets: dict[int, int] = {}
    product_sizes: dict[int, ProductSize] = {}
    for (brand_name, code, size_name), qty in grouped.items():
        ps = ProductSize.objects.select_related("product__brand", "size").get(
            product__brand__name=brand_name,
            product__code=code,
            size__name=size_name,
            active=True,
            product__active=True,
        )
        targets[ps.id] = qty
        product_sizes[ps.id] = ps

    existing_lines = {
        line.product_size_id: line
        for line in SaleLine.objects.select_for_update().filter(day=day).select_related("product_size__product__brand", "product_size__size")
    }

    # Replacement semantics: the uploaded file becomes the truth for this date.
    # Existing lines missing from the new file are set to zero so inventory is restored.
    all_ps_ids = set(existing_lines) | set(targets)
    shortage_count = 0
    changed_lines = 0
    for ps_id in all_ps_ids:
        ps = product_sizes.get(ps_id)
        line = existing_lines.get(ps_id)
        if ps is None and line is not None:
            ps = line.product_size
        qty = targets.get(ps_id, 0)
        if line is None:
            price = int(ps.default_sale_price or 0)
            line = SaleLine.objects.create(day=day, product_size=ps, quantity=0, sale_price=price)
        else:
            price = int(line.sale_price or ps.default_sale_price or 0)

        if int(line.quantity or 0) != qty or int(line.sale_price or 0) != price:
            changed_lines += 1
        line.quantity = qty
        line.sale_price = price
        line.save(update_fields=["quantity", "sale_price"])
        if qty > 0:
            _snapshot_line(line, ps, price)
        result = sync_sale_inventory(line)
        shortage_count += len(result.get("shortages") or [])
        # Excel-Web keeps financial balances manual, same as manual daily entry.
        AccountEntry.objects.filter(reference=f"sale:{line.id}:digikala").delete()

    preview["changed_lines"] = changed_lines
    preview["shortage_count"] = shortage_count
    preview["sale_day_id"] = day.id
    return preview
