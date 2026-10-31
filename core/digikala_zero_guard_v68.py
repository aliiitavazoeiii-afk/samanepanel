import hashlib
import json
import os

from .digikala_client_v40 import DigikalaAPIError, get_json, put_json
from .digikala_zero_guard_v65 import (
    _product_uses_color,
    _resolved_identity,
    affected_variants_for_cell,
    stock_cell_total,
)


WRITE_ENV = "DIGIKALA_ZERO_GUARD_WRITE_ENABLED"
CONFIRM_TTL_SECONDS = 90


class DigikalaZeroWriteError(RuntimeError):
    def __init__(
        self,
        message,
        *,
        completed=None,
        failed_variant_id=None,
        write_attempted=False,
    ):
        super().__init__(message)
        self.completed = list(completed or [])
        self.failed_variant_id = failed_variant_id
        self.write_attempted = bool(write_attempted)


def _truthy(value):
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def write_enabled():
    return _truthy(os.getenv(WRITE_ENV))


def activation_path(variant_id):
    return f"/open-api/v1/variants/{int(variant_id)}/activation"


def variant_path(variant_id):
    return f"/open-api/v1/variants/{int(variant_id)}"


def _row_snapshot(row):
    return {
        "seller_variant_id": int(row.get("seller_variant_id") or 0),
        "dkpc": int(row.get("dkpc") or 0),
        "product_code": str(row.get("product_code") or ""),
        "size": str(row.get("size") or ""),
        "title": str(row.get("title") or ""),
        "active": bool(row.get("active")),
        "seller_stock": int(row.get("seller_stock") or 0),
        "warehouse_stock": int(row.get("warehouse_stock") or 0),
        "on_the_way_stock": int(row.get("on_the_way_stock") or 0),
    }


def _blocked_reason(row):
    reasons = []
    if int(row.get("warehouse_stock") or 0) > 0:
        reasons.append(f"Digikala warehouse={int(row.get('warehouse_stock') or 0)}")
    if int(row.get("on_the_way_stock") or 0) > 0:
        reasons.append(f"on-the-way={int(row.get('on_the_way_stock') or 0)}")
    return ", ".join(reasons)


def _fingerprint_payload(plan):
    cell = plan["cell"]
    return {
        "size_id": int(cell["size"].id),
        "color_id": int(cell["color"].id),
        "total": int(cell["total"]),
        "source_variant_count": int(plan.get("source_variant_count") or 0),
        "unresolved_darma_like": int(plan.get("unresolved_darma_like") or 0),
        "eligible": [_row_snapshot(row) for row in plan.get("eligible", [])],
        "blocked": [
            {"row": _row_snapshot(item["row"]), "reason": str(item["reason"])}
            for item in plan.get("blocked", [])
        ],
    }


def plan_fingerprint(plan):
    raw = json.dumps(
        _fingerprint_payload(plan),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def build_deactivation_plan(size_id, color_id, *, force=True, preview=None):
    cell = stock_cell_total(int(size_id), int(color_id))
    if int(cell["total"]) > 0:
        raise DigikalaZeroWriteError(
            f"موجودی {cell['color'].name} / {cell['size'].name} دیگر صفر نیست."
        )

    preview = preview or affected_variants_for_cell(
        cell["size"].id,
        cell["color"].id,
        force=force,
    )

    eligible = []
    blocked = []
    seen = set()
    for raw in preview.get("active_affected", []):
        row = _row_snapshot(raw)
        variant_id = int(row["seller_variant_id"])
        if variant_id <= 0 or variant_id in seen:
            continue
        seen.add(variant_id)
        reason = _blocked_reason(row)
        if reason:
            blocked.append({"row": row, "reason": reason})
        else:
            eligible.append(row)

    eligible.sort(key=lambda row: (row["product_code"], row["seller_variant_id"]))
    blocked.sort(key=lambda item: (item["row"]["product_code"], item["row"]["seller_variant_id"]))

    plan = {
        "cell": cell,
        "eligible": eligible,
        "blocked": blocked,
        "unresolved_darma_like": int(preview.get("unresolved_darma_like") or 0),
        "source_variant_count": int(preview.get("source_variant_count") or 0),
    }
    plan["fingerprint"] = plan_fingerprint(plan)
    return plan


def format_deactivation_plan(plan):
    cell = plan["cell"]
    eligible = plan["eligible"]
    blocked = plan["blocked"]
    lines = [
        "⚠️ آماده‌سازی غیرفعال‌سازی Digikala",
        f"{cell['color'].name} / {cell['size'].name}",
        f"خانه: {int(cell['home'])} | خورشید: {int(cell['khorshid'])} | کل: {int(cell['total'])}",
        "",
        f"قابل غیرفعال‌سازی بعد از تأیید نهایی: {len(eligible)}",
    ]
    for row in eligible[:20]:
        lines.append(
            f"• {row['product_code']} | {row['size']} | variant {row['seller_variant_id']} | "
            f"DKPC {row['dkpc'] or '—'}"
        )
    if len(eligible) > 20:
        lines.append(f"… و {len(eligible) - 20} مورد دیگر")

    if blocked:
        lines.append("")
        lines.append(f"🔒 مسدود به‌خاطر موجودی شبکه Digikala: {len(blocked)}")
        for item in blocked[:20]:
            row = item["row"]
            lines.append(
                f"• {row['product_code']} | variant {row['seller_variant_id']} | {item['reason']}"
            )

    if plan.get("unresolved_darma_like"):
        lines.extend(
            [
                "",
                f"ℹ️ Darma unresolved خارج از scope write: {plan['unresolved_darma_like']}",
                "هیچ unresolvedای هرگز با حدس غیرفعال نمی‌شود.",
            ]
        )

    lines.extend(
        [
            "",
            f"⏳ تأیید نهایی فقط {CONFIRM_TTL_SECONDS} ثانیه معتبر است.",
            "قبل از اولین PUT، موجودی و mapping دوباره از صفر بررسی می‌شوند.",
        ]
    )
    return "\n".join(lines)


def get_variant_scope():
    response = get_json("/open-api/v1/auth/scopes", timeout=10)
    data = response.get("data") if isinstance(response, dict) else None
    data = data if isinstance(data, dict) else {}
    items = data.get("items")
    items = items if isinstance(items, list) else []
    for item in items:
        if isinstance(item, dict) and str(item.get("key") or "").strip().lower() == "variant":
            return {
                "key": str(item.get("key") or ""),
                "title": str(item.get("title") or ""),
                "access": str(item.get("access") or ""),
            }
    return None


def _live_variant_data(variant_id):
    response = get_json(variant_path(variant_id), timeout=10)
    data = response.get("data") if isinstance(response, dict) else None
    if not isinstance(data, dict):
        raise DigikalaZeroWriteError(
            f"GET variant {variant_id} پاسخ معتبر نداد."
        )
    if int(data.get("id") or 0) != int(variant_id):
        raise DigikalaZeroWriteError(
            f"GET variant identity mismatch: expected={variant_id} got={data.get('id')}"
        )
    return data


def _verify_live_variant(row, cell):
    variant_id = int(row["seller_variant_id"])
    data = _live_variant_data(variant_id)
    product, size_name, title_used = _resolved_identity(data)

    if product is None or not size_name:
        raise DigikalaZeroWriteError(f"variant {variant_id} دیگر title/size قابل resolve ندارد.")
    if product.brand.name != "دارما":
        raise DigikalaZeroWriteError(f"variant {variant_id} دیگر Darma نیست.")
    if str(product.code) != str(row["product_code"]) or str(size_name) != str(row["size"]):
        raise DigikalaZeroWriteError(
            f"variant {variant_id} mapping عوض شده: {product.code}/{size_name}"
        )
    if int(cell["size"].id) <= 0 or str(size_name) != str(cell["size"].name):
        raise DigikalaZeroWriteError(f"variant {variant_id} size دیگر با سلول صفر یکی نیست.")
    if not _product_uses_color(product, title_used, cell["color"]):
        raise DigikalaZeroWriteError(
            f"variant {variant_id} دیگر به رنگ صفر {cell['color'].name} وابسته نیست."
        )
    if not bool(data.get("active")):
        raise DigikalaZeroWriteError(f"variant {variant_id} قبل از write دیگر فعال نیست.")
    if int(data.get("warehouse_stock") or 0) > 0:
        raise DigikalaZeroWriteError(
            f"variant {variant_id} در انبار Digikala موجودی دارد: {data.get('warehouse_stock')}"
        )
    if int(data.get("on_the_way_stock") or 0) > 0:
        raise DigikalaZeroWriteError(
            f"variant {variant_id} موجودی درراه Digikala دارد: {data.get('on_the_way_stock')}"
        )
    return data


def deactivate_variant(variant_id):
    response = put_json(
        activation_path(variant_id),
        {"activation": False},
        timeout=10,
    )
    data = response.get("data") if isinstance(response, dict) else None
    data = data if isinstance(data, dict) else {}
    if data.get("active") is not False:
        raise DigikalaZeroWriteError(
            f"Digikala برای variant {variant_id} پاسخ غیرفعال قطعی نداد."
        )
    return response


def execute_confirmed_deactivation(size_id, color_id, expected_fingerprint):
    if not write_enabled():
        raise DigikalaZeroWriteError(
            f"{WRITE_ENV} فعال نیست؛ هیچ write انجام نشد."
        )

    fresh = build_deactivation_plan(size_id, color_id, force=True)
    if str(fresh["fingerprint"]) != str(expected_fingerprint):
        raise DigikalaZeroWriteError(
            "plan نسبت به مرحله تأیید تغییر کرده؛ هیچ write انجام نشد. دوباره preview بگیر."
        )

    if not fresh["eligible"]:
        return {
            "completed": [],
            "blocked": fresh["blocked"],
            "message": "هیچ variant فعال و واجدشرایطی برای غیرفعال‌سازی باقی نمانده.",
        }

    verified = []
    for row in fresh["eligible"]:
        _verify_live_variant(row, fresh["cell"])
        verified.append(row)

    cell_now = stock_cell_total(int(size_id), int(color_id))
    if int(cell_now["total"]) > 0:
        raise DigikalaZeroWriteError(
            "موجودی داخلی حین re-check مثبت شد؛ هیچ write انجام نشد."
        )

    completed = []
    for row in verified:
        variant_id = int(row["seller_variant_id"])
        try:
            deactivate_variant(variant_id)
            completed.append(variant_id)
            after = _live_variant_data(variant_id)
            if bool(after.get("active")):
                raise DigikalaZeroWriteError(
                    f"variant {variant_id} بعد از PUT هنوز active گزارش شد."
                )
            print(
                f"DIGIKALA V68 DEACTIVATED variant={variant_id} "
                f"product={row['product_code']} size={row['size']} "
                f"cell={fresh['cell']['color'].name}/{fresh['cell']['size'].name}",
                flush=True,
            )
        except Exception as exc:
            raise DigikalaZeroWriteError(
                f"غیرفعال‌سازی روی variant {variant_id} متوقف شد: {exc}",
                completed=completed,
                failed_variant_id=variant_id,
                write_attempted=True,
            ) from exc

    return {
        "completed": completed,
        "blocked": fresh["blocked"],
        "message": f"{len(completed)} variant با تأیید کاربر غیرفعال شد.",
    }
